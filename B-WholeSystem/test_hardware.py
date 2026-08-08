#!/usr/bin/env python3
"""
test_hardware.py — Smart Fire Alert hardware verification (SRS-driven)

Runs on the Raspberry Pi to prove each SRS requirement on real hardware.
It walks you through physical scenarios and records PASS/FAIL — use the
printed summary as evidence for the System Test Report.

Usage (on the Pi):
    cd B-WholeSystem
    cp .env.example .env          # fill in real Telegram / ThingSpeak keys
    sudo python3 test_hardware.py

Optional dev mode (Windows, no hardware) — checks the script flow only:
    python test_hardware.py --dry-run

SRS coverage map:
  1. Startup + LCD          REQ-01, REQ-02           (SRS 2.3.1)
  2. Live sensor reads      temp / LDR / moisture    (SRS 2.3.4 monitoring)
  3. Auto activation        REQ-03                   (SRS 2.3.2)
  4. Emergency response     REQ-06, REQ-07, ...      (SRS 2.3.3)
  5. Recovery               SRS 2.3.4 (incl. 5 s debounce NFR)
  6. False alarm            SRS 2.3.5 (keypad '123')
  7. Manual activation      REQ-04 (Telegram '995')
  8. ThingSpeak logging     SRS 2.3.6 / 2.4.2
"""

import queue
import sys
import threading
import time

DRY_RUN = "--dry-run" in sys.argv


# --------------------------------------------------------------------------
# Dry-run stubs (only used with --dry-run on a machine without RPi.GPIO)
# --------------------------------------------------------------------------
def _install_stubs():
    """Fake hal + requests modules so the script flow can be checked."""
    import types
    sensor = {"temp": 49.0, "humidity": 50.0, "ldr": 900, "moisture": True, "slide": 1}

    hal_pkg = types.ModuleType("hal")
    sys.modules["hal"] = hal_pkg

    def make(name, funcs):
        m = types.ModuleType("hal." + name)
        for k, v in funcs.items():
            setattr(m, k, v)
        sys.modules["hal." + name] = m
        setattr(hal_pkg, name, m)

    class LcdStub:
        def lcd_clear(self):
            print("  [lcd] cleared")

        def lcd_display_string(self, s, line=1, pos=0):
            print(f"  [lcd] line{line}: {s}")

        def backlight(self, state):
            pass

    make("hal_led", {"init": lambda: None, "set_output": lambda l, lvl: print(f"  [led] {l} -> {lvl}")})
    make("hal_lcd", {"lcd": lambda: LcdStub()})
    make("hal_adc", {"init": lambda: None, "get_adc_value": lambda ch: sensor["ldr"]})
    make("hal_buzzer", {"init": lambda: None, "turn_on": lambda: print("  [buzzer] ON"),
                        "turn_off": lambda: print("  [buzzer] OFF"),
                        "turn_on_with_timer": lambda d: None, "beep": lambda a, b, c: None})
    make("hal_keypad", {"init": lambda cbk: None, "get_key": lambda: None})
    make("hal_moisture_sensor", {"init": lambda: None, "read_sensor": lambda: sensor["moisture"]})
    make("hal_input_switch", {"init": lambda: None, "read_slide_switch": lambda: sensor["slide"]})
    make("hal_servo", {"init": lambda: None, "set_servo_position": lambda p: print(f"  [servo] -> {p}")})
    make("hal_temp_humidity_sensor", {
        "init": lambda: None,
        "read_temp_humidity": lambda: (sensor["temp"], sensor["humidity"]),
    })

    req = types.ModuleType("requests")
    req.post = lambda url, json=None, data=None, timeout=None: print(f"  [http POST] {url}")
    req.get = lambda url, timeout=None: type("R", (), {"json": lambda self: {"result": [{"message": {"text": "995"}}]}})()
    sys.modules["requests"] = req


# --------------------------------------------------------------------------
# Guard + import the real system (reuses main.py functions)
# --------------------------------------------------------------------------
if DRY_RUN:
    _install_stubs()
else:
    try:
        import RPi.GPIO  # noqa: F401
    except ImportError:
        print("This script must run on the Raspberry Pi (RPi.GPIO required).")
        print("Use --dry-run only to preview the flow on a dev machine.")
        sys.exit(1)

try:
    import main as app   # the real Smart Fire Alert system
except Exception as e:
    print("Could not import main.py:", e)
    sys.exit(1)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
results = []          # (srs_id, name, passed)
ask_default = "y" if DRY_RUN else None


def ask(question):
    """Ask a y/n question (auto-answers 'y' in dry-run)."""
    if ask_default is not None:
        print(f"{question} [y/n] -> (auto {ask_default})")
        return True
    while True:
        ans = input(f"{question} [y/n] ").strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("  Please answer y or n.")


