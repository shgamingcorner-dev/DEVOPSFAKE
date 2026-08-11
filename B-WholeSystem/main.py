
#    Sleep ->(slide switch right)->> Awake
 #   Awake ->(auto: temp>=60C OR LDR smoke)->> Emergency
  #  Awake ->(Telegram "995")->> Emergency            (manual)
#    Emergency ->(temp<50C AND moisture, 5s)->> Awake (auto recovery)
 #   Emergency ->(keypad "123")->> Awake              (false alarm)


#  - keypad_thread   : HAL keypad scanner -> key queue
 # - monitor_thread  : polls temp + moisture + LDR continuously;
 #                     drives auto-detection (entry) and auto-recovery (exit)
 # - telegram_thread : polls Telegram for the "995" manual command
#  - main loop       : applies state transitions + outputs

#Recovery + False Alarm logic is in fire_alarm.py (shared with folder A).


#Networking uses the `requests` library directly


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

# Teammates' modules:
#   - telegram_bot.py     (Harshita) REQ-07 multi-recipient + REQ-04 '995'
#   - emergency_response.py (Vishal) REQ-06/07/LED/servo/LCD emergency actions
from telegram_bot import send_emergency_alert, start_command_listener
from emergency_response import (emergency_response, reset_system,
                                stop_emergency_outputs, display_emergency_message)

# --------------------------------------------------------------------------
# Environment variables (from .env - see .env.example)
# --------------------------------------------------------------------------
# Load by ABSOLUTE path (relative to this file), same as telegram_bot.py,
# so it works no matter which directory the program is run from.
from pathlib import Path
_HERE = Path(__file__).resolve().parent
load_dotenv(_HERE / ".env")

# Startup diagnostic: print whether secrets loaded (remove for production)
_api = os.getenv("THINGSPEAK_API_KEY", "")
_tok = os.getenv("TELEGRAM_BOT_TOKEN", "")
print(f"[env] ThingSpeak key: {'OK' if _api and not _api.startswith('X'*16) else 'MISSING/placeholder'}")
print(f"[env] Telegram token: {'OK' if _tok and ':' in _tok and not _tok.startswith('123456789:AAExample') else 'MISSING/placeholder'}")

# SRS constants
FIRE_TEMP_C = 60.0            # SRS 2.3.3: auto-activation temp threshold
LDR_SMOKE_THRESHOLD = 300     # ADC value below this => smoke (calibrate!)
THINGSPEAK_UPLOAD_SECONDS = 15.0   # SRS 2.4.2
SAMPLE_PERIOD_SECONDS = 1.0

# Telegram credentials are read by telegram_bot.py from .env
# (TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_CHAT_ID, TELEGRAM_CAREGIVER_CHAT_ID,
#  TELEGRAM_SCDF_CHAT_ID) - see .env.example

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
# Pending REQ-17 alarm log (duration + temp) that couldn't be sent because
# ThingSpeak's free tier enforces a 15 s minimum between writes. It's
# flushed on the next sensor upload (every 15 s) so it's never lost.
_pending_alarm_log = None

# LCD instance (set in main()); module-level so deactivation can use it
lcd = None

# True while the LCD is showing the keypad entry buffer (for idle revert)
_keypad_lcd_active = False

# --------------------------------------------------------------------------
# HAL callback
# --------------------------------------------------------------------------
def key_pressed(key):
    key_queue.put(key)


def keypad_thread_fn():
    keypad.get_key()


# --------------------------------------------------------------------------
# Telegram helpers (Harshita's telegram_bot.py - REQ-04 '995' + REQ-07 alerts)
# --------------------------------------------------------------------------
# send_emergency_alert() -> sends to owner/caregiver/SCDF (REQ-07)
# start_command_listener(on_995_received) -> polls '995' (REQ-04)
# Both read credentials from .env (TELEGRAM_* env vars).
# 

# --------------------------------------------------------------------------
# Sensor read helper: DHT11 fails intermittently (-100). Retry a few times.
# --------------------------------------------------------------------------
def read_temp_humidity_with_retry(retries=3, delay=0.5):
    """Read temp/humidity, retrying on the HAL's -100 failure sentinel."""
    for attempt in range(retries):
        temp, hum = temp_humid_sensor.read_temp_humidity()
        if temp != -100 and hum != -100:
            return temp, hum
        time.sleep(delay)
    # last resort: return whatever we have (may still be -100)
    return temp, hum


