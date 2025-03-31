import requests
import json
import re

def find_location_recursive(data, depth=0, max_depth=10, path="", verbose=False):
    """
    Recursively search for a 'location' key with latitude and longitude
    in a nested dictionary structure.
    
    Args:
        data: Dictionary to search in
        depth: Current recursion depth
        max_depth: Maximum recursion depth to prevent infinite loops
        path: Current path in the nested structure (for debugging)
        verbose: Whether to print detailed debug information
        
    Returns:
        Dict containing latitude and longitude, or None if not found
    """
    # Prevent infinite recursion
    if depth > max_depth:
        return None
        
    # Base case: if not a dictionary, return None
    if not isinstance(data, dict):
        return None
        
    # Check if this dictionary has a 'location' key
    if 'location' in data and isinstance(data['location'], dict):
        location = data['location']
        if verbose:
            print(f"Found 'location' at path: {path}.location")
            print(f"Location keys: {list(location.keys())}")
        
        if 'latitude' in location and 'longitude' in location:
            if verbose:
                print(f"Found coordinates at path: {path}.location")
            return location
    
    # Check for latitude and longitude directly in this dict
    if 'latitude' in data and 'longitude' in data:
        if verbose:
            print(f"Found direct coordinates at path: {path}")
        return data
    
    # Recursive case: check all dictionary values
    for key, value in data.items():
        if isinstance(value, dict):
            new_path = f"{path}.{key}" if path else key
            result = find_location_recursive(value, depth + 1, max_depth, new_path, verbose)
            if result:
                return result
        # Also check inside lists
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    new_path = f"{path}.{key}[{i}]" if path else f"{key}[{i}]"
                    result = find_location_recursive(item, depth + 1, max_depth, new_path, verbose)
                    if result:
                        return result
                
    return None

