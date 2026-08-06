"""
Smart Fire Alert System — System Recovery + False Alarm logic (SRS 2.3.4 / 2.3.5).

Owns the Emergency -> Awake exit paths of the state machine:

  Auto-recovery  : temp < RECOVERY_TEMP_C AND moisture present, sustained
                   continuously for RECOVERY_MIN_SECONDS (default 5 s).
                   -> deactivate buzzer / red LED / servo (sprinkler)
                   -> LCD: "Fire is out"

  False alarm    : keypad sequence [1, 2, 3] entered during Emergency.
                   -> deactivate buzzer / red LED / servo (sprinkler)
                   -> LCD: "False alarm!" / "Alarm deactivated"

Design rules:
- Pure logic only: no direct hardware imports. All hardware access goes through
  injected HAL adapters (see `run_loop`), so this module is unit-testable on any
  host (Windows) and matches the repo's "diagnostic tester" HAL pattern.
- The Emergency *entry* logic (SRS 2.3.3: activate buzzer/LED/servo + Telegram)
  is owned by a teammate slice; this module exposes the shared exit helpers and
  the state enum so both slices integrate without conflict.
- The 5-second "extinguished" condition mirrors NFR: "Fire is considered
  extinguished only when both conditions hold continuously for at least 5 s".
"""

from enum import Enum, auto


# --------------------------------------------------------------------------
# SRS thresholds / constants
# --------------------------------------------------------------------------
RECOVERY_TEMP_C = 50.0          # SRS 2.3.4: temp must drop below 50 C
RECOVERY_MIN_SECONDS = 5.0      # NFR: conditions must hold >= 5 s continuously
SAMPLE_PERIOD_SECONDS = 1.0     # sensor polling period
KEYPAD_DEACTIVATE_CODE = (1, 2, 3)   # SRS 2.3.5: keypad '123'

# Servo "sprinkler" rest position (degrees). Entry logic sweeps the servo;
# recovery/false-alarm stops it back at rest.
SPRINKLER_REST_POSITION = 0

# LCD messages (SRS 2.3.4 / 2.3.5)
LCD_RECOVERED_LINE1 = "Fire is out"
LCD_FALSE_ALARM_LINE1 = "False alarm!"
LCD_FALSE_ALARM_LINE2 = "Alarm deactivated"

# Led output level that means "on" (hal_led.set_output(led, level))
LED_ON = 1
LED_OFF = 0


class State(Enum):
    """System states per SRS (Sleep / Awake / Emergency)."""
    SLEEP = auto()
    AWAKE = auto()
    EMERGENCY = auto()


class DeactivationReason(Enum):
    """Why the Emergency state was exited."""
    RECOVERED = auto()      # auto-recovery: fire extinguished
    FALSE_ALARM = auto()    # manual: keypad '123'


class FireAlarmController:
    """
    Emergency -> Awake exit logic.

    HAL adapters are injected as callables with these signatures:
      read_temperature()  -> float (Celsius)
      read_moisture()     -> bool  (True == water present)
      get_time()          -> float (seconds, monotonic)
    plus output helpers (buzzer/led/servo/lcd) passed to
    `deactivate_emergency` via `outputs`.
    """

    def __init__(self, read_temperature, read_moisture, get_time,
                 state=None):
        self._read_temp = read_temperature
        self._read_moisture = read_moisture
        self._now = get_time
        self.state = state if state is not None else State.AWAKE

        # 5 s debounce bookkeeping
        self._sustained_since = None

        # keypad "123" sequence buffer
        self._seq = []
        self._seq_len = len(KEYPAD_DEACTIVATE_CODE)

    # ------------------------------------------------------------------
    # Continuous monitoring / auto-recovery
    # ------------------------------------------------------------------
    def monitor_once(self):
        """
        Sample sensors and update auto-recovery bookkeeping.

        Returns True when the fire is considered extinguished (SRS 2.3.4:
        temp < 50 C AND moisture present continuously for >= 5 s).
        """
        temp = self._read_temp()
        moisture = self._read_moisture()

        extinguished = (temp < RECOVERY_TEMP_C) and moisture
        now = self._now()

        if extinguished:
            if self._sustained_since is None:
                self._sustained_since = now
            sustained = now - self._sustained_since
            if sustained >= RECOVERY_MIN_SECONDS:
                return True
        else:
            self._sustained_since = None  # reset on any condition break

        return False

    # ------------------------------------------------------------------
    # Keypad "123" sequence
    # ------------------------------------------------------------------
    def key_pressed(self, key):
        """
        Feed a keypad press into the sequence buffer.

        Returns True when the full deactivation code has been entered
        in order (resets the buffer in that case).
        """
        expected = KEYPAD_DEACTIVATE_CODE[len(self._seq)]
        if key == expected:
            self._seq.append(key)
            if len(self._seq) == self._seq_len:
                self._seq = []
                return True
        else:
            # wrong key -> restart sequence
            self._seq = []
            if key == KEYPAD_DEACTIVATE_CODE[0]:
                self._seq.append(key)
        return False

    # ------------------------------------------------------------------
    # Deactivation (shared exit helper for both paths)
    # ------------------------------------------------------------------
    def deactivate_emergency(self, outputs, reason):
        """
        Exit Emergency -> Awake. Turns off buzzer / red LED / servo and
        shows the reason-specific LCD message.

        `outputs` is a dict of callables:
          {
            'buzzer_off':   lambda: None,
            'led_off':      lambda: None,
            'servo_rest':   lambda: None,
            'lcd_clear':    lambda: None,
            'lcd_line1':    lambda text: None,
            'lcd_line2':    lambda text: None,
          }
        """
        outputs['buzzer_off']()
        outputs['led_off']()
        outputs['servo_rest']()
        outputs['lcd_clear']()

        if reason is DeactivationReason.RECOVERED:
            outputs['lcd_line1'](LCD_RECOVERED_LINE1)
        elif reason is DeactivationReason.FALSE_ALARM:
            outputs['lcd_line1'](LCD_FALSE_ALARM_LINE1)
            outputs['lcd_line2'](LCD_FALSE_ALARM_LINE2)

        self.state = State.AWAKE

    # ------------------------------------------------------------------
    # Main loop (drives monitoring while in Emergency)
    # ------------------------------------------------------------------
    def run_loop(self, outputs, get_key=None, poll_delay=None):
        """
        Blocking loop that runs while the controller is in EMERGENCY.

        - Polls sensors each cycle; on sustained extinguished condition,
          deactivates with RECOVERED.
        - If `get_key` is provided (keypad blocking read), feeds presses
          into the "123" buffer; on match deactivates with FALSE_ALARM.

        Callers may pass their own poll_delay (default SAMPLE_PERIOD_SECONDS).
        """
        if poll_delay is None:
            poll_delay = SAMPLE_PERIOD_SECONDS
        import time as _time
        delay = poll_delay if callable(poll_delay) else (lambda: _time.sleep(poll_delay))

        while self.state is State.EMERGENCY:
            if self.monitor_once():
                self.deactivate_emergency(outputs, DeactivationReason.RECOVERED)
                break

            if get_key is not None:
                key = get_key()
                if key is not None and self.key_pressed(key):
                    self.deactivate_emergency(outputs, DeactivationReason.FALSE_ALARM)
                    break

            delay()
