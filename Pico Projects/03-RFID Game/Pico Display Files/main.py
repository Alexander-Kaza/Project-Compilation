from machine import Pin, SPI
from picographics import PicoGraphics, DISPLAY_PICO_DISPLAY, PEN_P4
from minimal_rc522 import MinimalRC522
import time

# --- Display setup ---
display = PicoGraphics(display=DISPLAY_PICO_DISPLAY, pen_type=PEN_P4, rotate=0)
display.set_backlight(0.8)
display.set_font("bitmap8")

WHITE = display.create_pen(255, 255, 255)
BLACK = display.create_pen(0, 0, 0)
GREEN = display.create_pen(0, 255, 0)

def show_text(line1, line2=""):
    display.set_pen(BLACK)
    display.clear()
    display.set_pen(WHITE)
    display.text(line1, 10, 40, 220, 3)
    if line2:
        display.set_pen(GREEN)
        display.text(line2, 10, 80, 220, 2)
    display.update()

show_text("NFC Memory Game", "Scan a tag...")

# --- RC522 setup (SPI1 — SPI0 is claimed by the display) ---
rst = Pin(22, Pin.OUT)
rst.value(1)

spi = SPI(1, baudrate=1_000_000, polarity=0, phase=0,
          sck=Pin(10), mosi=Pin(11), miso=Pin(28))
cs = Pin(9, Pin.OUT)
reader = MinimalRC522(spi, cs, rst)

last_uid = None

while True:
    if reader.request():
        uid = reader.read_uid()
        if uid:
            uid_str = "-".join("{:02X}".format(b) for b in uid)
            if uid_str != last_uid:
                show_text("Tag detected:", uid_str)
                last_uid = uid_str
    else:
        if last_uid is not None:
            show_text("NFC Memory Game", "Scan a tag...")
        last_uid = None
    time.sleep_ms(200)