def record(srs_id, name, passed):
    results.append((srs_id, name, bool(passed)))
    print(f"  -> {'PASS' if passed else 'FAIL'}  [{srs_id}] {name}")


def pause(msg="Press Enter to continue..."):
    if ask_default is not None:
        print(f"[pause] {msg} (auto)")
        return
    input(msg)


def banner(title):
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)


def wait_for_state(target, timeout, note=""):
    """
    Poll controller.state until it equals `target` (or timeout).
    Returns elapsed seconds, or None on timeout.
    """
    print(f"  waiting for state -> {target.name} {note} (timeout {timeout}s)")
    if DRY_RUN:
        time.sleep(1)
        app.controller.state = target
        return 1.0
    start = time.time()
    while time.time() - start < timeout:
        with app.state_lock:
            st = app.controller.state
        if st is target:
            return time.time() - start
        time.sleep(0.2)
    return None


def live_sensor_summary():
    temp, hum = app.temp_humid_sensor.read_temp_humidity()
    ldr = app.adc.get_adc_value(0)
    moist = app.moisture_sensor.read_sensor()
    print(f"  live: temp={temp} C  humidity={hum}%  LDR(ADC)={ldr}  moisture={moist}")
    return temp, ldr, moist


def setup_system():
    """Init HAL + controller + threads the same way main() does."""
    print("\nInitialising hardware...")
    app.led.init()
    app.adc.init()
    app.buzzer.init()
    app.moisture_sensor.init()
    app.input_switch.init()
    app.servo.init()
    app.temp_humid_sensor.init()

    app.lcd = app.LCD.lcd()
    app.lcd.lcd_clear()

    app.controller = app.FireAlarmController(
        read_temperature=lambda: app.temp_humid_sensor.read_temp_humidity()[0],
        read_moisture=app.moisture_sensor.read_sensor,
        get_time=time.time,
        state=app.State.AWAKE,
    )

    app.keypad.init(app.key_pressed)
    threading.Thread(target=app.keypad_thread_fn, daemon=True).start()
    threading.Thread(target=app.monitor_thread_fn, daemon=True).start()
    threading.Thread(target=app.telegram_thread_fn, daemon=True).start()

    # warn about placeholder keys
    if app.TELEGRAM_BOT_TOKEN in ("", "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"):
        print("WARNING: TELEGRAM_BOT_TOKEN looks unset/placeholder — edit B-WholeSystem/.env")
    if app.THINGSPEAK_API_KEY in ("", "XXXXXXXXXXXXXXXX"):
        print("WARNING: THINGSPEAK_API_KEY looks unset/placeholder — edit B-WholeSystem/.env")


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
def test_01_startup_lcd():
    banner("1. System startup + LCD (SRS 2.3.1 — REQ-01/02)")
    print("  Slide the switch to the RIGHT (Awake).")
    pause("  ...slide it now, then press Enter")
    on = app.input_switch.read_slide_switch()
    record("REQ-01", "Slide switch right puts system in Awake", on == 1)

    app.lcd.lcd_clear()
    app.lcd.lcd_display_string("System ready :)", 1)
    record("REQ-02", 'LCD shows "System ready :)"', ask("  Is 'System ready :)' on the LCD?"))


def test_02_sensor_reads():
    banner("2. Live sensor reads (SRS 2.3.4 continuous monitoring)")
    temp, ldr, moist = live_sensor_summary()
    record("2.3.4", "Temperature sensor reads a sensible value", -100 < temp < 100)
    record("2.3.4", "Moisture sensor reads present/absent", isinstance(moist, bool))
    print("  Now COVER the LDR with your hand (simulate smoke).")
    pause("  ...cover it, then press Enter")
    ldr_covered = app.adc.get_adc_value(0)
    print(f"  LDR open={ldr}  covered={ldr_covered}")
    record("REQ-03", "LDR value drops when covered", ldr_covered < ldr)


def test_03_auto_activation():
    banner("3. Auto activation (SRS 2.3.2 — REQ-03)")
    print("  Trigger the fire: heat the temp sensor above 60 C, OR cover the LDR.")
    pause("  ...trigger it now, then press Enter")
    elapsed = wait_for_state(app.State.EMERGENCY, timeout=30, note="(auto fire detection)")
    record("REQ-03", "System enters Emergency automatically (temp>=60C or LDR smoke)",
           elapsed is not None)
    if elapsed is None:
        print("  Not detected in 30s — check sensor wiring / thresholds.")


def test_04_emergency_response():
    banner("4. Emergency response (SRS 2.3.3)")
    with app.state_lock:
        if app.controller.state is not app.State.EMERGENCY:
            print("  System not in Emergency — activating directly for this test.")
            app.activate_emergency()
    record("REQ-06", "Buzzer is sounding", ask("  Is the buzzer sounding?"))
    record("REQ-07", "Telegram 'Fire detected!' received", ask("  Did 'Fire detected!' arrive on Telegram?"))
    record("REQ-0?", "Red LED is on", ask("  Is the red LED on?"))
    record("REQ-0?", "Servo sprinkler is moving", ask("  Is the servo (sprinkler) moving?"))
    record("REQ-0?", "LCD shows 'FIRE DETECTED!' / 'EVACUATE NOW'",
           ask("  Does the LCD show FIRE DETECTED! / EVACUATE NOW?"))


