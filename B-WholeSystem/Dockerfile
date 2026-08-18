# ============================================================
# Smart Fire Alert - Dockerfile for Raspberry Pi (ET0735 Lab 8 style)
# ============================================================
# NOTE: If your Pi is 64-bit (uname -m -> aarch64), change the base image
#       to: arm64v8/python:3.7-slim-bullseye
# The teacher's Lab 8 uses arm32v7 for the 32-bit Pi (armv7l).
# ============================================================

# 1) Python interpreter built for the Pi's ARM CPU (NOT x86)
FROM arm32v7/python:3.7-slim-buster

# 2) Working directory inside the container
WORKDIR /app

# 3) Copy the dependency list first (Docker caches this layer)
COPY requirements.txt .

# 4) Install Python libraries. The --trusted-host flags fix the "SSL Cert
#    Failed" error seen when building on the Pi (see teacher's Lab 8 p.4).
RUN pip3 install --no-cache-dir \
    --trusted-host pypi.org \
    --trusted-host pypi.python.org \
    --trusted-host files.pythonhosted.org \
    -r requirements.txt

# 5) Copy the application code + HAL
COPY main.py fire_alarm.py emergency_response.py telegram_bot.py ./
COPY hal/ ./hal/

# 6) Make Python output visible in docker logs
ENV PYTHONUNBUFFERED=1

# 7) Command to run when the container starts
CMD ["python3", "main.py"]
