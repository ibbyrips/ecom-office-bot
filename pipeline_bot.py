#!/usr/bin/env python3
"""
Ecom Office Pipeline Bot v2 (Cloud Version)
Runs on Railway.app 24/7. Inline approve/deny buttons.
"""
import json, os, re, sys, time, signal, urllib.request, urllib.parse
from datetime import datetime

BOT_TOKEN = os.environ.get("BOT_TOKEN", "9079897779:AAGwvpoDxi-FMQbNNUh9EpJ_S3b82uMvE0U")
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
pipeline = {"brands": {}, "stats": {"found": 0, "approved": 0, "denied": 0}, "started": None}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

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
        log(f"API error: {e}")
        return None

def send_message(chat_id, text, reply_to=None, buttons=None):
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_to:
        params["reply_to_message_id"] = reply_to
    if buttons:
        params["reply_markup"] = {"inline_keyboard": buttons}
    return api_call("sendMessage", params)

def edit_message(chat_id, message_id, text, buttons=None):
    params = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if buttons:
        params["reply_markup"] = {"inline_keyboard": buttons}
    else:
        params["reply_markup"] = {"inline_keyboard": []}
    return api_call("editMessageText", params)

def answer_callback(callback_id, text=""):
    return api_call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

def parse_hermes_brands(text):
    brands = []
    pattern = r'(\d+)\.\s*(\S+)\s*\n\s*[^\n]*Ad Library ID:\s*(\S+)\s*\n\s*[^\n]*Total Ads:\s*(\d+)\s*\n\s*[^\n]*First Ad Date:\s*(.+?)(?=\n\n|\n\d+\.|\nSkipped|$)'
    for m in re.finditer(pattern, text, re.MULTILINE | re.DOTALL):
        brands.append({"name": m.group(2).strip(), "ad_library_id": m.group(3).strip(), "total_ads": int(m.group(4)), "first_ad_date": m.group(5).strip()})
    if not brands:
        for line in text.split('\n'):
            dm = re.search(r'([a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?)', line)
            if dm and 'qualified' in text.lower():
                d = dm.group(1)
                if not any(s in d.lower() for s in ['facebook.com','meta.com','telegram.org']):
                    brands.append({"name": d, "total_ads": "?", "ad_library_id": "?", "first_ad_date": "?"})
    return brands

def is_qualified_message(text):
    t = text.lower()
    return "qualified brands" in t or ("qualified" in t and "ad library id" in t) or ("qualified" in t and "total ads" in t)

def make_brand_card(brand, brand_id, status="pending"):
    name = brand["name"]
    ads = brand.get("total_ads", "?")
    ad_id = brand.get("ad_library_id", "?")
    first_date = brand.get("first_ad_date", "?")
    if status == "pending": status_line = "\u23f3 <b>PENDING YOUR DECISION</b>"
    elif status == "approved": status_line = "\u2705 <b>APPROVED</b>"
    else: status_line = "\u274c <b>DENIED</b>"
    return (f"\U0001f50d <b>{name}</b>\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"\U0001f4ca Ads Running: <b>{ads}</b>\n\U0001f194 Library ID: <code>{ad_id}</code>\n"
            f"\U0001f4c5 First Ad: <b>{first_date}</b>\n\U0001f517 Store: {name}\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n{status_line}")

def make_buttons(brand_id):
    return [[{"text": "\u2705 Approve", "callback_data": f"approve:{brand_id}"}, {"text": "\u274c Deny", "callback_data": f"deny:{brand_id}"}],
            [{"text": "\U0001f517 View on Meta Ad Library", "callback_data": f"view:{brand_id}"}]]

