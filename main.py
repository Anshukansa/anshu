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

def generate_pairs_and_log(users, log_filename="pairs_log.txt"):
    """Generate unique keyword-location pairs and log them."""
    pairs = set()
    user_pair_map = defaultdict(list)

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

        for keyword in keywords:
            pair = (keyword, location)
            pairs.add(pair)
            user_pair_map[pair].append({
                "chat_id": chat_id,
                "excluded_words": excluded_words,
                "fixed_lat": fixed_lat,
                "fixed_lon": fixed_lon,
                "modes": user["modes"]  # Pass modes for the user
            })

    with open(log_filename, "w") as log_file:
        for keyword, location in pairs:
            log_file.write(f"{keyword} - {location}\n")

    return pairs, user_pair_map

async def check_marketplace_pair(pair, user_data, seen_listings, first_run):
    keyword, location = pair
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

                sent_msg = await send_message(partial_text, chat_id)
                if sent_msg is not None:
                    partial_sent_map[chat_id] = (
                        sent_msg.message_id,
                        deal_message,
                        fixed_lat,
                        fixed_lon
                    )

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
                div = detail_soup.find('div', style=re.compile('background-image'))
                if div:
                    style = div.get('style', '')
                    url_match = re.search(r'url\("([^"]+)"\)', style)
                    if url_match:
                        img_url = url_match.group(1)
                        coords_match = re.search(r'center=([-0-9.]+)%2C([-0-9.]+)', img_url)
                        if coords_match:
                            latitude = float(coords_match.group(1))
                            longitude = float(coords_match.group(2))
                            address = reverse_geocode(latitude, longitude)

            except Exception as e:
                logging.error(f"Error fetching detail for listing {link}: {e}")
            finally:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])

            for chat_id, (msg_id, user_deal_message, fixed_lat, fixed_lon) in partial_sent_map.items():
                distance = calculate_distance(fixed_lat, fixed_lon, latitude, longitude)

                updated_text = (
                    f"{user_deal_message}{address} ({distance}) For {price}\n"
                    f"Link: https://www.facebook.com{link}"
                )
                await edit_message(chat_id, msg_id, updated_text)

        first_run[pair] = False

    except Exception as e:
        logging.error(f"Error checking pair {pair}: {e}")
    finally:
        driver.quit()

async def monitor_all_pairs_together(users, bot):
    pairs, user_pair_map = generate_pairs_and_log(users)
    seen_listings = set()
    first_run = {pair: True for pair in pairs}

    while True:
        tasks = [
            check_marketplace_pair(pair, user_pair_map, seen_listings, first_run)
            for pair in pairs
        ]
        await asyncio.gather(*tasks)

        delay = random.uniform(15, 25)
        logging.info(f"Round done. Waiting for {delay:.2f} seconds.")
        await asyncio.sleep(delay)
