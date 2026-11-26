#!/usr/bin/env python3
"""
Ecom Office Pipeline Bot
========================
Sits in the Telegram group alongside Hermes.
- Watches for Hermes brand reports (messages containing store URLs and ad counts)
- Watches for your "approved" or "denied" replies
- Saves all decisions to ~/Claude/pipeline.json
- Claude Desktop reads that file through mcp-serve or directly

Run: python3 pipeline_bot.py
Stop: Ctrl+C
"""

import json
import os
import re
import sys
import time
import signal
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

# === CONFIG ===
BOT_TOKEN = "9079897779:AAGwvpoDxi-FMQbNNUh9EpJ_S3b82uMvE0U"
PIPELINE_FILE = os.path.expanduser("~/Claude/pipeline.json")
POLL_INTERVAL = 2  # seconds between checking for new messages

# === PIPELINE FILE ===
def load_pipeline():
    if os.path.exists(PIPELINE_FILE):
        with open(PIPELINE_FILE) as f:
            return json.load(f)
    return {"brands": [], "last_updated": None}

def save_pipeline(data):
    data["last_updated"] = datetime.now().isoformat()
    os.makedirs(os.path.dirname(PIPELINE_FILE), exist_ok=True)
    with open(PIPELINE_FILE, "w") as f:
        json.dump(data, f, indent=2)

# === TELEGRAM API ===
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

def api_call(method, params=None):
    url = f"{API_BASE}/{method}"
    if params:
        data = json.dumps(params).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    else:
        req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  API error: {e}")
        return None

def send_message(chat_id, text, reply_to=None):
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_to:
        params["reply_to_message_id"] = reply_to
    return api_call("sendMessage", params)

# === PARSE HERMES OUTPUT ===
def parse_hermes_message(text):
    """Try to extract brand info from a Hermes report message."""
    brand = {}

    # Look for store URLs
    urls = re.findall(r'https?://[^\s,<>]+', text)
    store_urls = [u for u in urls if 'facebook.com' not in u and 'meta.com' not in u]
    meta_urls = [u for u in urls if 'facebook.com/ads/library' in u or 'meta.com' in u]

    if store_urls:
        brand["store_url"] = store_urls[0].rstrip(')')
        try:
            from urllib.parse import urlparse
            brand["name"] = urlparse(brand["store_url"]).hostname.replace("www.", "").replace("get.", "")
        except:
            brand["name"] = brand["store_url"]

    if meta_urls:
        brand["meta_link"] = meta_urls[0].rstrip(')')

    # Look for ad count
    count_match = re.search(r'(\d+)\s*(?:ads?|distinct|total)', text, re.IGNORECASE)
    if count_match:
        brand["ad_count"] = int(count_match.group(1))

    # Look for dates
    date_match = re.search(r'(?:earliest|first|started?|launched?)[:\s]*(?:on\s+)?(\w+\s+\d+(?:,?\s*\d{4})?)', text, re.IGNORECASE)
    if date_match:
        brand["earliest_ad"] = date_match.group(1)

    # Look for brand/company name
    name_match = re.search(r'(?:brand|company|store)[:\s]*([A-Z][A-Za-z0-9\s&\'-]+)', text)
    if name_match and "name" not in brand:
        brand["name"] = name_match.group(1).strip()

    return brand if ("store_url" in brand or "name" in brand) else None

def is_approval_message(text):
    """Check if message is an approval/denial."""
    text_lower = text.strip().lower()
    if text_lower in ["approved", "approve", "yes", "go", "ship it", "lets go", "let's go"]:
        return "approved"
    if text_lower in ["denied", "deny", "no", "pass", "skip", "nah"]:
        return "denied"
    if text_lower.startswith("approved"):
        return "approved"
    if text_lower.startswith("denied") or text_lower.startswith("deny"):
        return "denied"
    return None