def extract_coordinates(listing_id):
    """
    Extract latitude and longitude coordinates from a Facebook Marketplace listing
    
    Args:
        listing_id (str): The Facebook Marketplace listing ID
        
    Returns:
        tuple: (latitude, longitude) coordinates or None if not found
    """
    # URL for the bulk route definitions API
    url = "https://www.facebook.com/ajax/bulk-route-definitions/"
    
    # Headers to mimic a browser request
    headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://www.facebook.com",
        "referer": f"https://www.facebook.com/marketplace/item/{listing_id}/",
        "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
    }
    
    # Some cookies are needed for the request to work properly
    cookies = {
        "datr": "92jTZ8ae6PgSA87nd9Lfz_9m",  # Example value
        "sb": "92jTZ7AxrwFYLbISRttc-HSD",    # Example value
        "dpr": "1.25",
        "wd": "800x730"
    }
    
    # Try both route formats to see which one works
    # Format 1: with referral parameters
    route_with_ref = f"/marketplace/item/{listing_id}/?ref=search&referral_code=null&referral_story_type=post"
    # Format 2: simplified without parameters
    route_simple = f"/marketplace/item/{listing_id}/"
    
    # Form data for the request
    data = {
        "route_urls[0]": route_simple,  # Try the simpler route format first
        "routing_namespace": "fb_comet",
        "__aaid": "0",
        "__user": "0",
        "__a": "1",
        "__req": "2",
        "__hs": "20178.HYP:comet_loggedout_pkg.2.1...0",
        "dpr": "1",
        "__ccg": "EXCELLENT",
        "__rev": "1021404933",  # This might need to be updated periodically
        "__s": "yzjdwr:wbn65g:c5sxht",
        "__hsi": "7487801154620878429",
        "__dyn": "7xe6E5q5U5ObwKBwno6u5U4e0C8dEc8co38w4BwUx609vCwjE1EE2Cw8G1Dw5Zx62G3i0Bo2ygao1aU2swlo6qU2exi4UaEW1GwkEbo4y5o2exu16w2oEGdw46wbS1LwTwNwLweq1Iwqo4q1-w8eEb8uwm85K0ke",
        "__csr": "hRgJRlN4GLLlqkJdi7haF5VqyVbm4dBmjSaCABRUG9Quui9G2qdy-bzooxK48cobEf89EmiwMwHHACUC3e2K9wUzE8poeFo025Owq8rwKw37E3Rw047aw0L4a0bnwq60eEw5ow5zw0yvG5Q7y05Xw9EM0cYo0vtyo0fiU4a01v9o7V015i0mcw6C",
        "__comet_req": "15",
        "lsd": "AVotB1KQbug",
        "jazoest": "2967",
        "__spin_r": "1021404933",
        "__spin_b": "trunk",
        "__spin_t": "1743389562"
    }
    
    try:
        # Send the POST request
        response = requests.post(url, headers=headers, cookies=cookies, data=data)
        
        # Check if the request was successful
        if response.status_code == 200:
            # Print a small sample of the response for debugging
            print(f"Response preview: {response.text[:100]}...")
            
            # The response typically starts with "for (;;);" followed by JSON
            json_text = re.sub(r'^for \(;;\);', '', response.text)
            
            # Try to parse the JSON
            try:
                json_data = json.loads(json_text)
            except json.JSONDecodeError as e:
                print(f"Failed to parse JSON: {str(e)}")
                print(f"First 200 characters of response after removing 'for(;;);': {json_text[:200]}")
                return None
            
            # Extract the coordinates from the JSON structure
            try:
                # First, check if we can find the route key - try both formats
                route_simple = f"/marketplace/item/{listing_id}/"
                route_with_ref = f"/marketplace/item/{listing_id}/?ref=search&referral_code=null&referral_story_type=post"
                
                # Try to find a matching route key in the response
                route_key = None
                if route_simple in json_data["payload"]["payloads"]:
                    route_key = route_simple
                elif route_with_ref in json_data["payload"]["payloads"]:
                    route_key = route_with_ref
                else:
                    # Look for any key that contains our listing ID
                    for key in json_data["payload"]["payloads"].keys():
                        if listing_id in key:
                            route_key = key
                            break
                
                if not route_key:
                    print(f"Error: Could not find any route key for listing ID: {listing_id}")
                    print("Available keys in response:", list(json_data["payload"]["payloads"].keys()))
                    return None
                if "payload" not in json_data:
                    print("Error: Response doesn't contain 'payload' field")
                    print("Response preview:", json_data[:200] if isinstance(json_data, str) else str(json_data)[:200])
                    return None
                
                if "payloads" not in json_data["payload"]:
                    print("Error: Response doesn't contain 'payloads' field")
                    return None
                
                if route_key not in json_data["payload"]["payloads"]:
                    print(f"Error: Could not find route key in response: {route_key}")
                    # Look for any keys in the payloads field
                    if json_data["payload"]["payloads"]:
                        print("Available keys in response:", list(json_data["payload"]["payloads"].keys()))
                    return None
                
                # Check if there's an error in the response
                if "error" in json_data["payload"]["payloads"][route_key] and json_data["payload"]["payloads"][route_key]["error"] == True:
                    print("Facebook returned an error response")
                    if "errorSummary" in json_data["payload"]["payloads"][route_key]:
                        print("Error summary:", json_data["payload"]["payloads"][route_key]["errorSummary"])
                    return None
                
                # Try to extract the rootView
                if "result" not in json_data["payload"]["payloads"][route_key]:
                    print("Error: No 'result' field in the response")
                    return None
                
                result = json_data["payload"]["payloads"][route_key]["result"]
                
                # Debug the result structure
                print("Available fields in result:", list(result.keys()))
                
                # Based on the provided example JSON structure, check this specific path
                if "exports" in result:
                    exports = result["exports"]
                    print("Available fields in exports:", list(exports.keys()))
                    
                    # Check the rootView.props.location path - this is the correct path based on the example
                    if "rootView" in exports and isinstance(exports["rootView"], dict):
                        root_view = exports["rootView"]
                        print("rootView structure:", list(root_view.keys()) if isinstance(root_view, dict) else "Not a dictionary")
                        
                        if "props" in root_view and isinstance(root_view["props"], dict):
                            props = root_view["props"]
                            print("Props structure:", list(props.keys()) if isinstance(props, dict) else "Not a dictionary")
                            
                            if "location" in props and isinstance(props["location"], dict):
                                location = props["location"]
                                print("Found location in rootView.props:", location)
                                
                                if "latitude" in location and "longitude" in location:
                                    print("Found coordinates in rootView.props.location")
                                    return location["latitude"], location["longitude"]
                    
                    # Also check the hostableView.props.location path as a backup
                    if "hostableView" in exports and isinstance(exports["hostableView"], dict):
                        hostable_view = exports["hostableView"]
                        print("hostableView structure:", list(hostable_view.keys()) if isinstance(hostable_view, dict) else "Not a dictionary")
                        
                        if "props" in hostable_view and isinstance(hostable_view["props"], dict):
                            props = hostable_view["props"]
                            print("hostableView props structure:", list(props.keys()) if isinstance(props, dict) else "Not a dictionary")
                            
                            if "location" in props and isinstance(props["location"], dict):
                                location = props["location"]
                                print("Found location in hostableView.props:", location)
                                
                                if "latitude" in location and "longitude" in location:
                                    print("Found coordinates in hostableView.props.location")
                                    return location["latitude"], location["longitude"]
                    
                # Try additional known fields
                if not location_data:
                    # Sometimes Facebook uses a different structure
                    # Try to find coordinates in allResources or resource
                    if "rootView" in exports and isinstance(exports["rootView"], dict):
                        if "allResources" in exports["rootView"]:
                            print("Checking allResources in rootView...")
                            # allResources is typically a list
                            for i, resource in enumerate(exports["rootView"]["allResources"]):
                                if isinstance(resource, dict):
                                    location = find_location_recursive(resource, verbose=True)
                                    if location:
                                        return location["latitude"], location["longitude"]
                        
                        if "resource" in exports["rootView"]:
                            print("Checking resource in rootView...")
                            if isinstance(exports["rootView"]["resource"], dict):
                                location = find_location_recursive(exports["rootView"]["resource"], verbose=True)
                                if location:
                                    return location["latitude"], location["longitude"]
                    
                    # Try checking hostableView with same approach
                    if "hostableView" in exports and isinstance(exports["hostableView"], dict):
                        if "allResources" in exports["hostableView"]:
                            print("Checking allResources in hostableView...")
                            for i, resource in enumerate(exports["hostableView"]["allResources"]):
                                if isinstance(resource, dict):
                                    location = find_location_recursive(resource, verbose=True)
                                    if location:
                                        return location["latitude"], location["longitude"]
                        
                        if "resource" in exports["hostableView"]:
                            print("Checking resource in hostableView...")
                            if isinstance(exports["hostableView"]["resource"], dict):
                                location = find_location_recursive(exports["hostableView"]["resource"], verbose=True)
                                if location:
                                    return location["latitude"], location["longitude"]
                
                # If we haven't returned yet, try the original structure
                if "rootView" not in result:
                    print("Error: Could not find location information in the response")
                    return None
                
                root_view = result["rootView"]
                
                # Check if props exist
                if "props" not in root_view:
                    print("Error: No 'props' field in rootView")
                    print("Available fields in rootView:", list(root_view.keys()))
                    return None
                
                props = root_view["props"]
                
                # Check if location exists
                if "location" not in props:
                    print("Error: No 'location' field in props")
                    print("Available fields in props:", list(props.keys()))
                    return None
                
                location = props["location"]
                
                # Check if latitude and longitude exist
                if "latitude" not in location or "longitude" not in location:
                    print("Error: Missing latitude or longitude in location data")
                    print("Available fields in location:", list(location.keys()))
                    return None
                
                latitude = location["latitude"]
                longitude = location["longitude"]
                
                return latitude, longitude
            except (KeyError, TypeError) as e:
                print(f"Could not find coordinates in the response data: {str(e)}")
                return None
        else:
            print(f"Request failed with status code: {response.status_code}")
            return None
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        return None

