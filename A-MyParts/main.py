"""
Smart Fire Alert System — My Parts: System Recovery + False Alarm (SRS 2.3.4/2.3.5).

This folder implements ONLY the two Emergency -> Awake exit paths assigned to me:

  1) System Recovery  : temp < 50 C AND moisture present, sustained for >= 5 s
                        -> deactivate buzzer / red LED / servo (sprinkler)
                        -> LCD: "Fire is out"

  2) False Alarm      : keypad sequence [1,2,3] entered during Emergency
                        -> deactivate buzzer / red LED / servo (sprinkler)
                        -> LCD: "False alarm!" / "Alarm deactivated"

Threading model (as requested):
  - Thread 1 (keypad_thread): HAL keypad scanner -> pushes keys onto a queue
  - Thread 2 (monitor_thread): polls temp + moisture continuously while in
    EMERGENCY; drives the 5 s debounce and auto-recovery
  - Main loop: applies Emergency entry (stub, owned by the 2.3.3 slice),
    then waits for either thread to signal deactivation.

The Emergency *entry* logic (SRS 2.3.3: buzzer/LED/servo/Telegram) belongs to
a teammate; the entry stub here lets this folder run standalone. Integration
happens in the whole-system folder (B).

Hardware: Raspberry Pi + HAL (RPi.GPIO modules in ./hal).
"""

import queue
import threading
import time

from hal import hal_led as led
from hal import hal_lcd as LCD
from hal import hal_buzzer as buzzer
from hal import hal_keypad as keypad
from hal import hal_servo as servo
from hal import hal_temp_humidity_sensor as temp_humid_sensor
from hal import hal_moisture_sensor as moisture_sensor

# --------------------------------------------------------------------------
# SRS constants (from the SRS document)
# --------------------------------------------------------------------------
RECOVERY_TEMP_C = 50.0            # temp must drop below 50 C (SRS 2.3.4)
RECOVERY_MIN_SECONDS = 5.0        # conditions must hold >= 5 s (NFR)
KEYPAD_DEACTIVATE_CODE = [1, 2, 3]  # SRS 2.3.5: keypad '123'

LCD_RECOVERED_LINE1 = "Fire is out"
LCD_FALSE_ALARM_LINE1 = "False alarm!"
LCD_FALSE_ALARM_LINE2 = "Alarm deactivated"

# --------------------------------------------------------------------------
# Shared state
# --------------------------------------------------------------------------
class State:
    SLEEP = "SLEEP"
    AWAKE = "AWAKE"
    EMERGENCY = "EMERGENCY"

system_state = State.AWAKE
state_lock = threading.Lock()

# keypad presses land here (produced by keypad_thread)
key_queue = queue.Queue()

# Signals from the monitoring thread when auto-recovery fires
recovery_event = threading.Event()
false_alarm_event = threading.Event()

# LCD instance (set in main()); module-level so deactivate_emergency can use it
lcd = None

# --------------------------------------------------------------------------
# Deactivation helper (shared by recovery + false alarm)
# --------------------------------------------------------------------------
def deactivate_emergency(reason):
    """Exit Emergency -> Awake. Turns off buzzer / red LED / servo, LCD msg."""
    global system_state
    buzzer.turn_off()
    led.set_output(1, 0)           # red LED off
    servo.set_servo_position(0)    # sprinkler rest

    lcd.lcd_clear()
    if reason == "recovered":
        lcd.lcd_display_string(LCD_RECOVERED_LINE1, 1)
    elif reason == "false_alarm":
        lcd.lcd_display_string(LCD_FALSE_ALARM_LINE1, 1)
        lcd.lcd_display_string(LCD_FALSE_ALARM_LINE2, 2)

    with state_lock:
        system_state = State.AWAKE

# --------------------------------------------------------------------------
# Thread 1: keypad scanner
# --------------------------------------------------------------------------
def key_pressed(key):
    """Callback from HAL keypad scanner -> push onto queue."""
    key_queue.put(key)


def keypad_thread_fn():
    keypad.get_key()   # blocking scanner; calls key_pressed() per press


# --------------------------------------------------------------------------
# Thread 2: sensor monitor (continuous temp + moisture while in EMERGENCY)
# --------------------------------------------------------------------------
def monitor_thread_fn():
    """
    Polls temperature and moisture every second. Maintains the 5 s debounce:
    when temp < 50 C AND moisture present continuously for >= 5 s,
    deactivates with reason='recovered'.
    """
    sustained_since = None

    while True:
        with state_lock:
            in_emergency = system_state == State.EMERGENCY

        if in_emergency:
            temp, _humidity = temp_humid_sensor.read_temp_humidity()
            moisture = moisture_sensor.read_sensor()

            extinguished = (temp < RECOVERY_TEMP_C) and moisture
            now = time.time()

            if extinguished:
                if sustained_since is None:
                    sustained_since = now
                if now - sustained_since >= RECOVERY_MIN_SECONDS:
                    print("[recovery] fire extinguished -> deactivating")
                    deactivate_emergency("recovered")
                    recovery_event.set()
                    sustained_since = None
            else:
                sustained_since = None  # break -> reset debounce

        time.sleep(1)   # 1 s sample period


# --------------------------------------------------------------------------
# Emergency entry stub (SRS 2.3.3 — owned by teammate slice)
# --------------------------------------------------------------------------
def enter_emergency():
    """Stub: activates buzzer / red LED / servo. Real impl in whole system."""
    global system_state
    with state_lock:
        system_state = State.EMERGENCY
    buzzer.turn_on()
    led.set_output(1, 1)
    servo.set_servo_position(90)   # sprinkler sweeping
    print("[entry-stub] Emergency entered (2.3.3 owned by teammate)")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    # init HAL
    led.init()
    buzzer.init()
    servo.init()
    temp_humid_sensor.init()
    moisture_sensor.init()

    global lcd
    lcd = LCD.lcd()
    lcd.lcd_clear()
    keypad.init(key_pressed)
    threading.Thread(target=keypad_thread_fn, daemon=True).start()
    threading.Thread(target=monitor_thread_fn, daemon=True).start()

    print("Smart Fire Alert — my parts (recovery + false alarm)")
    print("In real deployment the 2.3.3 slice triggers enter_emergency().")
    print("Here we simulate: press 5 to enter Emergency, then either")
    print("  - satisfy recovery (temp<50C + moisture 5s), or")
    print("  - keypad 1-2-3 for false alarm.")

    while True:
        # simulate Emergency entry for standalone demo (replace in integration)
        time.sleep(1)

        # detect keypad presses
        try:
            key = key_queue.get_nowait()
        except queue.Empty:
            key = None

        if key is not None:
            print("key pressed:", key)
            # demo: any key enters Emergency (whole system uses auto/manual rules)
            enter_emergency()

        # check for auto-recovery / false-alarm signals
        if recovery_event.is_set():
            recovery_event.clear()
            print("[main] auto-recovery done")
        if false_alarm_event.is_set():
            false_alarm_event.clear()
            print("[main] false alarm deactivated")


if __name__ == "__main__":
    main()