def main():
    log("ECOM OFFICE PIPELINE BOT v2 — ONLINE")
    me = api_call("getMe")
    if not me or not me.get("ok"):
        log("ERROR: Invalid bot token!"); sys.exit(1)
    log(f"Bot: @{me['result']['username']}")
    offset = 0; my_id = me["result"]["id"]
    def handle_shutdown(sig, frame):
        log(f"Shutting down... {pipeline['stats']}"); sys.exit(0)
    signal.signal(signal.SIGINT, handle_shutdown); signal.signal(signal.SIGTERM, handle_shutdown)
    while True:
        try:
            result = api_call("getUpdates", {"offset": offset, "timeout": 20, "allowed_updates": ["message", "callback_query"]})
            if not result or not result.get("ok"): time.sleep(2); continue
            for update in result["result"]:
                offset = update["update_id"] + 1
                callback = update.get("callback_query")
                if callback:
                    cb_id = callback["id"]; cb_data = callback.get("data", ""); cb_msg = callback.get("message", {})
                    chat_id = cb_msg.get("chat", {}).get("id"); message_id = cb_msg.get("message_id")
                    user_name = callback.get("from", {}).get("first_name", "Unknown")
                    parts = cb_data.split(":")
                    if len(parts) == 2:
                        action, brand_id = parts
                        if brand_id in pipeline["brands"]:
                            brand = pipeline["brands"][brand_id]
                            if action == "approve":
                                brand["status"] = "approved"; brand["decided_by"] = user_name; brand["decided_at"] = datetime.now().isoformat()
                                pipeline["stats"]["approved"] += 1
                                card = make_brand_card(brand, brand_id, "approved") + "\n\n\U0001f680 <b>Pipeline triggered</b>\n1\ufe0f\u20e3 Scrape store copy\n2\ufe0f\u20e3 Write 15 native ads\n3\ufe0f\u20e3 Generate campaign images\n4\ufe0f\u20e3 Package in Google Drive"
                                edit_message(chat_id, message_id, card); answer_callback(cb_id, f"\u2705 {brand['name']} approved!")
                                log(f"APPROVED: {brand['name']} by {user_name}")
                            elif action == "deny":
                                brand["status"] = "denied"; brand["decided_by"] = user_name; brand["decided_at"] = datetime.now().isoformat()
                                pipeline["stats"]["denied"] += 1
                                edit_message(chat_id, message_id, make_brand_card(brand, brand_id, "denied")); answer_callback(cb_id, f"\u274c {brand['name']} denied")
                                log(f"DENIED: {brand['name']} by {user_name}")
                            elif action == "view":
                                url = f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US&q={urllib.parse.quote(brand['name'])}"
                                answer_callback(cb_id); send_message(chat_id, f'\U0001f517 <a href="{url}">View {brand["name"]} on Meta Ad Library</a>', reply_to=message_id)
                        else: answer_callback(cb_id, "\u26a0\ufe0f Brand expired (bot restarted)")
                    continue
                msg = update.get("message")
                if not msg or not msg.get("text"): continue
                text = msg["text"]; chat_id = msg["chat"]["id"]; msg_id = msg["message_id"]
                sender = msg.get("from", {}).get("first_name", "Unknown"); is_bot = msg.get("from", {}).get("is_bot", False)
                sender_id = msg.get("from", {}).get("id", 0)
                if sender_id == my_id: continue
                if is_bot and is_qualified_message(text):
                    brands = parse_hermes_brands(text)
                    if brands:
                        for brand in brands:
                            bid = f"b{int(time.time()*1000)}{pipeline['stats']['found']}"
                            brand["status"] = "pending"; brand["found_at"] = datetime.now().isoformat()
                            pipeline["brands"][bid] = brand; pipeline["stats"]["found"] += 1
                            send_message(chat_id, make_brand_card(brand, bid, "pending"), reply_to=msg_id, buttons=make_buttons(bid))
                            log(f"FOUND: {brand['name']} \u2014 {brand.get('total_ads','?')} ads \u2014 buttons sent"); time.sleep(0.5)
                elif not is_bot:
                    tl = text.strip().lower()
                    if tl in ["/status", "status"]:
                        p = {k:v for k,v in pipeline["brands"].items() if v["status"]=="pending"}; s = pipeline["stats"]
                        st = f"\U0001f4ca <b>PIPELINE STATUS</b>\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\U0001f50d Found: {s['found']}\n\u2705 Approved: {s['approved']}\n\u274c Denied: {s['denied']}\n\u23f3 Pending: {len(p)}\n\U0001f916 Online since: {pipeline['started']}"
                        if p: st += "\n\n<b>Waiting:</b>\n" + "".join(f"  \u2022 {b['name']} \u2014 {b.get('total_ads','?')} ads\n" for b in list(p.values())[-5:])
                        send_message(chat_id, st, reply_to=msg_id)
                    elif tl in ["/help", "help"]:
                        send_message(chat_id, "\U0001f3e2 <b>ECOM OFFICE BOT v2</b>\n\nTap \u2705 Approve or \u274c Deny on any brand card.\n\nCommands: status, help", reply_to=msg_id)
                    elif tl in ["approved","approve","yes","go","ship it"]:
                        pend = [(k,v) for k,v in pipeline["brands"].items() if v["status"]=="pending"]
                        if pend:
                            bid, brand = pend[-1]; brand["status"]="approved"; brand["decided_by"]=sender; brand["decided_at"]=datetime.now().isoformat(); pipeline["stats"]["approved"]+=1
                            send_message(chat_id, f"\u2705 <b>{brand['name']} APPROVED</b>", reply_to=msg_id); log(f"APPROVED (text): {brand['name']}")
                        else: send_message(chat_id, "No pending brands.", reply_to=msg_id)
                    elif tl in ["denied","deny","no","pass","skip","next"]:
                        pend = [(k,v) for k,v in pipeline["brands"].items() if v["status"]=="pending"]
                        if pend:
                            bid, brand = pend[-1]; brand["status"]="denied"; brand["decided_by"]=sender; brand["decided_at"]=datetime.now().isoformat(); pipeline["stats"]["denied"]+=1
                            send_message(chat_id, f"\u274c <b>{brand['name']} DENIED</b>", reply_to=msg_id); log(f"DENIED (text): {brand['name']}")
                        else: send_message(chat_id, "No pending brands.", reply_to=msg_id)
            time.sleep(1)
        except KeyboardInterrupt: handle_shutdown(None, None)
        except Exception as e: log(f"Error: {e}"); time.sleep(5)

if __name__ == "__main__":
    pipeline["started"] = datetime.now().strftime("%Y-%m-%d %H:%M CST"); main()
