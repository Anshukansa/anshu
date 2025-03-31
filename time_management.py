import pytz
from datetime import datetime, time

# Define timezone mappings for supported locations
LOCATION_TIMEZONES = {
    "melbourne": pytz.timezone("Australia/Melbourne"),
    "brisbane": pytz.timezone("Australia/Brisbane"),
    # Add more locations as needed
}

# Default timezone for locations not explicitly mapped
DEFAULT_TIMEZONE = pytz.timezone("UTC")

def get_location_timezone(location):
    """Get the timezone for a specific location."""
    location_key = location.lower()
    return LOCATION_TIMEZONES.get(location_key, DEFAULT_TIMEZONE)

def is_monitoring_active(location):
    """
    Check if monitoring should be active for the given location based on its local time.
    Returns:
        bool: True if monitoring should be active, False if it should be paused.
        str: Reason for the status (for logging)
    """
    # Get timezone for location
    tz = get_location_timezone(location)
    
    # Get current time in location's timezone
    now = datetime.now(pytz.UTC).astimezone(tz)
    current_time = now.time()
    
    # Define monitoring inactive period (10:00 PM to 6:30 AM)
    start_inactive = time(22, 0)  # 10:00 PM
    end_inactive = time(6, 30)    # 6:30 AM
    
    # Check if current time is within inactive period
    if start_inactive <= current_time or current_time <= end_inactive:
        next_active_time = now.replace(
            hour=end_inactive.hour, 
            minute=end_inactive.minute, 
            second=0
        )
        if current_time > end_inactive:
            # If it's after midnight, next active time is tomorrow
            next_active_time = next_active_time.replace(day=now.day + 1)
            
        reason = f"Nighttime hours in {location} (local time: {current_time.strftime('%H:%M')}). Resuming at {end_inactive.strftime('%H:%M')}"
        return False, reason, next_active_time
    
    # Calculate when monitoring will stop next
    next_inactive_time = now.replace(
        hour=start_inactive.hour,
        minute=start_inactive.minute,
        second=0
    )
    
    return True, f"Daytime hours in {location} (local time: {current_time.strftime('%H:%M')})", next_inactive_time

def get_monitoring_schedule(location):
    """
    Get the current monitoring schedule for a location.
    
    Returns:
        dict: Schedule information including active status, local time, and next status change
    """
    tz = get_location_timezone(location)
    now = datetime.now(pytz.UTC).astimezone(tz)
    current_time = now.time()
    
    # Define monitoring inactive period
    start_inactive = time(22, 0)  # 10:00 PM
    end_inactive = time(6, 30)    # 6:30 AM
    
    is_active = not (start_inactive <= current_time or current_time <= end_inactive)
    
    if is_active:
        # If active, calculate when it will become inactive
        next_change = now.replace(hour=start_inactive.hour, minute=start_inactive.minute, second=0)
        next_status = "inactive"
    else:
        # If inactive, calculate when it will become active
        next_change = now.replace(hour=end_inactive.hour, minute=end_inactive.minute, second=0)
        if current_time > end_inactive:
            # If it's after midnight, next active time is tomorrow
            next_change = next_change.replace(day=now.day + 1)
        next_status = "active"
    
    return {
        "location": location,
        "timezone": str(tz),
        "local_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "is_active": is_active,
        "next_change": next_change.strftime("%Y-%m-%d %H:%M:%S"),
        "next_status": next_status,
        "active_hours": f"{end_inactive.strftime('%H:%M')} - {start_inactive.strftime('%H:%M')}"
    }
