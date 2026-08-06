# Smart Fire Alert — My Parts (System Recovery + False Alarm)

This folder contains **my delegated slice** of the Smart Fire Alert System
(SRS 2.3.4 System Recovery + 2.3.5 False Alarm) — the two **Emergency → Awake**
exit paths.

## What's here

| File | Purpose |
|---|---|
| `fire_alarm.py` | Pure-logic controller: `monitor_once()` (5 s debounce auto-recovery), `key_pressed()` ("123" sequence), `deactivate_emergency(reason)` |
| `test_fire_alarm.py` | 20 pytest tests (state transitions, thresholds, debounce, keypad sequence) |
| `main.py` | Threaded demo: keypad thread + sensor-monitor thread, Emergency entry stub |
| `hal/` | Hardware Abstraction Layer (RPi.GPIO modules) |

## SRS requirements covered

| SRS ID | Requirement | Where |
|---|---|---|
| 2.3.4 | Auto-recovery: temp < 50 °C AND moisture present, sustained ≥ 5 s | `fire_alarm.monitor_once()` |
| 2.3.4 | Deactivate buzzer / red LED / servo on recovery | `deactivate_emergency('recovered')` |
| 2.3.4 | LCD shows "Fire is out" | `LCD_RECOVERED_LINE1` |
| 2.3.5 | Keypad '123' deactivates Emergency | `key_pressed()` → `[1,2,3]` |
| 2.3.5 | Deactivate buzzer / red LED / servo; LCD "False alarm!" / "Alarm deactivated" | `deactivate_emergency('false_alarm')` |
| NFR | Extinguished only when conditions hold continuously ≥ 5 s | `RECOVERY_MIN_SECONDS = 5.0` |

## Threads

- **keypad_thread** — HAL keypad scanner → key queue (existing repo pattern)
- **monitor_thread** — polls temp + moisture every 1 s while in Emergency; drives 5 s debounce and auto-recovery
- **main loop** — applies state transitions

## Run tests (no hardware needed)

```bash
# from repo root
python -m venv .venv
.venv/Scripts/python -m pip install pytest
PYTHONPATH=. .venv/Scripts/python -m pytest test_fire_alarm.py -v
```

Expected: **20 passed**.

## Hardware run (Raspberry Pi)

```bash
python main.py
```

In this folder the Emergency *entry* is a stub (any key enters Emergency) so the
recovery + false alarm paths can be demoed standalone. The real entry logic
(SRS 2.3.3) lives in the whole-system folder (B) or the teammate's slice.

## Integration contract

Shared with the teammate owning Emergency entry (SRS 2.3.3):

- `FireAlarmController(read_temperature, read_moisture, get_time, state)`
- `monitor_once() -> bool` — True when fire considered extinguished
- `key_pressed(key) -> bool` — True when '123' entered
- `deactivate_emergency(outputs, reason)` — the single owner of buzzer/LED/servo off-state

**Pitfall:** both the entry and exit slices touch the same outputs; the
deactivation helper must be the only code that turns buzzer/LED/servo off.
