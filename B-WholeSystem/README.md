# Smart Fire Alert System — Whole System

Full implementation of the Smart Fire Alert System per the SRS
(`SRS_project_xxx.docx`). Detects fire hazards for elderly living alone,
activates safety devices, notifies via Telegram, and logs to ThingSpeak.

## State machine (from SRS)

```
Sleep ──(slide switch right)──> Awake
Awake ──(auto: temp>=60C OR LDR smoke)──> Emergency
Awake ──(Telegram "995")──> Emergency              (manual)
Emergency ──(temp<50C AND moisture, 5s)──> Awake   (auto recovery)
Emergency ──(keypad "123")──> Awake                (false alarm)
```

## What's here

| File | Purpose |
|---|---|
| `main.py` | Threaded whole-system app (states, sensors, outputs, relay hooks) |
| `fire_alarm.py` | Recovery + false-alarm logic (shared with folder A) |
| `test_fire_alarm.py` | 20 tests for the exit paths |
| `hal/` | Hardware Abstraction Layer (RPi.GPIO) |
| `PLAN.md` | Implementation plan for the whole system |

## SRS coverage

- REQ-01/02: Sleep→Awake via slide switch; LCD "System ready :)"
- REQ-03: Auto-activation — temp ≥ 60 °C OR LDR smoke (ADC drop)
- REQ-04: Manual activation — Telegram "995"
- REQ-06/07/0?: Emergency — buzzer, "Fire detected!" Telegram, red LED
- REQ-0?: Servo sprinkler; LCD "FIRE DETECTED!" / "EVACUATE NOW"
- 2.3.4: Recovery — temp < 50 °C + moisture ≥ 5 s → deactivate, "Fire is out"
- 2.3.5: False alarm — keypad "123" → deactivate, "False alarm!" / "Alarm deactivated"
- 2.3.6 + 2.4.2: ThingSpeak upload every 15 s

## Threads

- **keypad_thread** — keypad scanner → key queue
- **monitor_thread** — sensor polling (temp/LDR/moisture), auto-detection, auto-recovery, ThingSpeak uploads
- **telegram_thread** — polls relay for "995" manual command
- **main loop** — state transitions + keypad handling

## Deploy / run

1. Raspberry Pi with HAL modules in `hal/`.
2. Install deps: `pip install RPi.GPIO spidev smbus requests`
3. Fill in real credentials in `main.py`:
   - `TELEGRAM_BOT_TOKEN` (from @BotFather)
   - `TELEGRAM_CHAT_ID`
   - `THINGSPEAK_API_KEY`
4. Run:

```bash
python main.py
```

Telegram + ThingSpeak are called **directly from the Pi** via `requests`
(no relay server needed).

## Calibration needed (before grading)

- **LDR smoke threshold** (`LDR_SMOKE_THRESHOLD`): ADC value where smoke blocks light.
- **Moisture "wet" cut-off**: `hal_moisture_sensor.read_sensor()` is bool (GPIO4 high);
  verify wiring / polarity.
- **DHT11 at 50/60 °C**: ±2 °C accuracy — consider a thermistor/NTC for reliable
  fire detection at 60 °C.
