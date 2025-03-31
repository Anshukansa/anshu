import os
import sys
from collections import defaultdict
import logging
import asyncio
import random
import sqlite3
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
from config import configure_chrome_options
from telegram_utils import send_messages_sequentially, send_message, edit_message
from product_checking import product_checker
from location_check import reverse_geocode, calculate_distance
import re
from selenium.webdriver.common.keys import Keys
from datetime import datetime
import json
from time_management import is_monitoring_active, get_monitoring_schedule

# Set UTF-8 Encoding for Console and Logging
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# Configure Logging with UTF-8 Encoding
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("app.log", encoding="utf-8")
    ]
)

# Configure a separate logger for sent messages
message_logger = logging.getLogger("SentMessagesLogger")
message_logger.setLevel(logging.INFO)
message_file_handler = logging.FileHandler("sent_messages.log", encoding="utf-8")
message_file_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
message_logger.addHandler(message_file_handler)

# Configure a separate logger for monitoring schedule
schedule_logger = logging.getLogger("MonitoringScheduleLogger")
schedule_logger.setLevel(logging.INFO)
schedule_file_handler = logging.FileHandler("monitoring_schedule.log", encoding="utf-8")
schedule_file_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
schedule_logger.addHandler(schedule_file_handler)

# Global dictionaries to track monitoring status
LOCATION_STATUS = {}  # Tracks the active/inactive status for each location
LOCATION_USERS = defaultdict(set)  # Maps locations to user IDs