# === MAIN BOT LOOP ===
def main():
    print("=" * 50)
    print("  ECOM OFFICE PIPELINE BOT")
    print("=" * 50)
    print(f"  Pipeline file: {PIPELINE_FILE}")
    print(f"  Polling every {POLL_INTERVAL}s")
    print(f"  Watching for Hermes brands + your approvals")
    print("=" * 50)

    # Verify bot token
    me = api_call("getMe")
    if not me or not me.get("ok"):
        print("ERROR: Invalid bot token!")
        sys.exit(1)
    print(f"  Bot: @{me['result']['username']}")
    print("  Status: ONLINE")
    print()

    offset = 0
    pending_brands = {}  # message_id -> brand data (brands waiting for approval)

    # Load existing pipeline
    pipeline = load_pipeline()
    print(f"  Loaded {len(pipeline['brands'])} existing brands from pipeline")
    print()

    def handle_shutdown(sig, frame):
        print("\n  Shutting down bot...")
        save_pipeline(pipeline)
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    while True:
        try:
            result = api_call("getUpdates", {"offset": offset, "timeout": 20})

            if not result or not result.get("ok"):
                time.sleep(POLL_INTERVAL)
                continue

            for update in result["result"]:
                offset = update["update_id"] + 1
                msg = update.get("message")
                if not msg or not msg.get("text"):
                    continue

                text = msg["text"]
                chat_id = msg["chat"]["id"]
                msg_id = msg["message_id"]
                sender = msg.get("from", {}).get("first_name", "Unknown")
                is_bot = msg.get("from", {}).get("is_bot", False)
                reply_to = msg.get("reply_to_message", {}).get("message_id")

                # Skip our own messages
                if msg.get("from", {}).get("id") == me["result"]["id"]:
                    continue

                # Check if it's a Hermes message (from a bot, contains URLs/ad data)
                if is_bot:
                    brand = parse_hermes_message(text)
                    if brand:
                        brand["status"] = "pending"
                        brand["hermes_message_id"] = msg_id
                        brand["found_at"] = datetime.now().isoformat()
                        brand["raw_message"] = text[:500]

                        pending_brands[msg_id] = brand
                        pipeline["brands"].append(brand)
                        save_pipeline(pipeline)

                        name = brand.get("name", "Unknown")
                        count = brand.get("ad_count", "?")
                        url = brand.get("store_url", "")

                        reply_text = (
                            f"<b>NEW BRAND FOUND</b>\n\n"
                            f"Brand: <b>{name}</b>\n"
                            f"Ads: {count}\n"
                            f"Store: {url}\n\n"
                            f"Reply <b>approved</b> or <b>denied</b> to this message."
                        )
                        send_message(chat_id, reply_text, reply_to=msg_id)
                        print(f"  [BRAND] {name} — {count} ads — {url}")

                # Check if it's an approval/denial (reply to a brand message)
                elif not is_bot:
                    decision = is_approval_message(text)

                    if decision:
                        # Find which brand this approval is for
                        target_brand = None

                        # If replying to our bot's brand card
                        if reply_to:
                            for brand in pipeline["brands"]:
                                if brand.get("hermes_message_id") == reply_to or brand.get("bot_card_id") == reply_to:
                                    target_brand = brand
                                    break

                        # If not replying to anything, approve the most recent pending brand
                        if not target_brand:
                            for brand in reversed(pipeline["brands"]):
                                if brand.get("status") == "pending":
                                    target_brand = brand
                                    break

                        if target_brand:
                            target_brand["status"] = decision
                            target_brand["decided_at"] = datetime.now().isoformat()
                            target_brand["decided_by"] = sender
                            save_pipeline(pipeline)

                            emoji = "✅" if decision == "approved" else "❌"
                            name = target_brand.get("name", "Unknown")

                            if decision == "approved":
                                reply_text = (
                                    f"{emoji} <b>{name} APPROVED</b>\n\n"
                                    f"Pipeline started. Claude will:\n"
                                    f"1. Copy the store into Shopify\n"
                                    f"2. Pull top 3 native ads\n"
                                    f"3. Write 5 hook variations each\n"
                                    f"4. Generate campaign images\n"
                                    f"5. Package everything in Google Drive"
                                )
                            else:
                                reply_text = f"{emoji} <b>{name} DENIED</b> — moving on."

                            send_message(chat_id, reply_text, reply_to=msg_id)
                            print(f"  [{decision.upper()}] {name} by {sender}")
                        else:
                            send_message(chat_id, "No pending brand to approve. Wait for Hermes to find one.", reply_to=msg_id)

                    # Handle /status command
                    elif text.strip().lower() in ["/status", "status"]:
                        pending = [b for b in pipeline["brands"] if b["status"] == "pending"]
                        approved = [b for b in pipeline["brands"] if b["status"] == "approved"]
                        denied = [b for b in pipeline["brands"] if b["status"] == "denied"]

                        status_text = (
                            f"<b>PIPELINE STATUS</b>\n\n"
                            f"Pending: {len(pending)}\n"
                            f"Approved: {len(approved)}\n"
                            f"Denied: {len(denied)}\n"
                        )

                        if pending:
                            status_text += "\n<b>Waiting for decision:</b>\n"
                            for b in pending[-3:]:
                                status_text += f"  • {b.get('name', '?')} — {b.get('ad_count', '?')} ads\n"

                        send_message(chat_id, status_text, reply_to=msg_id)

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            handle_shutdown(None, None)
        except Exception as e:
            print(f"  Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
