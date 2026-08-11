import RPi.GPIO as GPIO
from time import sleep

# One PWM instance per program run. Creating a new GPIO.PWM on the same
# channel every call raises "RuntimeError: PWM already in use" after the
# first use, so init() creates it once and set_servo_position() reuses it.
_pwm = None


def init():
    GPIO.setmode(GPIO.BCM)  # choose BCM mode
    GPIO.setwarnings(False)
    GPIO.setup(26, GPIO.OUT)  # set GPIO 26 as output
    global _pwm
    _pwm = GPIO.PWM(26, 50)  # 50Hz PWM output at GPIO26 (created once)
    _pwm.start(0)            # start at 0% duty so the pin is idle


# position [0 deg to 180 deg]
def set_servo_position(position):
    global _pwm
    if _pwm is None:
        init()

    position = (-10 * position) / 180 + 12

    print("position = " + str(position))

    _pwm.ChangeDutyCycle(position)
    sleep(0.05)
