from machine import Pin
from time import sleep

buzzer = Pin(22, Pin.OUT)
pin = Pin("LED", Pin.OUT)

while True:

    try:
       
        # This snippit of code turns everything on, the buzzer and the light and then waits for 0.8 secs
        buzzer.value(1)
        pin.toggle()
        sleep(0.8)
        
        # This snippit of code turns everything off, the buzzer and the light and waits for 0.8 secs until it loops
        buzzer.value(0)
        pin.toggle()
        sleep(0.8)
    
    # This is a keyboard interrupt that helps break the loop when ctr-c because the pi kept the buzzer on even after I killed the program.
    except KeyboardInterrupt:
        break
buzzer.value(0)
pin.off()
print("IM DONE!!!)")