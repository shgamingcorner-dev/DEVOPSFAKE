# Smart Fire Alert System — Whole System (B)

A complete implementation of the **Smart Fire Alert System** per the
Software Requirements Specification (`SRS_project_GRPPRJ.docx`). The system
detects potential fire hazards for elderly individuals living alone,
activates safety devices, sends emergency notifications via **Telegram**, and
uploads sensor readings to **ThingSpeak** for remote monitoring.

---

## 1. System Requirements

### 1.1 Functional Requirements

| ID | Requirement |
|---|---|
| REQ-01 | The system shall remain in the **Sleep State** until the slide switch is slid to the right; it shall then transition to the **Awake State**. |
| REQ-02 | When in the **Awake State**, the LCD shall display `System ready :)`. |
| REQ-03 | **Automatic activation:** the system shall activate the Emergency Response when the temperature sensor detects **≥ 60 °C** OR the LDR detects a significant reduction in light (smoke obstruction). |
| REQ-04 | **Manual activation:** the system shall activate the Emergency Response upon receiving the `995` command from the Telegram chat. |
| REQ-06 | Upon entering the Emergency state, the system shall activate the **buzzer**. |
| REQ-07 | The system shall send a simulated emergency notification, `Fire detected!`, via Telegram to the **house owner, caregiver and SCDF**. |
| REQ-08 | The system shall turn on the **red LED** to provide a visual indication of the emergency. |
| REQ-09 | The system shall activate the **servo motor** to operate as a **water sprinkler**. |
| REQ-10 | The LCD shall display `FIRE DETECTED!` (line 1) and `EVACUATE NOW` (line 2). |
| REQ-11 | The system shall transition to Awake only when the temperature is **below 50 °C** AND the moisture sensor detects water (sprinkler active). |
| REQ-12 | Upon recovery, the system shall deactivate the buzzer, red LED and servo. |
| REQ-13 | The LCD shall display `Fire is out`. |
| REQ-14 | In the event of a false alarm, the user shall enter the code **`123`** on the keypad to deactivate the Emergency state. |
| REQ-15 | Once the code is entered, the system shall deactivate the buzzer, red LED and servo, and transition to Awake. |
| REQ-16 | The LCD shall display `False alarm!` (line 1) and `Alarm deactivated` (line 2). |
| REQ-17 | Upon deactivation, the system shall upload the **alarm duration and recorded temperature** to ThingSpeak. |

### 1.2 Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-01 | System startup shall complete within **2 seconds**. |
| NFR-02 | The sprinkler shall activate within **3 seconds** of the alarm. |
| NFR-03 | The LCD display shall update within **1 second** of an alarm event. |
| NFR-04 | The LED indicator shall update within **1 second** of an alarm event. |
| NFR-05 | The Telegram notification shall be sent within **5 seconds** of the alarm. |
| NFR-06 | Fire is considered extinguished only when **both** conditions (temp < 50 °C + moisture) hold **continuously for ≥ 5 seconds**. |
| NFR-07 | Upon detecting fire is extinguished, the alarm shall deactivate within **3 seconds**. |
| NFR-08 | Sensor readings shall be uploaded to ThingSpeak **every 15 seconds**. |

---

## 2. UML Diagrams

### 2.1 Use Case Diagram

```
             +---------------------------------------------+
             |              Smart Fire Alert System        |
             +---------------------------------------------+
   Owner/     |  (detect fire)  (activate devices)  (upload) |
   Caregiver  |        ^                |              ^     |
   / SCDF     |        |                v              |     |
    (995) ----+--> [manual activation]  |         [ThingSpeak]|
    (alert)-- |<-- [Telegram alert]     |              |     |
             |        |                v              |     |
   Elderly    |  (slide switch)  [buzzer/LED/servo]    |     |
    user -----+--> [Sleep -> Awake]    |              |     |
    (123) ----+--> [false alarm] ------+--------------+-----+
             +---------------------------------------------+
```

### 2.2 State Machine Diagram

