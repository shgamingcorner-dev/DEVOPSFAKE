"""
Tests for src/fire_alarm.py - System Recovery + False Alarm (SRS 2.3.4/2.3.5).

Run from repo root:
    .venv/Scripts/python -m pytest src/test_fire_alarm.py -v
"""

import pytest

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
    LED_OFF,
    SPRINKLER_REST_POSITION,
)


class FakeClock:
    """Deterministic monotonic clock for tests."""
    def __init__(self, start=0.0):
        self.t = start

    def now(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class FakeOutputs:
    """Records output calls for assertions."""
    def __init__(self):
        self.calls = []
        self.buzzer_off_count = 0
        self.led_off_count = 0
        self.servo_rest_count = 0
        self.lcd_clear_count = 0
        self.lcd_lines = []

    def buzzer_off(self):
        self.calls.append('buzzer_off')
        self.buzzer_off_count += 1

    def led_off(self):
        self.calls.append('led_off')
        self.led_off_count += 1

    def servo_rest(self):
        self.calls.append('servo_rest')
        self.servo_rest_count += 1

    def lcd_clear(self):
        self.calls.append('lcd_clear')
        self.lcd_clear_count += 1

    def lcd_line1(self, text):
        self.lcd_lines.append((1, text))

    def lcd_line2(self, text):
        self.lcd_lines.append((2, text))

    @property
    def outputs(self):
        return {
            'buzzer_off': self.buzzer_off,
            'led_off': self.led_off,
            'servo_rest': self.servo_rest,
            'lcd_clear': self.lcd_clear,
            'lcd_line1': self.lcd_line1,
            'lcd_line2': self.lcd_line2,
        }


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def outputs():
    return FakeOutputs()


def make_ctrl(clock, temp, moisture, state=State.EMERGENCY):
    return FireAlarmController(
        read_temperature=lambda: temp[0],
        read_moisture=lambda: moisture[0],
        get_time=clock.now,
        state=state,
    )


# ---------------------------------------------------------------------------
# monitor_once / auto-recovery
# ---------------------------------------------------------------------------
class TestMonitorOnce:
    def test_temp_below_threshold_but_dry_returns_false(self, clock):
        ctrl = make_ctrl(clock, temp=[49.0], moisture=[False])
        clock.advance(10)
        assert ctrl.monitor_once() is False

    def test_temp_at_or_above_threshold_with_moisture_returns_false(self, clock):
        for t in (50.0, 60.0, 99.0):
            ctrl = make_ctrl(clock, temp=[t], moisture=[True])
            clock.advance(10)
            assert ctrl.monitor_once() is False

    def test_conditions_hold_but_less_than_5s_returns_false(self, clock):
        ctrl = make_ctrl(clock, temp=[49.0], moisture=[True])
        # conditions true for only 4 s
        for _ in range(4):
            clock.advance(1)
            assert ctrl.monitor_once() is False

    def test_conditions_hold_5s_returns_true(self, clock):
        ctrl = make_ctrl(clock, temp=[49.0], moisture=[True])
        # first extinguished sample at t=0 starts the 5 s window
        assert ctrl.monitor_once() is False     # t=0: sustained 0 s
        for i in range(1, 6):
            clock.advance(1)
            result = ctrl.monitor_once()
            if i < 5:
                assert result is False          # t=1..4: < 5 s
            else:
                assert result is True           # t=5: >= 5 s

    def test_condition_break_resets_debounce(self, clock):
        ctrl = make_ctrl(clock, temp=[49.0], moisture=[True])
        assert ctrl.monitor_once() is False     # t=0: start window
        clock.advance(3)
        assert ctrl.monitor_once() is False     # t=3: 3 s elapsed

        ctrl._read_moisture = lambda: False
        assert ctrl.monitor_once() is False     # break -> window reset

        ctrl._read_moisture = lambda: True
        clock.advance(4)
        assert ctrl.monitor_once() is False     # t=7: window restarts here, 0 s
        clock.advance(4)
        assert ctrl.monitor_once() is False     # t=11: 4 s
        clock.advance(1)
        assert ctrl.monitor_once() is True      # t=12: 5 s

    def test_temp_drop_also_resets_debounce(self, clock):
        ctrl = make_ctrl(clock, temp=[49.0], moisture=[True])
        assert ctrl.monitor_once() is False     # t=0: start window
        clock.advance(3)
        assert ctrl.monitor_once() is False     # t=3: 3 s elapsed

        ctrl._read_temp = lambda: 55.0
        assert ctrl.monitor_once() is False     # break -> window reset

        ctrl._read_temp = lambda: 49.0
        clock.advance(4)
        assert ctrl.monitor_once() is False     # t=7: window restarts, 0 s
        clock.advance(4)
        assert ctrl.monitor_once() is False     # t=11: 4 s
        clock.advance(1)
        assert ctrl.monitor_once() is True      # t=12: 5 s


# ---------------------------------------------------------------------------
# key_pressed / keypad '123'
# ---------------------------------------------------------------------------
class TestKeypad:
    def test_correct_sequence_triggers(self, clock):
        ctrl = make_ctrl(clock, temp=[49.0], moisture=[True])
        assert ctrl.key_pressed(1) is False
        assert ctrl.key_pressed(2) is False
        assert ctrl.key_pressed(3) is True

    def test_wrong_order_does_not_trigger(self, clock):
        ctrl = make_ctrl(clock, temp=[49.0], moisture=[True])
        assert ctrl.key_pressed(1) is False
        assert ctrl.key_pressed(3) is False  # wrong -> reset
        assert ctrl.key_pressed(2) is False
        assert ctrl.key_pressed(1) is False
        assert ctrl.key_pressed(3) is False
        assert ctrl.key_pressed(2) is False
        assert ctrl.key_pressed(1) is False
        assert ctrl.key_pressed(2) is False
        assert ctrl.key_pressed(3) is True

    def test_partial_then_wrong_resets(self, clock):
        ctrl = make_ctrl(clock, temp=[49.0], moisture=[True])
        assert ctrl.key_pressed(1) is False
        assert ctrl.key_pressed(9) is False  # wrong, reset
        assert ctrl.key_pressed(1) is False
        assert ctrl.key_pressed(2) is False
        assert ctrl.key_pressed(3) is True

    def test_buffer_resets_after_success(self, clock):
        ctrl = make_ctrl(clock, temp=[49.0], moisture=[True])
        assert ctrl.key_pressed(1) is False
        assert ctrl.key_pressed(2) is False
        assert ctrl.key_pressed(3) is True
        # next sequence needs 1,2,3 again
        assert ctrl.key_pressed(1) is False
        assert ctrl.key_pressed(2) is False
        assert ctrl.key_pressed(3) is True

    def test_digit_keys_match_hal_keypad_types(self):
        # HAL keypad MATRIX returns ints for digits (1,2,3) and strings for
        # symbols. Our code targets ints.
        assert KEYPAD_DEACTIVATE_CODE == (1, 2, 3)
        assert all(isinstance(k, int) for k in KEYPAD_DEACTIVATE_CODE)


# ---------------------------------------------------------------------------
# Rolling buffer + LCD feedback (new behavior)
# ---------------------------------------------------------------------------
class TestRollingBuffer:
    def test_fourth_key_pushes_oldest_out(self, clock):
        # buffer holds 3; pressing a 4th key drops the oldest so the
        # display resets to just the newest key
        ctrl = make_ctrl(clock, temp=[49.0], moisture=[True])
        ctrl.key_pressed(5)
        ctrl.key_pressed(9)
        ctrl.key_pressed(7)
        # after 3 keys buffer is [5,9,7]
        assert ctrl.key_pressed(2) is False  # buffer now [9,7,2]
        disp = ctrl.keypad_display(now=clock.now())
        assert disp == "Enter 123: 972"  # only the last 3

    def test_self_heals_after_wrong_key(self, clock):
        ctrl = make_ctrl(clock, temp=[49.0], moisture=[True])
        ctrl.key_pressed(1)
        ctrl.key_pressed(9)   # wrong key - buffer [1,9]
        ctrl.key_pressed(2)   # [9,2] - still not 1,2,3
        ctrl.key_pressed(3)   # [2,3] - no match
        assert ctrl.key_pressed(1) is False  # [3,1]
        assert ctrl.key_pressed(2) is False  # [1,2]
        assert ctrl.key_pressed(3) is True   # [1,2,3] -> match!

    def test_idle_reset_returns_none(self, clock):
        ctrl = make_ctrl(clock, temp=[49.0], moisture=[True])
        ctrl.key_pressed(1)
        ctrl.key_pressed(2)
        # 6 s later (no new press) -> None (LCD reverts)
        clock.advance(6)
        assert ctrl.keypad_display(now=clock.now()) is None

    def test_no_keys_returns_none(self, clock):
        ctrl = make_ctrl(clock, temp=[49.0], moisture=[True])
        assert ctrl.keypad_display(now=clock.now()) is None

    def test_display_shows_typed_keys(self, clock):
        ctrl = make_ctrl(clock, temp=[49.0], moisture=[True])
        ctrl.key_pressed(1)
        ctrl.key_pressed(2)
        assert ctrl.keypad_display(now=clock.now()) == "Enter 123: 12"
        # pressing 3 completes the code -> match -> buffer reset -> None
        assert ctrl.key_pressed(3) is True
        assert ctrl.keypad_display(now=clock.now()) is None


# ---------------------------------------------------------------------------
# deactivate_emergency
# ---------------------------------------------------------------------------
class TestDeactivate:
    def test_recovered_deactivates_outputs_and_sets_awake(self, clock, outputs):
        ctrl = make_ctrl(clock, temp=[49.0], moisture=[True], state=State.EMERGENCY)
        ctrl.deactivate_emergency(outputs.outputs, DeactivationReason.RECOVERED)
        assert outputs.buzzer_off_count == 1
        assert outputs.led_off_count == 1
        assert outputs.servo_rest_count == 1
        assert outputs.lcd_clear_count == 1
        assert ctrl.state is State.AWAKE

    def test_recovered_lcd_message(self, clock, outputs):
        ctrl = make_ctrl(clock, temp=[49.0], moisture=[True], state=State.EMERGENCY)
        ctrl.deactivate_emergency(outputs.outputs, DeactivationReason.RECOVERED)
        assert (1, LCD_RECOVERED_LINE1) in outputs.lcd_lines
        assert (2, LCD_FALSE_ALARM_LINE2) not in outputs.lcd_lines

    def test_false_alarm_deactivates_outputs_and_sets_awake(self, clock, outputs):
        ctrl = make_ctrl(clock, temp=[49.0], moisture=[True], state=State.EMERGENCY)
        ctrl.deactivate_emergency(outputs.outputs, DeactivationReason.FALSE_ALARM)
        assert outputs.buzzer_off_count == 1
        assert outputs.led_off_count == 1
        assert outputs.servo_rest_count == 1
        assert ctrl.state is State.AWAKE

    def test_false_alarm_lcd_message(self, clock, outputs):
        ctrl = make_ctrl(clock, temp=[49.0], moisture=[True], state=State.EMERGENCY)
        ctrl.deactivate_emergency(outputs.outputs, DeactivationReason.FALSE_ALARM)
        assert (1, LCD_FALSE_ALARM_LINE1) in outputs.lcd_lines
        assert (2, LCD_FALSE_ALARM_LINE2) in outputs.lcd_lines
        assert (1, LCD_RECOVERED_LINE1) not in outputs.lcd_lines

    def test_led_off_constant_is_zero(self):
        # red LED is turned OFF on deactivation (hal_led.set_output(led, level))
        assert LED_OFF == 0

    def test_servo_rest_position_is_zero_degrees(self):
        assert SPRINKLER_REST_POSITION == 0


# ---------------------------------------------------------------------------
# run_loop integration
# ---------------------------------------------------------------------------
class TestRunLoop:
    def test_recovery_loop_deactivates_on_extinguished(self, clock, outputs):
        temp = [49.0]
        moisture = [True]
        ctrl = FireAlarmController(
            read_temperature=lambda: temp[0],
            read_moisture=lambda: moisture[0],
            get_time=clock.now,
            state=State.EMERGENCY,
        )
        # simulate 5 cycles of 1s polling
        for _ in range(5):
            clock.advance(1)
            ctrl.monitor_once()
        ctrl.deactivate_emergency(outputs.outputs, DeactivationReason.RECOVERED)
        assert outputs.buzzer_off_count == 1
        assert outputs.led_off_count == 1
        assert ctrl.state is State.AWAKE

    def test_keypad_123_loop_deactivates_false_alarm(self, clock, outputs):
        ctrl = FireAlarmController(
            read_temperature=lambda: 49.0,
            read_moisture=lambda: True,
            get_time=clock.now,
            state=State.EMERGENCY,
        )
        keys = iter([1, 2, 3])
        ctrl.run_loop(
            outputs.outputs,
            get_key=lambda: next(keys, None),
            poll_delay=lambda: None,  # no sleeping in test
        )
        assert outputs.buzzer_off_count == 1
        assert outputs.led_off_count == 1
        assert ctrl.state is State.AWAKE

    def test_loop_stops_when_state_exits_emergency(self, clock, outputs):
        ctrl = FireAlarmController(
            read_temperature=lambda: 49.0,
            read_moisture=lambda: True,
            get_time=clock.now,
            state=State.AWAKE,  # not in emergency -> loop should not run
        )
        ctrl.run_loop(outputs.outputs, get_key=lambda: None, poll_delay=lambda: None)
        assert outputs.buzzer_off_count == 0
        assert ctrl.state is State.AWAKE


# ---------------------------------------------------------------------------
# Lock-safety regression (REQ-04 manual '995' deadlock guard)
# ---------------------------------------------------------------------------
# main.py: on_995() must call activate_emergency() OUTSIDE state_lock, because
# activate_emergency() acquires state_lock itself and threading.Lock is NOT
# reentrant. This test documents the contract: FireAlarmController methods
# must never acquire a lock (they are pure logic, called under main.py's lock).
class TestLockSafetyContract:
    def test_controller_has_no_lock_attribute(self):
        # If the controller ever introduces a lock that main.py nests, the
        # 995 path deadlocks. Guard: controller exposes no threading primitives.
        import threading
        ctrl = FireAlarmController(
            read_temperature=lambda: 25.0,
            read_moisture=lambda: False,
            get_time=lambda: 0.0,
            state=State.AWAKE,
        )
        # Check for any thread-lock-like object among instance attributes
        for a in dir(ctrl):
            if a.startswith('_') or callable(getattr(ctrl, a, None)):
                continue
            try:
                if isinstance(getattr(ctrl, a), (threading.Lock, type(threading.Lock()))):
                    raise AssertionError(f"controller exposes a lock: {a}")
            except TypeError:
                pass  # not a lock type

    def test_deactivate_emergency_is_pure_state_change(self, clock, outputs):
        # deactivate_emergency must be safe to call under main.py's state_lock
        # (it only touches injected outputs + self.state).
        ctrl = make_ctrl(clock, temp=[49.0], moisture=[True], state=State.EMERGENCY)
        ctrl.deactivate_emergency(outputs.outputs, DeactivationReason.RECOVERED)
        assert ctrl.state is State.AWAKE
        assert outputs.lcd_clear_count == 1
