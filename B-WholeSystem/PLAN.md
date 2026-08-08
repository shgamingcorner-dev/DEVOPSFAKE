# Whole System Implementation Plan — Smart Fire Alert

> Companion to the master SRS plan. This is the plan for the **complete** system
> (folder B), assuming the recovery + false-alarm slice (folder A) is already done.

**Goal:** Ship the full Smart Fire Alert System matching every SRS requirement,
verified end-to-end.

**Architecture:** State machine (`Sleep → Awake → Emergency → Awake`) on Raspberry Pi
+ Python HAL (RPi.GPIO), threaded (keypad / monitor / telegram), calling
Telegram + ThingSpeak **directly** via `requests` (no relay server).

---

## Current state (validated)

- `fire_alarm.py` (recovery + false alarm) done + 20 tests green.
- `main.py` whole-system skeleton written (states, sensors, outputs, `requests` hooks).
- HAL submodule present (`hal/`, RPi.GPIO modules).
- **Not yet verified on hardware** — calibration values are placeholders.

---

## Phases

### Phase 1 — Hardware bring-up (1–2 h)
- [ ] Init HAL on Pi; smoke-test each sensor read (temp, moisture, LDR, keypad).
- [ ] Calibrate: `LDR_SMOKE_THRESHOLD`, moisture wet/dry cut-off, DHT11 tolerance at 50/60 °C.
- [ ] Confirm GPIO wiring matches HAL (keypad GPIO6/20/19/13 + 12/5/16; moisture GPIO4;
      temp GPIO21; buzzer GPIO18; LED GPIO24; servo GPIO26; slide GPIO22).

### Phase 2 — State machine integration (1–2 h)
- [ ] Wire `enter_emergency()` (SRS 2.3.3) into monitor + telegram threads.
- [ ] Wire recovery + false alarm (already done in `fire_alarm.py`) via `deactivate_via_controller`.
- [ ] Sleep→Awake via slide switch; LCD "System ready :)".
- [ ] Threads: keypad, monitor, telegram; main loop state handling.

### Phase 3 — Cloud integration (1–2 h)
- [ ] Fill in Telegram Bot token + chat id + ThingSpeak API key in `main.py`.
- [ ] `curl`-style test: `requests.post(...)` to Telegram + ThingSpeak from the Pi
      (user's preferred verification).
- [ ] Confirm `requests` installed on the Pi.

### Phase 4 — Verification (1–2 h)
- [ ] `pytest test_fire_alarm.py -v` → 20 passed.
- [ ] Hardware-in-loop: fire sim (heat/LDR) → buzzer/LED/servo/LCD/Telegram;
      recovery (cool + water 5 s) → deactivate + "Fire is out";
      false alarm (keypad 123) → "False alarm!".
- [ ] ThingSpeak: 15 s uploads visible.
- [ ] Fill System Test Report xlsx (REQ → test → result).

### Phase 5 — Docs + polish (1 h)
- [ ] Traceability matrix REQ ↔ code ↔ test.
- [ ] README calibration values + wiring table.
- [ ] Commit (user gates commits) + push to DEVOPSFAKE.

---

## Files
- `main.py` — whole-system app
- `fire_alarm.py` + `test_fire_alarm.py` — exit paths (done)
- `hal/` — HAL modules
- `relay/` (deploy) — Flask relay for Telegram/ThingSpeak

## Risks
1. **DHT11 accuracy at 60 °C** — consider NTC/thermistor for the auto-fire threshold.
2. **LDR "significant reduction" undefined** — calibrate ADC drop; document chosen value.
3. **Moisture sensor bool semantics** — verify GPIO4 wiring; may need analog variant.
4. **HAL submodule** — already initialized locally; confirm Pi has RPi.GPIO + spidev + smbus.
5. **Relay deployment** — PythonAnywhere free tier: no Env Vars UI, manual reload
   (user's documented workarounds apply).

## Est. time: **~6–9 h** (hardware + integration + relay + verification)
## Confidence: **~70%** (hardware calibration + relay live-test are the swing factors)