```
                  +--------+
   power on       | Sleep  |
    +------------>|        |
    |             +--------+
    |               |  slide switch right
    |               v
    |             +--------+     temp >= 60 C OR LDR smoke     +------------+
    |             | Awake  | ---------------------------------> | Emergency  |
    |             |        |     Telegram "995"                |            |
    |             +--------+ ---------------------------------> |            |
    |               |                                          +------------+
    |               |  slide switch left                         |     |     |
    |               |          temp < 50 C AND moisture (5 s)    |     |     |
    |               v          keypad "123" (false alarm)        |     |     |
    |             +--------+ <-----------------------------------+     |     |
    +-------------| Sleep  | <-----------------------------------------+     |
                  +--------+                                                  |
```

---

## 3. Software Architecture

### 3.1 Architecture Diagram

```
                        Raspberry Pi
   +---------------------------------------------------------------+
   |  Application Layer                                            |
   |   main.py  fire_alarm.py  emergency_response.py  telegram_bot.py |
   |      |          |              |                   |           |
   |      +----------+--------------+-------------------+           |
   |                    | (HAL API calls)                           |
   |  Hardware Abstraction Layer (hal/)                             |
   |   temp  adc  moisture  keypad  switch  buzzer  led  servo  lcd |
   |      |     |     |       |       |      |     |    |     |     |
   |  Sensors & Actuators                                          |
   |   DHT11 LDR  moisture  keypad  switch  buzzer  LED  servo  LCD |
   +---------------------------------------------------------------+
        |                                       |
        v                                       v
   Telegram Bot API                    ThingSpeak API
   (alerts / 995)                      (sensor logs)
```

### 3.2 Architecture Description

The software follows a **layered architecture** with a clear separation of concerns:

| Layer | Components | Responsibility |
|---|---|---|
| **Application Layer** | `main.py`, `fire_alarm.py`, `emergency_response.py`, `telegram_bot.py` | Orchestrates the state machine, threading, emergency actions, and cloud integration. Pure logic lives in `fire_alarm.py` (unit-testable without hardware). |
| **Hardware Abstraction Layer (HAL)** | `hal/hal_*.py` | Wraps RPi.GPIO / I2C / SPI access behind simple `init()` + read/write functions. Keeps hardware details out of the application logic. |
| **Cloud Interfaces** | Telegram Bot API, ThingSpeak API | Outbound HTTPS calls via the `requests` library. Credentials come from `.env`. |

**Threading model** (concurrency required by the SRS):

| Thread | Role |
|---|---|
| `keypad_thread` | Scans the keypad → puts key presses into a shared queue |
| `monitor_thread` | Polls temp / LDR / moisture; drives auto-detection, auto-recovery and the 15 s ThingSpeak upload |
| `telegram_thread` | Polls Telegram for the `995` manual command |
| `main loop` | Applies state transitions, slide-switch toggle, keypad "123" handling and LCD feedback |

Thread safety is ensured with a shared `state_lock`, a lock around the DHT11
read (GPIO pin-mode race), and a mutex around LCD writes (I2C bus corruption).

---

## 4. Usage

### 4.1 Prerequisites

- Raspberry Pi (32-bit ARM) with the sensor/actuator kit connected
- Python 3.7+
- A Telegram bot token (via @BotFather) and a ThingSpeak channel API key

### 4.2 Setup

```bash
# 1. Clone / pull the repo
git clone https://github.com/shgamingcorner-dev/DEVOPSFAKE.git
cd DEVOPSFAKE/B-WholeSystem

# 2. Install dependencies
pip3 install -r requirements.txt
#   (RPi.GPIO, spidev, smbus, requests, python-dotenv)

# 3. Create .env from the template (fill in REAL credentials - never commit)
cp .env.example .env
nano .env
#   TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_CHAT_ID,
#   TELEGRAM_CAREGIVER_CHAT_ID, TELEGRAM_SCDF_CHAT_ID, THINGSPEAK_API_KEY

# 4. Run
sudo python3 main.py
```

### 4.3 Testing the scenarios

| Scenario | Action | Expected result |
|---|---|---|
| Startup | `sudo python3 main.py` | LCD shows `System asleep` |
| Sleep → Awake | Slide switch right | LCD shows `System ready :)` |
| Auto-activation | Heat temp ≥ 60 °C OR cover the LDR | Buzzer + red LED + servo + LCD `FIRE DETECTED!` + Telegram alert |
| Manual activation | Text `995` to the bot | Same emergency response |
| Recovery | Cool < 50 °C AND wet moisture sensor for 5 s | Deactivates; LCD `Fire is out`; Telegram `Fire is out - alarm resolved.` |
| False alarm | Press `1 2 3` on the keypad | Deactivates; LCD `False alarm!` / `Alarm deactivated`; Telegram status |
| Monitoring | Wait ~15 s | ThingSpeak channel gets sensor readings (field1 temp, field2 LDR, field3 moisture) |