def test_05_recovery():
    banner("5. System recovery (SRS 2.3.4 — 5 s debounce NFR)")
    print("  Put the fire out: cool the sensor below 50 C AND wet the moisture sensor.")
    print("  (Both conditions must hold for ~5 seconds.)")
    pause("  ...cool + wet it now, then press Enter")
    elapsed = wait_for_state(app.State.AWAKE, timeout=60, note="(auto recovery)")
    record("2.3.4", "System returns to Awake when temp<50C + moisture (5s)", elapsed is not None)
    record("2.3.4", "Buzzer stopped", ask("  Did the buzzer stop?"))
    record("2.3.4", "Red LED off", ask("  Is the red LED off?"))
    record("2.3.4", "Servo (sprinkler) stopped", ask("  Did the servo stop?"))
    record("2.3.4", 'LCD shows "Fire is out"', ask('  Does the LCD show "Fire is out"?'))
    record("NFR-5s", "Recovery took ~5 s after conditions met", ask("  Did deactivation happen ~5 s after cooling/wetting?"))


def test_06_false_alarm():
    banner("6. False alarm (SRS 2.3.5 — keypad '123')")
    with app.state_lock:
        if app.controller.state is not app.State.EMERGENCY:
            print("  Re-trigger the fire (heat/cover LDR) to enter Emergency again.")
            pause("  ...trigger it, then press Enter")
            wait_for_state(app.State.EMERGENCY, timeout=30)
    print("  Now press the keypad sequence: 1, 2, 3")
    pressed = []
    deadline = time.time() + 30
    while len(pressed) < 3 and time.time() < deadline:
        try:
            key = app.key_queue.get(timeout=0.5)
            pressed.append(key)
        except queue.Empty:
            pass
    print(f"  keypad sequence read: {pressed}")
    record("REQ-0?", "Keypad '123' deactivates Emergency", pressed == [1, 2, 3])
    record("2.3.5", 'LCD shows "False alarm!" / "Alarm deactivated"',
           ask('  Does the LCD show "False alarm!" / "Alarm deactivated"?'))
    with app.state_lock:
        record("2.3.5", "System is back to Awake", app.controller.state is app.State.AWAKE)


def test_07_manual_995():
    banner("7. Manual activation via Telegram (SRS 2.3.2 — REQ-04)")
    print("  Make sure the fire source is removed (system should be Awake).")
    pause("  ...press Enter when it is normal")
    with app.state_lock:
        if app.controller.state is app.State.EMERGENCY:
            print("  Still in Emergency — press 1-2-3 on the keypad to clear it first.")
            pause("  ...press Enter when cleared")
    print("  Now send the message '995' to your Telegram bot from your phone.")
    pause("  ...sent it, then press Enter")
    elapsed = wait_for_state(app.State.EMERGENCY, timeout=30, note="(Telegram '995')")
    record("REQ-04", "Telegram '995' activates Emergency", elapsed is not None)


def test_08_thingspeak():
    banner("8. ThingSpeak logging (SRS 2.3.6 / 2.4.2)")
    print("  Uploading sensor readings now (also happens every 15 s automatically)...")
    app.upload_thingspeak()
    record("2.4.2", "ThingSpeak shows a new entry", ask("  Did a new entry appear on your ThingSpeak channel?"))


def cleanup():
    """Make sure nothing is left alarming."""
    print("\nCleaning up...")
    app.buzzer.turn_off()
    app.led.set_output(1, 0)
    app.servo.set_servo_position(0)
    app.lcd.lcd_clear()
    app.lcd.lcd_display_string("Test complete", 1)


def print_summary():
    banner("SUMMARY")
    passed = sum(1 for _, _, p in results if p)
    for srs_id, name, p in results:
        print(f"[{'PASS' if p else 'FAIL'}] [{srs_id}] {name}")
    print(f"\n{passed}/{len(results)} checks passed")
    print("Copy this output into the System Test Report as evidence.")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    print("Smart Fire Alert — hardware verification")
    print("Make sure the Raspberry Pi is wired and the system is powered.")
    setup_system()
    pause("\nPress Enter to start the tests...")

    test_01_startup_lcd()
    test_02_sensor_reads()
    test_03_auto_activation()
    test_04_emergency_response()
    test_05_recovery()
    test_06_false_alarm()
    test_07_manual_995()
    test_08_thingspeak()

    cleanup()
    print_summary()


if __name__ == "__main__":
    main()