def main():
    print("Facebook Marketplace Coordinates Extractor")
    print("=========================================")
    
    while True:
        listing_id = input("\nEnter the Facebook Marketplace listing ID (or 'q' to quit): ")
        
        if listing_id.lower() == 'q':
            break
        
        # Check if the input is a URL
        if "facebook.com" in listing_id or "fb.com" in listing_id:
            # Try to extract the ID from the URL using a regex pattern
            import re
            match = re.search(r'/item/(\d+)', listing_id)
            if match:
                listing_id = match.group(1)
                print(f"Extracted listing ID from URL: {listing_id}")
            else:
                print("Could not extract a valid listing ID from the URL.")
                continue
        else:
            # Clean the listing ID (remove any non-numeric characters)
            listing_id = ''.join(filter(str.isdigit, listing_id))
            
            if not listing_id:
                print("Invalid listing ID. Please enter a numeric ID.")
                continue
            
        print(f"\nFetching coordinates for listing ID: {listing_id}")
        
        # Add a try-except block to catch any unexpected errors
        try:
            coordinates = extract_coordinates(listing_id)
            
            if coordinates:
                latitude, longitude = coordinates
                print(f"\nFound coordinates:")
                print(f"Latitude: {latitude}")
                print(f"Longitude: {longitude}")
                print(f"\nGoogle Maps URL: https://www.google.com/maps?q={latitude},{longitude}")
            else:
                print("\nCould not extract coordinates. Make sure the listing ID is valid.")
                print("\nTroubleshooting tips:")
                print("1. Make sure you have an internet connection")
                print("2. Try using a different listing ID")
                print("3. The structure of Facebook's response might have changed")
                print("4. You might need updated cookies - check the cookies in the script")
        except Exception as e:
            print(f"\nAn unexpected error occurred: {str(e)}")

if __name__ == "__main__":
    main()