def fetch_users_from_db(db_path="users.db"):
    """Fetch user data from the SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users")
    users = []
    user_columns = [col[0] for col in cursor.description]
    for row in cursor.fetchall():
        user = dict(zip(user_columns, row))
        user["keywords"] = fetch_user_keywords(conn, user["unique_userid"])
        user["excluded_words"] = fetch_user_excluded_words(conn, user["unique_userid"])
        user["modes"] = fetch_user_modes(conn, user["unique_userid"])  # Fetch modes
        users.append(user)

    conn.close()
    return users

def fetch_user_modes(conn, unique_userid):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT mode_only_preferred, near_good_deals, good_deals FROM user_modes WHERE unique_userid = ?",
        (unique_userid,)
    )
    row = cursor.fetchone()
    if row:
        return {
            "mode_only_preferred": row[0],
            "near_good_deals": row[1],
            "good_deals": row[2],
        }
    return {"mode_only_preferred": 0, "near_good_deals": 0, "good_deals": 0}

def fetch_user_keywords(conn, unique_userid):
    cursor = conn.cursor()
    cursor.execute("SELECT keyword FROM keywords WHERE unique_userid = ?", (unique_userid,))
    return [row[0] for row in cursor.fetchall()]

def fetch_user_excluded_words(conn, unique_userid):
    cursor = conn.cursor()
    cursor.execute("SELECT excluded_word FROM excluded_words WHERE unique_userid = ?", (unique_userid,))
    return [row[0] for row in cursor.fetchall()]

def save_monitoring_status(status_filename="monitoring_status.json"):
    """Save the current monitoring status to a JSON file."""
    status_data = {
        "locations": {
            location: {
                "is_active": status["is_active"],
                "last_updated": datetime.now().isoformat(),
                "next_change": status["next_change"],
                "next_status": status["next_status"]
            }
            for location, status in LOCATION_STATUS.items()
        },
        "updated_at": datetime.now().isoformat()
    }
    
    with open(status_filename, "w", encoding="utf-8") as status_file:
        json.dump(status_data, status_file, indent=4)
    
    logging.info(f"Monitoring status saved to {status_filename}")

async def notify_status_change(location, is_active, reason, next_change_time=None):
    """Notify users about monitoring status changes for a location."""
    if location not in LOCATION_USERS:
        return
    
    user_ids = LOCATION_USERS[location]
    
    if is_active:
        message = (
            f"📢 Monitoring has been resumed for {location.title()}.\n"
            f"Reason: {reason}\n"
            f"Will stop at: {next_change_time.strftime('%H:%M') if next_change_time else 'Unknown'}"
        )
    else:
        message = (
            f"🛑 Monitoring has been paused for {location.title()}.\n"
            f"Reason: {reason}\n"
            f"Will resume at: {next_change_time.strftime('%H:%M') if next_change_time else 'Unknown'}"
        )
    
    # Send notifications to all users subscribed to this location
    notification_tasks = [send_message(message, user_id) for user_id in user_ids]
    await asyncio.gather(*notification_tasks)
    
    # Log the status change
    schedule_logger.info(f"Status change for {location}: {'Active' if is_active else 'Inactive'} - {reason}")

def generate_pairs_and_log(users, log_filename="pairs_log.txt"):
    """Generate unique keyword-location pairs and log them."""
    pairs = set()
    user_pair_map = defaultdict(list)
    active_pairs = set()
    
    # Clear previous location-user mappings
    LOCATION_USERS.clear()

    today = datetime.now().date()

    for user in users:
        activation_status = user.get("activation_status", 0)
        expiry_date = user.get("expiry_date", "1970-01-01")
        expiry_date_obj = datetime.strptime(expiry_date, "%Y-%m-%d").date()

        if not activation_status or expiry_date_obj < today:
            logging.info(
                f"Skipping user {user['user_id']} due to inactive status or expired subscription."
            )
            continue

        keywords = user["keywords"]
        location = user["location"]
        chat_id = user["user_id"]
        excluded_words = user.get("excluded_words", [])
        fixed_lat = user["fixed_lat"]
        fixed_lon = user["fixed_lon"]
        
        # Add user to location mapping for notifications
        LOCATION_USERS[location.lower()].add(chat_id)

        for keyword in keywords:
            pair = (keyword, location)
            pairs.add(pair)
            
            # Check if monitoring is active for this location
            is_active, reason, next_change_time = is_monitoring_active(location)
            
            # Update global status tracking
            if location.lower() not in LOCATION_STATUS or LOCATION_STATUS[location.lower()]["is_active"] != is_active:
                LOCATION_STATUS[location.lower()] = get_monitoring_schedule(location)
            
            # Only add to active pairs if monitoring is active
            if is_active:
                active_pairs.add(pair)
            
            user_pair_map[pair].append({
                "chat_id": chat_id,
                "excluded_words": excluded_words,
                "fixed_lat": fixed_lat,
                "fixed_lon": fixed_lon,
                "modes": user["modes"]  # Pass modes for the user
            })

    # Log all pairs (both active and inactive)
    with open(log_filename, "w") as log_file:
        for keyword, location in pairs:
            is_active, reason, _ = is_monitoring_active(location)
            status = "ACTIVE" if is_active else "PAUSED"
            log_file.write(f"{keyword} - {location} [{status}] - {reason}\n")
    
    # Save current monitoring status to file
    save_monitoring_status()
    
    return active_pairs, user_pair_map

async def check_marketplace_pair(pair, user_data, seen_listings, first_run):
    keyword, location = pair
    
    # Check if monitoring should be active for this location
    is_active, reason, next_change_time = is_monitoring_active(location)
    
    # If not active, log and return early
    if not is_active:
        logging.info(f"Skipping pair {pair}: {reason}")
        
        # Check if status has changed and notify users
        if location.lower() in LOCATION_STATUS and LOCATION_STATUS[location.lower()]["is_active"] != is_active:
            await notify_status_change(location.lower(), is_active, reason, next_change_time)
            LOCATION_STATUS[location.lower()] = get_monitoring_schedule(location)
            save_monitoring_status()
        
        return
    
    # Check if status has changed to active and notify users
    if location.lower() in LOCATION_STATUS and LOCATION_STATUS[location.lower()]["is_active"] != is_active:
        await notify_status_change(location.lower(), is_active, reason, next_change_time)
        LOCATION_STATUS[location.lower()] = get_monitoring_schedule(location)
        save_monitoring_status()
    
    min_price = random.randint(90, 100)
    max_price = random.randint(990, 1000)
    url = f"https://www.facebook.com/marketplace/{location}/search?minPrice={min_price}&maxPrice={max_price}&daysSinceListed=1&sortBy=creation_time_descend&query={keyword}"

    chrome_options = configure_chrome_options()
    driver = webdriver.Chrome(options=chrome_options)

    try:
        driver.get(url)
        await asyncio.sleep(2)
        driver.refresh()

        WebDriverWait(driver, 5).until(
            EC.presence_of_all_elements_located((By.CLASS_NAME, "xjp7ctv"))
        )

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        listings = soup.find_all('div', class_='xjp7ctv')

        for listing in listings:
            link_element = listing.find('a', class_='x1i10hfl')
            price_element = listing.find('div', class_='x1gslohp')
            title_element = listing.find('span', class_='x1lliihq x6ikm8r x10wlt62 x1n2onr6')

            if not (link_element and price_element and title_element):
                continue

            link = link_element.get('href')
            if not link:
                continue

            price = price_element.get_text(strip=True)
            title = title_element.get_text(strip=True)

            if first_run[pair]:
                seen_listings.add(link)
                logging.info(f"First run for {pair}, stored: {title} | {price}")
                continue

            if link in seen_listings:
                continue
            seen_listings.add(link)

            partial_sent_map = {}

            for user in user_data[pair]:
                chat_id = user["chat_id"]
                fixed_lat = user["fixed_lat"]
                fixed_lon = user["fixed_lon"]
                modes = user["modes"]


                excluded_words = user["excluded_words"]
                if any(word.lower() in title.lower() for word in excluded_words):
                    logging.info(
                        f"SKIP user {chat_id}: Title contains excluded word. "
                        f"Title='{title}' Excluded={excluded_words}"
                    )
                    continue

                result = product_checker(chat_id, title, price)
                product_name = result.get("product_name")
                preferred = result.get("preferred")
                is_good_deal = result.get("is_good_deal", False)
                near_good_deal = result.get("near_good_deal", False)

                if modes["mode_only_preferred"] and preferred != 1:
                    logging.info(f"SKIP user {chat_id}: Product '{product_name}' not preferred.")
                    continue

                if modes["near_good_deals"] and not (is_good_deal or near_good_deal):
                    logging.info(
                        f"SKIP user {chat_id}: Product '{product_name}' is neither a good deal nor near good deal."
                    )
                    continue

                if modes["good_deals"] and not is_good_deal:
                    logging.info(f"SKIP user {chat_id}: Product '{product_name}' is not a good deal.")
                    continue

                if is_good_deal:
                    deal_message = "✅ Good Deal @ "
                elif near_good_deal:
                    deal_message = "⚠️ Near Good Deal @ "
                else:
                    deal_message = ""

                partial_text = (
                    f"{deal_message}For {price}\n"
                    f"Link: https://www.facebook.com{link}"
                )

                try:
                    sent_msg = await send_message(partial_text, chat_id)
                    if sent_msg is not None:
                        partial_sent_map[chat_id] = (
                            sent_msg.message_id,
                            deal_message,
                            fixed_lat,
                            fixed_lon
                        )
                    else:
                        logging.error(f"Failed to send initial message to {chat_id}")
                except Exception as e:
                    logging.error(f"Exception sending message to {chat_id}: {e}", exc_info=True)

            if not partial_sent_map:
                continue

            address = "Unknown Address"
            latitude = None
            longitude = None

            driver.execute_script("window.open(arguments[0], '_blank');", link)
            driver.switch_to.window(driver.window_handles[-1])
            try:
                await asyncio.sleep(2)

                detail_soup = BeautifulSoup(driver.page_source, 'html.parser')
                
                # Debug - save HTML for inspection
                logging.debug(f"Analyzing listing detail page for {link}")
                
                # Find div with background-image containing static_map.php
                div = detail_soup.find('div', style=re.compile('background-image.*static_map'))
                
                if div:
                    style = div.get('style', '')
                    logging.debug(f"Found map div with style: {style}")
                    url_match = re.search(r'url\("([^"]+)"\)', style)
                    
                    if url_match:
                        img_url = url_match.group(1)
                        logging.debug(f"Extracted map URL: {img_url}")
                        coords_match = re.search(r'center=([-0-9.]+)%2C([-0-9.]+)', img_url)
                        
                        if coords_match:
                            latitude = float(coords_match.group(1))
                            longitude = float(coords_match.group(2))
                            logging.info(f"Extracted coordinates: ({latitude}, {longitude})")
                            address = reverse_geocode(latitude, longitude)
                        else:
                            logging.warning(f"Could not extract coordinates from URL: {img_url}")
                else:
                    # Alternative method - look for div with specific classes that might contain the map
                    map_div = detail_soup.find('div', class_='x13vifvy')
                    if map_div and 'style' in map_div.attrs:
                        style = map_div.get('style', '')
                        url_match = re.search(r'background-image: url\("([^"]+)"\)', style)
                        
                        if url_match:
                            img_url = url_match.group(1)
                            coords_match = re.search(r'center=([-0-9.]+)%2C([-0-9.]+)', img_url)
                            
                            if coords_match:
                                latitude = float(coords_match.group(1))
                                longitude = float(coords_match.group(2))
                                logging.info(f"Extracted coordinates (alt method): ({latitude}, {longitude})")
                                address = reverse_geocode(latitude, longitude)
                    else:
                        # Save a sample of the HTML for debugging
                        with open(f"listing_debug_{random.randint(1000, 9999)}.html", "w", encoding="utf-8") as f:
                            f.write(detail_soup.prettify())

            except Exception as e:
                logging.error(f"Error fetching detail for listing {link}: {e}")
            finally:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])

            for chat_id, (msg_id, user_deal_message, fixed_lat, fixed_lon) in partial_sent_map.items():
                try:
                    # Check if we have valid coordinates
                    if latitude is None or longitude is None:
                        logging.warning(f"Missing coordinates for listing {link}, can't calculate distance")
                        updated_text = (
                            f"{user_deal_message}{address} (Distance unknown) For {price}\n"
                            f"Link: https://www.facebook.com{link}"
                        )
                    else:
                        distance = calculate_distance(fixed_lat, fixed_lon, latitude, longitude)
                        
                        logging.info(f"Updating message for chat_id={chat_id}, msg_id={msg_id}")
                        logging.info(f"  Address: {address}")
                        logging.info(f"  Distance: {distance}")
                        logging.info(f"  Coordinates: listing=({latitude}, {longitude}), user=({fixed_lat}, {fixed_lon})")
                        
                        updated_text = (
                            f"{user_deal_message}{address} ({distance}) For {price}\n"
                            f"Link: https://www.facebook.com{link}"
                        )
                    
                    result = await edit_message(chat_id, msg_id, updated_text)
                    if not result:
                        logging.error(f"Failed to update message {msg_id} for chat_id {chat_id}")
                except Exception as e:
                    logging.error(f"Error updating message for chat_id={chat_id}: {e}", exc_info=True)
                    # Try to still send a message even if distance calculation fails
                    try:
                        fallback_text = (
                            f"{user_deal_message}Location update failed. For {price}\n"
                            f"Link: https://www.facebook.com{link}"
                        )
                        await edit_message(chat_id, msg_id, fallback_text)
                    except Exception:
                        logging.error("Failed to send fallback message update", exc_info=True)

        first_run[pair] = False

    except Exception as e:
        logging.error(f"Error checking pair {pair}: {e}")
    finally:
        driver.quit()

async def check_and_update_schedules(users, user_pair_map, full_pairs):
    """Check for schedule changes and update active pairs."""
    location_updates = {}
    
    for keyword, location in full_pairs:
        is_active, reason, next_change_time = is_monitoring_active(location)
        location_key = location.lower()
        
        # Check if status has changed since last check
        if (location_key in LOCATION_STATUS and 
            LOCATION_STATUS[location_key]["is_active"] != is_active):
            
            location_updates[location_key] = (is_active, reason, next_change_time)
    
    # Send notifications for all status changes
    for location, (is_active, reason, next_change_time) in location_updates.items():
        await notify_status_change(location, is_active, reason, next_change_time)
        LOCATION_STATUS[location] = get_monitoring_schedule(location)
    
    # Save updated status
    if location_updates:
        save_monitoring_status()
        logging.info(f"Updated monitoring status for {len(location_updates)} locations")

async def monitor_all_pairs_together(users, bot):
    # Generate all pairs, but get only active pairs for monitoring
    active_pairs, user_pair_map = generate_pairs_and_log(users)
    
    # Get the full set of pairs (active and inactive)
    full_pairs = set()
    for pair in user_pair_map.keys():
        full_pairs.add(pair)
    
    seen_listings = set()
    first_run = {pair: True for pair in full_pairs}
    
    # Initialize location status
    for keyword, location in full_pairs:
        location_key = location.lower()
        if location_key not in LOCATION_STATUS:
            LOCATION_STATUS[location_key] = get_monitoring_schedule(location)
    
    # Initial save of monitoring status
    save_monitoring_status()
    
    # Send initial status notifications
    for location, status in LOCATION_STATUS.items():
        if location in LOCATION_USERS:
            await notify_status_change(
                location,
                status["is_active"],
                f"Initial monitoring status: {'Active' if status['is_active'] else 'Inactive'}",
                datetime.fromisoformat(status["next_change"]) if status["next_change"] else None
            )

    while True:
        # Regenerate active pairs in case any location's schedule has changed
        active_pairs, user_pair_map = generate_pairs_and_log(users)
        
        # Check and update schedules every cycle
        await check_and_update_schedules(users, user_pair_map, full_pairs)
        
        # Only check active pairs
        if active_pairs:
            tasks = [
                check_marketplace_pair(pair, user_pair_map, seen_listings, first_run)
                for pair in active_pairs
            ]
            await asyncio.gather(*tasks)
            
            delay = random.uniform(15, 25)
            logging.info(f"Round done. Checked {len(active_pairs)} active pairs. Waiting for {delay:.2f} seconds.")
            await asyncio.sleep(delay)
        else:
            # All pairs are inactive, wait for a longer period
            delay = random.uniform(180, 300)  # 3-5 minutes
            logging.info(f"All {len(full_pairs)} pairs are inactive. Waiting for {delay:.2f} seconds.")
            await asyncio.sleep(delay)