# --------------------------------------------------------------------------
# ThingSpeak helper (direct HTTPS via requests)
# --------------------------------------------------------------------------
def _post_thingspeak(payload):
    """POST a payload to ThingSpeak, respecting the 15 s free-tier cooldown.

    Returns True if the write went through (or was accepted), False if it
    was skipped because of the cooldown (caller may queue it).
    """
    global last_thingspeak_upload
    now = time.time()
    if now - last_thingspeak_upload < 15.0:
        # still inside ThingSpeak's minimum-write window - would be dropped
        return False
    print(f"[thingspeak] post: {payload}")
    try:
        requests.post(THINGSPEAK_URL, data=payload, timeout=5)
        last_thingspeak_upload = now
        return True
    except Exception as e:
        print(f"[thingspeak] post failed (offline?): {e}")
        # still count the attempt so we don't hammer the API
        last_thingspeak_upload = now
        return True  # treat as sent (avoid infinite retry loop)


def _flush_pending_alarm_log():
    """Send any queued REQ-17 alarm log on the next available slot."""
    global _pending_alarm_log
    if _pending_alarm_log is None:
        return
    if _post_thingspeak(_pending_alarm_log):
        print("[thingspeak] flushed pending alarm log")
        _pending_alarm_log = None


def upload_thingspeak():
    """Upload sensor readings to ThingSpeak (SRS 2.4.2)."""
    global _pending_alarm_log
    # flush a queued alarm log first (it's the higher-priority REQ-17 data)
    _flush_pending_alarm_log()
    temp, _h = read_temp_humidity_with_retry()
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
    """Emergency response actions on fire detection (SRS 2.3.3)."""
    with state_lock:
        if controller.state is State.EMERGENCY:
            return
        controller.state = State.EMERGENCY
        set_alarm_start()   # REQ-17: start alarm duration timer

    # Vishal's emergency_response() -> buzzer + red LED + LCD + Telegram + sprinkler
    emergency_response(lcd)


# --------------------------------------------------------------------------
# Thread: sensor monitor (auto-detection + auto-recovery + ThingSpeak)
# --------------------------------------------------------------------------
def monitor_thread_fn():
    global last_thingspeak_upload
    while True:
        temp, _h = read_temp_humidity_with_retry()
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
# Thread: Telegram manual command ("995") - Harshita's telegram_bot listener
# --------------------------------------------------------------------------
def telegram_thread_fn():
    # start_command_listener runs poll_for_commands in its own daemon thread;
    # only trigger '995' when the system is Awake (not in Sleep).
    def on_995():
        with state_lock:
            if controller.state is State.AWAKE:
                print("[telegram] manual '995' -> emergency")
                should_activate = True
            else:
                print("[telegram] '995' ignored (system not Awake)")
                should_activate = False
        # call activate_emergency() OUTSIDE the lock - it re-acquires the
        # lock itself (threading.Lock is NOT reentrant -> deadlock if nested)
        if should_activate:
            activate_emergency()
    start_command_listener(on_995)


# --------------------------------------------------------------------------
# Deactivation via shared controller (recovery or false alarm)
# --------------------------------------------------------------------------
alarm_start_time = None   # set when Emergency begins (for REQ-17 alarm duration)


def set_alarm_start():
    """Record when the Emergency state began (for REQ-17 alarm duration)."""
    global alarm_start_time
    if alarm_start_time is None:
        alarm_start_time = time.time()


def upload_alarm_log():
    """
    REQ-17: on deactivation, upload alarm duration + recorded temperature
    to ThingSpeak (fields 4 = duration seconds, 5 = temperature at
    deactivation).

    If ThingSpeak's 15 s free-tier cooldown is still active, the log is
    QUEUED (in _pending_alarm_log) and flushed on the next sensor upload
    (upload_thingspeak) so it is never silently dropped.
    """
    global alarm_start_time, _pending_alarm_log
    duration = 0
    if alarm_start_time is not None:
        duration = round(time.time() - alarm_start_time, 1)
    temp, _h = read_temp_humidity_with_retry()
    payload = {
        "api_key": THINGSPEAK_API_KEY,
        "field4": duration,
        "field5": temp,
    }
    print(f"[thingspeak] alarm log: {payload}")
    if not _post_thingspeak(payload):
        # cooldown active -> queue it; will flush on next 15 s upload
        _pending_alarm_log = payload
        print("[thingspeak] alarm log queued (15 s cooldown) - will flush later")
    alarm_start_time = None   # reset for next alarm


