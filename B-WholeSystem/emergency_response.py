"""
Emergency response actions (SRS 2.3.3).

Adapted from Vishal's branch (vishals_part) with the missing Telegram wiring
fixed: `send_telegram_alert()` was an empty body — it now calls Harshita's
`telegram_bot.send_emergency_alert()` so REQ-07 (notify owner/caregiver/SCDF)
actually works.

REQ coverage:
  REQ-06: activate_buzzer()
  REQ-07: send_telegram_alert()          -> telegram_bot.send_emergency_alert()
  REQ-0?: turn_on_red_led() / turn_off_red_led()
  REQ-0?: activate_sprinkler()
  REQ-0?: display_emergency_message(lcd)
  orchestration: emergency_response(lcd)
"""

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


# ---------------------------------------------------------------------------
# REQ-06: Activate the buzzer
# ---------------------------------------------------------------------------

def activate_buzzer():
    """Sound the buzzer to provide an audible emergency alert."""
    print("REQ-06: Buzzer activated.")
    buzzer.beep(0.5, 0.5, 5)  # on_time, off_time, repeat


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
# REQ-0?: Turn on the red LED
# ---------------------------------------------------------------------------

def turn_on_red_led():
    """Turn on the red LED to visually indicate the emergency."""
    led.set_output(RED_LED_CHANNEL, 1)
    print("REQ-0?: Red LED turned on.")


def turn_off_red_led():
    """Turn off the red LED (used when the system exits Emergency state)."""
    led.set_output(RED_LED_CHANNEL, 0)
    print("Red LED turned off.")


# ---------------------------------------------------------------------------
# REQ-0?: Activate the servo-driven water sprinkler
# ---------------------------------------------------------------------------

def activate_sprinkler(run_time=5):
    """
    Activate the servo motor acting as a water sprinkler to help tame
    the fire while waiting for SCDF to arrive.

    Args:
        run_time: how long (in seconds) the sprinkler stays open.
    """
    servo.set_servo_position(SPRINKLER_SERVO_ANGLE)
    print("REQ-0?: Sprinkler servo opened.")
    time.sleep(run_time)

    servo.set_servo_position(SERVO_RESET_ANGLE)
    print("Sprinkler servo closed.")


# ---------------------------------------------------------------------------
# REQ-0?: LCD emergency message
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
    print("REQ-0?: LCD displaying emergency message.")


# ---------------------------------------------------------------------------
# Orchestrator - entering the Emergency response state
# ---------------------------------------------------------------------------

def emergency_response(lcd):
    """
    Entry point for the Emergency response state (Section 2.3.3).

    Call this when either automatic activation (REQ-03: temperature
    >= 60C or LDR detects smoke) or manual activation (REQ-04: "995"
    command via Telegram) is triggered.
    """
    print("Emergency response state entered.")
    activate_buzzer()
    turn_on_red_led()
    display_emergency_message(lcd)
    send_telegram_alert("Fire detected!")
    activate_sprinkler()


def reset_system(lcd):
    """Reset outputs after the emergency has been handled."""
    turn_off_red_led()
    lcd.lcd_clear()
    print("System reset to normal state.")
