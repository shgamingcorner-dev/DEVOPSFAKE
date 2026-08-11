"""
Emergency response actions (SRS 2.3.3).

Adapted from Vishal's branch (vishals_part) with the missing Telegram wiring
fixed: `send_telegram_alert()` was an empty body - it now calls Harshita's
`telegram_bot.send_emergency_alert()` so REQ-07 (notify owner/caregiver/SCDF)
actually works.

REQ coverage:
  REQ-06: activate_buzzer()          (continuous beep until stop_emergency_outputs)
  REQ-07: send_telegram_alert()      -> telegram_bot.send_emergency_alert()
  REQ-08: turn_on_red_led() / turn_off_red_led()
  REQ-09: activate_sprinkler()       (servo opens, returns immediately)
  REQ-10: display_emergency_message(lcd)
  orchestration: emergency_response(lcd)
  deactivation: stop_emergency_outputs()
"""

import threading
import time

from hal import hal_led as led
from hal import hal_buzzer as buzzer
from hal import hal_servo as servo

from telegram_bot import send_emergency_alert


# ---------------------------------------------------------------------------
# Configuration - adjust to match your wiring.
# ---------------------------------------------------------------------------

RED_LED_CHANNEL = 1          # channel passed to led.set_output(channel, state)
SPRINKLER_SERVO_ANGLE = 90   # degrees, sprinkler "open" position
SERVO_RESET_ANGLE = 0        # degrees, sprinkler "closed" position
BUZZER_BEEP_SECONDS = 0.5    # on/off time for the continuous beep pattern


# ---------------------------------------------------------------------------
# Continuous buzzer (non-blocking background thread)
# ---------------------------------------------------------------------------

_buzzer_stop = threading.Event()


def _buzzer_loop():
    """Keep beeping until stop_emergency_outputs() sets the stop event."""
    while not _buzzer_stop.is_set():
        buzzer.turn_on()
        time.sleep(BUZZER_BEEP_SECONDS)
        buzzer.turn_off()
        time.sleep(BUZZER_BEEP_SECONDS)


# ---------------------------------------------------------------------------
# REQ-06: Activate the buzzer
# ---------------------------------------------------------------------------

def activate_buzzer():
    """Start the continuous audible emergency alert (non-blocking thread)."""
    print("REQ-06: Buzzer activated (continuous).")
    _buzzer_stop.clear()
    threading.Thread(target=_buzzer_loop, daemon=True).start()


# ---------------------------------------------------------------------------
# REQ-07: Send a simulated emergency notification via Telegram
# ---------------------------------------------------------------------------

def send_telegram_alert(message="Fire detected!"):
    """
    Send the emergency notification to the owner, caregiver and SCDF
    (REQ-07). Delegates to Harshita's telegram_bot.send_emergency_alert().
    """
    send_emergency_alert(message)


# ---------------------------------------------------------------------------
# REQ-08: Red LED
# ---------------------------------------------------------------------------

def turn_on_red_led():
    """Turn on the red LED to visually indicate the emergency."""
    led.set_output(RED_LED_CHANNEL, 1)
    print("REQ-08: Red LED turned on.")


def turn_off_red_led():
    """Turn off the red LED (used when the system exits Emergency state)."""
    led.set_output(RED_LED_CHANNEL, 0)
    print("Red LED turned off.")


# ---------------------------------------------------------------------------
# REQ-09: Servo-driven water sprinkler
# ---------------------------------------------------------------------------

def activate_sprinkler():
    """
    Open the servo acting as a water sprinkler to help tame the fire while
    waiting for SCDF to arrive. Returns immediately (non-blocking) - the
    servo stays open until stop_emergency_outputs() closes it.
    """
    servo.set_servo_position(SPRINKLER_SERVO_ANGLE)
    print("REQ-09: Sprinkler servo opened.")


# ---------------------------------------------------------------------------
# REQ-10: LCD emergency message
# ---------------------------------------------------------------------------

def display_emergency_message(lcd):
    """
    Display the emergency message on the LCD:
        Line 1: "FIRE DETECTED!"
        Line 2: "EVACUATE NOW"

    Args:
        lcd: an initialised hal_lcd.lcd() instance (the one created in main()).
    """
    lcd.lcd_clear()
    lcd.lcd_display_string("FIRE DETECTED!", 1)
    lcd.lcd_display_string("EVACUATE NOW", 2)
    print("REQ-10: LCD displaying emergency message.")


# ---------------------------------------------------------------------------
# Orchestrator - entering the Emergency response state
# ---------------------------------------------------------------------------

def emergency_response(lcd):
    """
    Entry point for the Emergency response state (Section 2.3.3).

    Call this when either automatic activation (REQ-03: temperature
    >= 60C or LDR detects smoke) or manual activation (REQ-04: "995"
    command via Telegram) is triggered. All outputs stay on until
    stop_emergency_outputs() is called (on recovery or false alarm).
    """
    print("Emergency response state entered.")
    activate_buzzer()
    turn_on_red_led()
    display_emergency_message(lcd)
    send_telegram_alert("Fire detected!")
    activate_sprinkler()


# ---------------------------------------------------------------------------
# Deactivation - stop all emergency outputs
# ---------------------------------------------------------------------------

def stop_emergency_outputs():
    """
    Stop the continuous buzzer, turn off the red LED and close the sprinkler.
    Call this when the system exits Emergency (recovery or false alarm).
    """
    _buzzer_stop.set()
    buzzer.turn_off()
    turn_off_red_led()
    servo.set_servo_position(SERVO_RESET_ANGLE)
    print("Emergency outputs stopped.")


def reset_system(lcd):
    """Reset outputs after the emergency has been handled."""
    stop_emergency_outputs()
    lcd.lcd_clear()
    print("System reset to normal state.")
