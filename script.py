import os
import json
import requests
from datetime import datetime
from urllib.parse import urlparse
import re

# --- Constants ---
DATA_FILE = "data.json"
URLS_FILE = "urls.txt"
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")  # GitHub secret

# --- Helper Functions ---

def load_urls_by_person():
    """
    Reads the urls.txt and splits them into 3 sections (Ben, Alice, Charlie).
    Sections are separated by comments starting with '#'.
    Returns a dict with person's name as key and list of URLs as value.
    """
    urls = {}
    current_person = None
    with open(URLS_FILE, "r") as file:
        for line in file:
            line = line.strip()
            if line.startswith("#"):
                current_person = line[1:].strip()
                urls[current_person] = []
            elif line and current_person:
                urls[current_person].append(line)
    return urls


def extract_product_id(url):
    """
    Extracts the numeric product ID from a TCGPlayer product URL.
    Example: https://www.tcgplayer.com/product/509980/... -> 509980
    """
    match = re.search(r"/product/(\d+)/", url)
    return match.group(1) if match else None


def fetch_price(product_id):
    """
    Fetches the foil marketPrice using the public mpapi endpoint.
    Only returns the Foil marketPrice (as per project requirements).
    """
    endpoint = f"https://mpapi.tcgplayer.com/v2/product/{product_id}/pricepoints"
    try:
        response = requests.get(endpoint, timeout=10)
        response.raise_for_status()
        data = response.json()

        for price_entry in data:
            if price_entry.get("printingType") == "Foil":
                return price_entry.get("marketPrice")
    except Exception as e:
        print(f"❌ Error fetching price for product ID {product_id}: {e}")
    return None


def load_previous_data():
    """
    Loads the saved price data from the previous run.
    Returns an empty dict if file does not exist or is corrupted.
    """
    if not os.path.exists(DATA_FILE):
        return {}

    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_current_data(data):
    """
    Saves the current price data to data.json.
    """
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def format_price_change(old, new):
    """
    Formats the price difference as a string with arrow and sign.
    """
    if old is None:
        return f"🆕 ${new:.2f}"
    diff = new - old
    arrow = "🔺" if diff > 0 else "🔻" if diff < 0 else "➡️"
    return f"{arrow} ${new:.2f} ({diff:+.2f})"


def send_to_discord(message):
    """
    Sends the final price update message to the Discord webhook.
    Webhook URL is stored in GitHub secrets.
    """
    if not DISCORD_WEBHOOK_URL:
        print("❌ Webhook URL not found in environment variables.")
        return

    payload = {
        "username": "Pokémon Price Tracker",
        "content": message
    }

    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"❌ Failed to send message to Discord: {e}")


# --- Main Tracker Logic ---

def main():
    previous_data = load_previous_data()
    urls_by_person = load_urls_by_person()
    current_data = {}
    summary = f"📊 **Pokémon Price Tracker** ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n"

    for person, urls in urls_by_person.items():
        summary += f"\n__**{person}**__\n"
        for url in urls:
            product_id = extract_product_id(url)
            if not product_id:
                summary += f"❌ Could not extract product ID from URL: {url}\n"
                continue

            new_price = fetch_price(product_id)
            if new_price is None:
                summary += f"❌ No price found for product {product_id}\n"
                continue

            old_price = previous_data.get(product_id)
            change = format_price_change(old_price, new_price)
            summary += f"[Product {product_id}] {change}\n"
            current_data[product_id] = new_price

    # Save latest prices for next run
    save_current_data(current_data)

    # Send to Discord
    send_to_discord(summary)


if __name__ == "__main__":
    main()
