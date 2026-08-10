import os
import time
import threading
import requests
from dotenv import load_dotenv
from pathlib import Path

# load .env from this folder (B-WholeSystem/.env), same as main.py
HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OWNER_CHAT_ID = os.getenv("TELEGRAM_OWNER_CHAT_ID", "")
CAREGIVER_CHAT_ID = os.getenv("TELEGRAM_CAREGIVER_CHAT_ID", "")
SCDF_CHAT_ID = os.getenv("TELEGRAM_SCDF_CHAT_ID", "")

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

# REQ-07: everyone who is alerted
ALERT_RECIPIENTS = {
    "owner": OWNER_CHAT_ID,
    "caregiver": CAREGIVER_CHAT_ID,
    "scdf": SCDF_CHAT_ID,
}


#emergency notif
def send_message(chat_id: str, text: str, timeout: int = 5) -> bool:
    url = f"{API_BASE}/sendMessage"
    try:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "text": text},
            timeout=timeout,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"[telegram_bot] Failed to message {chat_id}: {e}")
        return False


def send_emergency_alert(message: str = "Fire detected!") -> None:
    for role, chat_id in ALERT_RECIPIENTS.items(): #send everyone 
        success = send_message(chat_id, message)
        status = "sent" if success else "FAILED"
        print(f"[telegram_bot] Alert to {role} ({chat_id}): {status}")


#995 manual command 
def poll_for_commands(on_995_received, poll_interval: int = 2) -> None:
    offset = None
    url = f"{API_BASE}/getUpdates"

    while True:
        params = {"timeout": poll_interval}
        if offset is not None:
            params["offset"] = offset

        try:
            resp = requests.get(url, params=params, timeout=poll_interval + 5)
            resp.raise_for_status()
            updates = resp.json().get("result", [])
        except requests.RequestException as e:
            print(f"[telegram_bot] Poll error: {e}")
            time.sleep(poll_interval)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message", {})
            text = message.get("text", "").strip()

            if text == "995":
                chat_id = str(message.get("chat", {}).get("id"))
                print(f"[telegram_bot] '995' received from chat {chat_id}")
                on_995_received()


def start_command_listener(on_995_received) -> threading.Thread:
    t = threading.Thread(
        target=poll_for_commands,
        args=(on_995_received,),
        daemon=True,
    )
    t.start()
    return t