"""
Smart Fire Alert System — Whole System (full SRS implementation).

Implements the complete state machine from the SRS:

    Sleep ──(slide switch right)──> Awake
    Awake ──(auto: temp>=60C OR LDR smoke)──> Emergency
    Awake ──(Telegram "995")──> Emergency            (manual)
    Emergency ──(temp<50C AND moisture, 5s)──> Awake (auto recovery)
    Emergency ──(keypad "123")──> Awake              (false alarm)

Threading model:
  - keypad_thread   : HAL keypad scanner -> key queue
  - monitor_thread  : polls temp + moisture + LDR continuously;
                      drives auto-detection (entry) and auto-recovery (exit)
  - telegram_thread : polls Telegram for the "995" manual command
  - main loop       : applies state transitions + outputs

Recovery + False Alarm logic is in fire_alarm.py (shared with folder A).
HAL modules are RPi.GPIO based (Raspberry Pi).

Networking uses the `requests` library directly (no relay needed — the Pi can
call HTTPS endpoints itself).
"""

import queue
import threading
import time

import os
from dotenv import load_dotenv

import requests

from hal import hal_led as led
from hal import hal_lcd as LCD
from hal import hal_adc as adc
from hal import hal_buzzer as buzzer
from hal import hal_keypad as keypad
from hal import hal_moisture_sensor as moisture_sensor
from hal import hal_input_switch as input_switch
from hal import hal_servo as servo
from hal import hal_temp_humidity_sensor as temp_humid_sensor

from fire_alarm import (
    DeactivationReason,
    FireAlarmController,
    State,
    RECOVERY_TEMP_C,
    RECOVERY_MIN_SECONDS,
    KEYPAD_DEACTIVATE_CODE,
    LCD_RECOVERED_LINE1,
    LCD_FALSE_ALARM_LINE1,
    LCD_FALSE_ALARM_LINE2,
)

# --------------------------------------------------------------------------
# Environment variables (from .env — see .env.example)
# --------------------------------------------------------------------------
load_dotenv()  # reads B-WholeSystem/.env when running from this folder

# SRS constants
FIRE_TEMP_C = 60.0            # SRS 2.3.3: auto-activation temp threshold
LDR_SMOKE_THRESHOLD = 300     # ADC value below this => smoke (calibrate!)
THINGSPEAK_UPLOAD_SECONDS = 15.0   # SRS 2.4.2
TELEGRAM_POLL_SECONDS = 1.0
SAMPLE_PERIOD_SECONDS = 1.0

# Telegram Bot API (direct from the Pi)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# ThingSpeak (direct from the Pi)
THINGSPEAK_API_KEY = os.getenv("THINGSPEAK_API_KEY", "")
THINGSPEAK_URL = "https://api.thingspeak.com/update"

# --------------------------------------------------------------------------
# Shared state
# --------------------------------------------------------------------------
state_lock = threading.Lock()
controller = None          # FireAlarmController (recovery + false alarm)

key_queue = queue.Queue()
last_thingspeak_upload = time.time()

# LCD instance (set in main()); module-level so deactivation can use it
lcd = None

# --------------------------------------------------------------------------
# HAL callback
# --------------------------------------------------------------------------
def key_pressed(key):
    key_queue.put(key)


def keypad_thread_fn():
    keypad.get_key()


# --------------------------------------------------------------------------
# Telegram helpers (direct HTTPS via requests)
# --------------------------------------------------------------------------
def send_telegram(message):
    """Send a Telegram message (SRS 2.3.3 REQ-07)."""
    print(f"[telegram] -> {message}")
    try:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=5,
        )
    except Exception as e:
        print(f"[telegram] send failed (offline?): {e}")


_telegram_offset = None   # last processed update_id (so '995' isn't re-triggered)


def get_telegram_manual_command():
    """
    Check the latest incoming Telegram message for the manual activation
    command "995" (SRS 2.3.3 REQ-04). Returns True if 995 was received.
    Advances the update offset so a message is only processed once.
    """
    global _telegram_offset
    try:
        url = f"{TELEGRAM_API}/getUpdates"
        if _telegram_offset is not None:
            url += f"?offset={_telegram_offset + 1}"
        r = requests.get(url, timeout=5)
        updates = r.json().get("result", [])
        for u in updates:
            update_id = u.get("update_id")
            if update_id is not None:
                _telegram_offset = max(_telegram_offset or 0, update_id)
            text = u.get("message", {}).get("text", "")
            if text == "995":
                return True
        return False
    except Exception:
        return False  # offline: skip


# --------------------------------------------------------------------------
# ThingSpeak helper (direct HTTPS via requests)
# --------------------------------------------------------------------------
def upload_thingspeak():
    """Upload sensor readings to ThingSpeak (SRS 2.4.2)."""
    temp, _h = temp_humid_sensor.read_temp_humidity()
    moisture = moisture_sensor.read_sensor()
    ldr = adc.get_adc_value(0)
    payload = {
        "api_key": THINGSPEAK_API_KEY,
        "field1": temp,
        "field2": ldr,
        "field3": 1 if moisture else 0,
    }
    print(f"[thingspeak] upload: {payload}")
    try:
        requests.post(THINGSPEAK_URL, data=payload, timeout=5)
    except Exception as e:
        print(f"[thingspeak] upload failed (offline?): {e}")