def deactivate_via_controller(reason):
    # Physical outputs (buzzer/LED/servo) are stopped by
    # emergency_response.stop_emergency_outputs() AFTER the controller
    # sets state + LCD. The controller's outputs dict only needs the LCD
    # helpers; pass no-op for the physical ones to avoid double-calls.
    global _keypad_lcd_active
    _keypad_lcd_active = False
    outputs = {
        "buzzer_off": lambda: None,
        "led_off": lambda: None,
        "servo_rest": lambda: None,
        "lcd_clear": lcd.lcd_clear,
        "lcd_line1": lambda t: lcd.lcd_display_string(t, 1),
        "lcd_line2": lambda t: lcd.lcd_display_string(t, 2),
    }
    controller.deactivate_emergency(outputs, reason)
    # stop the continuous buzzer + sprinkler from the background thread
    stop_emergency_outputs()
    # REQ-17: log alarm duration/temp to ThingSpeak
    upload_alarm_log()
    # Post-deactivation UX (beyond SRS, for the demo):
    #   - keep the deactivation message ("Fire is out" / "False alarm!") on
    #     the LCD for a moment, then show "System ready :)"
    #   - Telegram status so owner/caregiver/SCDF know the alarm is resolved
    import time as _t
    _t.sleep(2.0)   # let the REQ-13/16 message stay visible
    lcd.lcd_display_string("System ready :)", 1)
    try:
        if reason is DeactivationReason.RECOVERED:
            send_emergency_alert("Fire is out - alarm resolved.")
        elif reason is DeactivationReason.FALSE_ALARM:
            send_emergency_alert("False alarm - system reset to normal.")
    except Exception as e:
        print(f"[main] Telegram status failed: {e}")
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
    lcd.lcd_display_string("System asleep", 1)   # SRS REQ-01: starts in Sleep

    controller = FireAlarmController(
        read_temperature=lambda: read_temp_humidity_with_retry()[0],
        read_moisture=moisture_sensor.read_sensor,
        get_time=time.time,
        state=State.SLEEP,   # SRS REQ-01: starts in Sleep until slide switch right
    )

    # threads
    keypad.init(key_pressed)
    threading.Thread(target=keypad_thread_fn, daemon=True).start()
    threading.Thread(target=monitor_thread_fn, daemon=True).start()
    threading.Thread(target=telegram_thread_fn, daemon=True).start()

    print("Smart Fire Alert - whole system")
    print("Sleep -> Awake via slide switch; auto/manual activation; recovery + false alarm.")

    while True:
        # Slide switch: left = Sleep, right = Awake (checked continuously)
        with state_lock:
            st = controller.state
            sw = input_switch.read_slide_switch()
            if st is State.SLEEP and sw:
                controller.state = State.AWAKE
                lcd.lcd_clear()
                lcd.lcd_display_string("System ready :)", 1)
                print("[main] slide switch -> Awake")
            elif st is State.AWAKE and not sw:
                controller.state = State.SLEEP
                lcd.lcd_clear()
                lcd.lcd_display_string("System asleep", 1)
                print("[main] slide switch -> Sleep")

        # process keypad (false alarm '123' while in Emergency)
        # drain ALL queued keys this cycle so fast presses aren't dropped
        key_pressed_this_cycle = False
        while True:
            try:
                key = key_queue.get_nowait()
            except queue.Empty:
                break
            key_pressed_this_cycle = True
            with state_lock:
                st = controller.state
            if st is State.EMERGENCY:
                if controller.key_pressed(key):
                    deactivate_via_controller(DeactivationReason.FALSE_ALARM)
                    break  # deactivated, stop processing this batch

        # LCD feedback: while in Emergency, show the last typed keys (with a
        # 5 s idle reset back to the normal emergency message).
        global _keypad_lcd_active
        with state_lock:
            st = controller.state
        if st is State.EMERGENCY:
            display = controller.keypad_display()
            if display is not None:
                lcd.lcd_clear()
                lcd.lcd_display_string(display, 1)
                _keypad_lcd_active = True
            elif _keypad_lcd_active:
                # idle timeout -> back to the normal emergency message
                display_emergency_message(lcd)
                _keypad_lcd_active = False

        time.sleep(0.1)


if __name__ == "__main__":
    main()
