import time
import threading

import RPi.GPIO as GPIO

from . import dht11

# DHT11 is NOT thread-safe: read() toggles the pin between OUTPUT (start
# signal) and INPUT (data). Two threads reading at once races the pin mode
# and crashes with "GPIO channel has not been set up as an OUTPUT". Serialize
# all reads with a lock.
_read_lock = threading.Lock()

def init():
    GPIO.setmode(GPIO.BCM)
    global dht11_inst

    dht11_inst = dht11.DHT11(pin=21)  # read data using pin 21

def read_temp_humidity():

    global dht11_inst

    ret = [-100, -100]

    with _read_lock:  # serialize DHT11 access across threads
        result = dht11_inst.read()

    if result.is_valid():
        #print("Temperature: %-3.1f C" % result.temperature)
        #print("Humidity: %-3.1f %%" % result.humidity)

        ret[0] = result.temperature
        ret[1] = result.humidity

    return ret