# --------------------------------------------------------------------------
# Emergency entry (SRS 2.3.3)
# --------------------------------------------------------------------------
def activate_emergency():
    """Emergency response actions on fire detection."""
    with state_lock:
        if controller.state is State.EMERGENCY:
            return
        controller.state = State.EMERGENCY

    buzzer.turn_on()
    led.set_output(1, 1)             # red LED on
    servo.set_servo_position(90)     # sprinkler sweeps
    lcd.lcd_clear()
    lcd.lcd_display_string("FIRE DETECTED!", 1)
    lcd.lcd_display_string("EVACUATE NOW", 2)
    send_telegram("Fire detected!")


# --------------------------------------------------------------------------
# Thread: sensor monitor (auto-detection + auto-recovery + ThingSpeak)
# --------------------------------------------------------------------------
def monitor_thread_fn():
    global last_thingspeak_upload
    while True:
        temp, _h = temp_humid_sensor.read_temp_humidity()
        ldr = adc.get_adc_value(0)
        moisture = moisture_sensor.read_sensor()

        with state_lock:
            st = controller.state

        if st is State.AWAKE:
            # auto-activation (SRS 2.3.3)
            if temp >= FIRE_TEMP_C or ldr < LDR_SMOKE_THRESHOLD:
                print(f"[monitor] fire detected! temp={temp} ldr={ldr}")
                activate_emergency()

        elif st is State.EMERGENCY:
            # auto-recovery (SRS 2.3.4) via shared controller
            if controller.monitor_once():
                deactivate_via_controller(DeactivationReason.RECOVERED)

        # ThingSpeak upload every 15 s (SRS 2.4.2)
        now = time.time()
        if now - last_thingspeak_upload >= THINGSPEAK_UPLOAD_SECONDS:
            upload_thingspeak()
            last_thingspeak_upload = now

        time.sleep(SAMPLE_PERIOD_SECONDS)


# --------------------------------------------------------------------------
# Thread: Telegram manual command ("995")
# --------------------------------------------------------------------------
def telegram_thread_fn():
    while True:
        if get_telegram_manual_command():
            print("[telegram] manual '995' -> emergency")
            activate_emergency()
        time.sleep(TELEGRAM_POLL_SECONDS)


# --------------------------------------------------------------------------
# Deactivation via shared controller (recovery or false alarm)
# --------------------------------------------------------------------------
def deactivate_via_controller(reason):
    outputs = {
        "buzzer_off": buzzer.turn_off,
        "led_off": lambda: led.set_output(1, 0),
        "servo_rest": lambda: servo.set_servo_position(0),
        "lcd_clear": lcd.lcd_clear,
        "lcd_line1": lambda t: lcd.lcd_display_string(t, 1),
        "lcd_line2": lambda t: lcd.lcd_display_string(t, 2),
    }
    controller.deactivate_emergency(outputs, reason)
    # log alarm duration/temp to ThingSpeak (SRS 2.3.6)
    upload_thingspeak()
    print(f"[main] deactivated: {reason}")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    global lcd, controller

    # init HAL
    led.init()
    adc.init()
    buzzer.init()
    moisture_sensor.init()
    input_switch.init()
    servo.init()
    temp_humid_sensor.init()

    lcd = LCD.lcd()
    lcd.lcd_clear()
    lcd.lcd_display_string("System ready :)", 1)   # SRS REQ-02

    controller = FireAlarmController(
        read_temperature=lambda: temp_humid_sensor.read_temp_humidity()[0],
        read_moisture=moisture_sensor.read_sensor,
        get_time=time.time,
        state=State.SLEEP,   # SRS REQ-01: starts in Sleep until slide switch right
    )

    # threads
    keypad.init(key_pressed)
    threading.Thread(target=keypad_thread_fn, daemon=True).start()
    threading.Thread(target=monitor_thread_fn, daemon=True).start()
    threading.Thread(target=telegram_thread_fn, daemon=True).start()

    print("Smart Fire Alert — whole system")
    print("Sleep -> Awake via slide switch; auto/manual activation; recovery + false alarm.")

    while True:
        # Sleep state: wait for slide switch (SRS REQ-01)
        with state_lock:
            if controller.state is State.SLEEP:
                if input_switch.read_slide_switch():
                    controller.state = State.AWAKE
                    lcd.lcd_clear()
                    lcd.lcd_display_string("System ready :)", 1)

        # process keypad (false alarm '123' while in Emergency)
        try:
            key = key_queue.get_nowait()
        except queue.Empty:
            key = None

        if key is not None:
            with state_lock:
                st = controller.state
            if st is State.EMERGENCY:
                if controller.key_pressed(key):
                    deactivate_via_controller(DeactivationReason.FALSE_ALARM)

        time.sleep(0.1)


if __name__ == "__main__":
    main()
