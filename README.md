# DEVOPSFAKE — Smart Fire Alert System

Two independent folders for the Smart Fire Alert System (SRS-based):

```
DEVOPSFAKE/
├── A-MyParts/        # My delegated slice: System Recovery + False Alarm (SRS 2.3.4/2.3.5)
│   ├── fire_alarm.py        # recovery + false-alarm logic (20 tests)
│   ├── test_fire_alarm.py
│   ├── main.py              # threaded demo (keypad + monitor threads)
│   ├── hal/                 # RPi.GPIO HAL modules
│   └── README.md
└── B-WholeSystem/    # Complete Smart Fire Alert System (full SRS)
    ├── main.py              # threaded whole-system app
    ├── fire_alarm.py        # shared exit logic
    ├── test_fire_alarm.py
    ├── hal/
    ├── README.md
    └── PLAN.md              # whole-system implementation plan
```

## Quick start

**My parts (recovery + false alarm) — run tests (no hardware):**
```bash
cd A-MyParts
python -m venv .venv
.venv/Scripts/python -m pip install pytest
PYTHONPATH=. .venv/Scripts/python -m pytest test_fire_alarm.py -v   # 20 passed
```

**Whole system** — see `B-WholeSystem/README.md` (needs Raspberry Pi + relay).

## Hardware
Raspberry Pi + Python HAL (RPi.GPIO). See `B-WholeSystem/README.md` for wiring
and calibration notes.
