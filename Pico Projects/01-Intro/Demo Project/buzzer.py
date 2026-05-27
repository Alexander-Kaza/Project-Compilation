from machine import Pin
from time import sleep

buzzer = Pin(22, Pin.OUT)

while True:
    buzzer.value(1)
    sleep(0.2)
    buzzer.value(0)
    sleep(0.8)