### 4.4 Running the tests

```bash
# Unit tests (logic - no hardware needed)
PYTHONPATH=. python3 -m pytest test_fire_alarm.py -v

# Hardware walkthrough (on the Pi, interactive)
sudo python3 test_hardware.py
```

---

## 5. Calibration notes

- **LDR smoke threshold** (`LDR_SMOKE_THRESHOLD` in `main.py`): the ADC value
  below which the sensor is considered smoke-covered. Calibrate to your room.
- **DHT11 accuracy** (±2 °C): at the 50/60 °C fire boundaries, consider a
  thermistor for reliable detection.
- **Moisture polarity**: `hal_moisture_sensor.read_sensor()` returns True when
  GPIO4 is HIGH — verify against your wiring.

---

## 6. Docker and Kubernetes

This project can also be **containerised with Docker** and run under
**Kubernetes (k3s)** on the Raspberry Pi.

### 6.1 What Docker does

Docker packages the application (code + Python libraries + settings) into a
single **image** that can be built and run on any machine with Docker —
including the Raspberry Pi. A `Dockerfile` in this folder defines the image:

| Line | What it does |
|---|---|
| `FROM arm32v7/python:3.7-slim-buster` | Start from a Python 3.7 image built for the Pi's ARM processor |
| `WORKDIR /app` | Set the working folder inside the container |
| `COPY requirements.txt .` | Copy the dependency list |
| `RUN pip3 install -r requirements.txt` | Install the Python libraries |
| `COPY main.py ... ./` | Copy the application code |
| `COPY hal/ ./hal/` | Copy the hardware layer |
| `CMD ["python3", "main.py"]` | Run the app when the container starts |

**How it works:** when the image is *built*, Docker runs each `COPY` / `RUN`
step to assemble a self-contained snapshot of the app. When the image is
*run* as a **container**, the app starts inside an isolated environment with
its own filesystem and Python — identical on any Pi.

**Why it matters:** it makes the app **portable** (runs identically on any
Pi) and **isolated** (the container's files and libraries do not clash with
the host OS). Because this app talks to the Pi's hardware (GPIO / I2C for
the sensors, buzzer, LCD, servo), the container is run with privileged
hardware access.

### 6.2 What Kubernetes does

Kubernetes (K8s) **manages containers at scale** — it starts, restarts,
scales and exposes containers (called **Pods**) automatically. On the Pi we
use **k3s**, a lightweight Kubernetes distribution built for small devices.

**How it works:** you describe what you want in a manifest file, and
Kubernetes makes it happen:

| Object | Purpose |
|---|---|
| `Deployment` | Tells Kubernetes to run a number of replicas of a container and keep them running (restarts them if they crash) |
| `Service` | Exposes the Pods on a network port so other machines can reach them |

**Why it matters:** it shows the app can be deployed like a real production
service — the Deployment describes the desired state, and Kubernetes
continuously works to keep the system in that state (self-healing, scaling,
rolling updates).

---

## 7. File reference

| File | Purpose |
|---|---|
| `main.py` | Threaded whole-system app (states, sensors, outputs) |
| `fire_alarm.py` | Recovery + false-alarm logic |
| `emergency_response.py` | Emergency response actions (buzzer/LED/servo/LCD/Telegram) |
| `telegram_bot.py` | Telegram integration (REQ-07 alerts, REQ-04 '995') |
| `test_fire_alarm.py` | Unit tests (pytest) |
| `test_hardware.py` | Hardware walkthrough script (SRS-driven) |
| `hal/` | Hardware Abstraction Layer (RPi.GPIO) |
| `Dockerfile` | Defines the Docker image |
| `docker-compose.yml` | One-command Docker run (privileged + .env) |
| `k8s/` | Kubernetes manifests (Deployment + Service) |
| `requirements.txt` | Python dependencies |
| `.env.example` | Template for credentials (never commit `.env`) |
