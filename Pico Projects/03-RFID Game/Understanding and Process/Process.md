# Process.md
### How we built the NFC Memory Game, step by step

This file is the *how* — wiring, setup, and code for each step. [`Understanding.md`](./Understanding.md) has the *why* behind each one.

**Final assembled files** (`main.py`, `web.py`, `wifi_config.py`, `minimal_rc522.py`) are in the repo root — the steps below are the incremental path that got there, kept for reference.

## Contents
1. [RC522 basics](#1-get-the-rc522-talking-to-the-pico-2-w)
2. [Display + RC522 together](#2-display--rc522-together)
3. [Rotary encoder](#3-rotary-encoder)
4. [Tag memory](#4-tag-memory-store--add--remove--browse)
5. [The game](#5-the-game)
6. [Polish](#6-polish)
7. [Web server & data logging](#7-web-server--data-logging)

---

## 1. Get the RC522 talking to the Pico 2 W

### Wiring (RC522 → Pico 2 W)
| RC522 pin | Pico 2 W pin | Notes |
|---|---|---|
| VCC | 3V3 (OUT, physical pin 36) | RC522 is NOT 5V tolerant — do not use VBUS/5V |
| RST | GP22 (physical pin 29) | driven HIGH in code at startup (RST is active-low; must never float) |
| GND | GND (any GND pin) | |
| MISO | GP28 (physical pin 34) | SPI1 RX |
| MOSI | GP11 (physical pin 15) | SPI1 TX |
| SCK | GP10 (physical pin 14) | SPI1 SCK |
| NSS (=SDA/CS) | GP9 (physical pin 12) | manually toggled in code, doesn't need to be a "real" hardware CS pin |
| IRQ | not connected | unused — we're polling, not interrupt-driven |

**Why SPI1 and not SPI0:** the display claims GP16-20 (see [Understanding.md §3](./Understanding.md#3-display-basics--the-pin-conflict)) — SPI1 on GP9/10/11/28 is clear.

### Software setup
1. Flash the Pico 2 W with **Pimoroni's RP2350 MicroPython build** (needed for the display in Step 2, and works fine for RC522-only testing too): [pimoroni-pico-rp2350 releases](https://github.com/pimoroni/pimoroni-pico-rp2350/releases/latest) → download the asset named like `pico2_w-*-pimoroni-micropython.uf2` → hold BOOTSEL, plug in, drag the file onto the `RPI-RP2` drive.
2. No third-party library — we're writing our own minimal driver (see Understanding.md for the concepts behind it).

### Our own driver — save as `/lib/minimal_rc522.py`
```python
from machine import Pin, SPI
import time

# --- MFRC522 register addresses (from the NXP datasheet) ---
CommandReg    = 0x01
ComIrqReg     = 0x04
ErrorReg      = 0x06
FIFODataReg   = 0x09
FIFOLevelReg  = 0x0A
BitFramingReg = 0x0D
ModeReg       = 0x11
TxControlReg  = 0x14
TxASKReg      = 0x15
TModeReg      = 0x2A
TPrescalerReg = 0x2B
TReloadRegH   = 0x2C
TReloadRegL   = 0x2D

PCD_IDLE       = 0x00
PCD_TRANSCEIVE = 0x0C
PCD_RESET      = 0x0F

PICC_REQIDL   = 0x26  # "is anyone there?" (REQA)
PICC_ANTICOLL = 0x93  # anti-collision, cascade level 1


class MinimalRC522:
    def __init__(self, spi, cs, rst):
        self.spi = spi
        self.cs = cs
        self.rst = rst
        self.cs.value(1)
        self.rst.value(1)
        self._init_reader()

    # --- low-level register access ---
    def _write(self, reg, val):
        self.cs.value(0)
        self.spi.write(bytes([(reg << 1) & 0x7E, val]))
        self.cs.value(1)

    def _read(self, reg):
        self.cs.value(0)
        self.spi.write(bytes([((reg << 1) & 0x7E) | 0x80]))
        result = self.spi.read(1)
        self.cs.value(1)
        return result[0]

    def _set_bits(self, reg, mask):
        self._write(reg, self._read(reg) | mask)

    def _clear_bits(self, reg, mask):
        self._write(reg, self._read(reg) & (~mask & 0xFF))

    # --- setup ---
    def _init_reader(self):
        self._write(CommandReg, PCD_RESET)
        time.sleep_ms(50)
        self._write(TModeReg, 0x8D)
        self._write(TPrescalerReg, 0x3E)
        self._write(TReloadRegL, 30)
        self._write(TReloadRegH, 0)
        self._write(TxASKReg, 0x40)   # force 100% ASK modulation
        self._write(ModeReg, 0x3D)
        self._antenna_on()

    def _antenna_on(self):
        if not (self._read(TxControlReg) & 0x03):
            self._set_bits(TxControlReg, 0x03)

    # --- talking to a tag ---
    def _transceive(self, data):
        self._write(CommandReg, PCD_IDLE)
        self._write(ComIrqReg, 0x7F)          # clear all interrupt flags
        self._set_bits(FIFOLevelReg, 0x80)    # flush FIFO

        for b in data:
            self._write(FIFODataReg, b)

        self._write(CommandReg, PCD_TRANSCEIVE)
        self._set_bits(BitFramingReg, 0x80)   # start send

        for _ in range(2000):                 # wait for finish or time out
            if self._read(ComIrqReg) & 0x30:  # RxIRq or IdleIRq set
                break
        self._clear_bits(BitFramingReg, 0x80)

        if self._read(ErrorReg) & 0x1B:       # a real error bit is set
            return None

        n = self._read(FIFOLevelReg)
        return bytes(self._read(FIFODataReg) for _ in range(n))

    def request(self):
        """True if a tag is in range."""
        self._write(BitFramingReg, 0x07)      # last byte: only 7 bits valid
        resp = self._transceive([PICC_REQIDL])
        self._write(BitFramingReg, 0x00)
        return resp is not None and len(resp) == 2

    def read_uid(self):
        """Returns the tag's 4-byte UID, or None if no valid read."""
        resp = self._transceive([PICC_ANTICOLL, 0x20])
        if resp is None or len(resp) != 5:
            return None
        uid, checksum = resp[:4], resp[4]
        if (uid[0] ^ uid[1] ^ uid[2] ^ uid[3]) != checksum:
            return None
        return uid
```

### Test script — save as `main.py`
```python
from machine import Pin, SPI
from minimal_rc522 import MinimalRC522
import time

rst = Pin(22, Pin.OUT)
rst.value(1)

spi = SPI(1, baudrate=1_000_000, polarity=0, phase=0,
          sck=Pin(10), mosi=Pin(11), miso=Pin(28))
cs = Pin(9, Pin.OUT)

reader = MinimalRC522(spi, cs, rst)

print("Scan a tag...")
last_uid = None

while True:
    if reader.request():
        uid = reader.read_uid()
        if uid:
            uid_str = "-".join("{:02X}".format(b) for b in uid)
            if uid_str != last_uid:
                print("Tag UID:", uid_str)
                last_uid = uid_str
    else:
        last_uid = None
    time.sleep_ms(200)
```

### Status
⏳ Waiting on you to save both files and test.

---

## 2. Display + RC522 together

Once Step 1 prints UIDs reliably, swap `main.py` for this — same driver, now also drawing to the screen.

### Combined script (`main.py`)
```python
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
```

**What's new here vs. Step 1:** `PicoGraphics` manages an off-screen framebuffer — you draw into it (`.text()`, `.clear()`, etc.) then call `.update()` once to push the whole frame to the screen in one go. This is why we build `show_text()` as one function: fewer `.update()` calls means no visible flicker/tearing. `PEN_P4` is a 16-colour palette mode — plenty for text, and lighter on RAM than full colour.

### Status
✅ Working — display + RC522 confirmed together.

---

## 3. Rotary encoder

### Wiring (5-pin encoder → Pico 2 W)
| Encoder pin | Pico 2 W pin | Notes |
|---|---|---|
| + / VCC | 3V3 (OUT) | |
| GND | GND | |
| CLK (A) | GP2 | interrupt-driven |
| DT (B) | GP3 | read at time of CLK interrupt |
| SW (button) | GP4 | pulled up internally, active LOW |

Remaining free pins after display + RC522: GP0,1,2,3,4,5,21,26,27 — plenty of room, so GP2/3/4 keeps the encoder's wires close together on the Decker.

### Test script — save as `main.py`
```python
from machine import Pin
import time

clk = Pin(2, Pin.IN, Pin.PULL_UP)
dt  = Pin(3, Pin.IN, Pin.PULL_UP)
sw  = Pin(4, Pin.IN, Pin.PULL_UP)

position = 0
last_press_ms = 0

def on_rotate(pin):
    global position
    # DT's current level at the moment CLK fires tells us direction
    if dt.value() != clk.value():
        position += 1
        print("CW  ->", position)
    else:
        position -= 1
        print("CCW ->", position)

def on_press(pin):
    global last_press_ms
    now = time.ticks_ms()
    if time.ticks_diff(now, last_press_ms) > 200:  # debounce
        print("Button pressed! position =", position)
        last_press_ms = now

clk.irq(trigger=Pin.IRQ_FALLING, handler=on_rotate)
sw.irq(trigger=Pin.IRQ_FALLING, handler=on_press)

print("Turn the knob or press it...")
while True:
    time.sleep(1)  # main loop is free — the IRQs do the work
```

**What this does:** `clk.irq(...)` registers `on_rotate` to fire the instant GP2 goes HIGH→LOW (a "falling edge"), regardless of what the main loop is doing. Inside it, we check `dt.value()` at that exact moment to figure out spin direction (this is the quadrature trick from Understanding.md). The main loop itself does nothing — it's just kept alive while interrupts handle everything.

### Status
✅ Working — encoder confirmed.

---

## 4. Tag memory (store / add / remove / browse)

Supports unlimited tags, stored as JSON on the Pico's flash (`tags.json`), pairs implied by scan order (see Understanding.md). This script: scanning a new tag adds it and saves immediately; turning the knob scrolls a cursor through the registered list; pressing the knob deletes whichever tag is currently shown.

### Script — save as `main.py`
```python
from machine import Pin, SPI
from picographics import PicoGraphics, DISPLAY_PICO_DISPLAY, PEN_P4
from minimal_rc522 import MinimalRC522
import ujson
import time

TAGS_FILE = "tags.json"

def load_tags():
    try:
        with open(TAGS_FILE) as f:
            return ujson.load(f)
    except OSError:
        return []

def save_tags(tags):
    with open(TAGS_FILE, "w") as f:
        ujson.dump(tags, f)

tags = load_tags()
cursor = 0
dirty = True

# --- display ---
display = PicoGraphics(display=DISPLAY_PICO_DISPLAY, pen_type=PEN_P4, rotate=0)
display.set_backlight(0.8)
display.set_font("bitmap8")
WHITE = display.create_pen(255, 255, 255)
BLACK = display.create_pen(0, 0, 0)
GREEN = display.create_pen(0, 255, 0)
RED   = display.create_pen(255, 60, 60)

def refresh():
    display.set_pen(BLACK)
    display.clear()
    display.set_pen(WHITE)
    display.text("Tags: {}".format(len(tags)), 10, 10, 220, 2)
    if tags:
        display.set_pen(GREEN)
        display.text("{}/{}: {}".format(cursor + 1, len(tags), tags[cursor]), 10, 50, 220, 2)
    else:
        display.set_pen(RED)
        display.text("No tags yet - scan one", 10, 50, 220, 2)
    display.set_pen(WHITE)
    display.text("Scan=add  Press=delete", 10, 105, 220, 1)
    display.update()

# --- RC522 (SPI1) ---
rst = Pin(22, Pin.OUT); rst.value(1)
spi = SPI(1, baudrate=1_000_000, polarity=0, phase=0,
          sck=Pin(10), mosi=Pin(11), miso=Pin(28))
cs = Pin(9, Pin.OUT)
reader = MinimalRC522(spi, cs, rst)
last_uid = None

# --- encoder ---
clk = Pin(2, Pin.IN, Pin.PULL_UP)
dt  = Pin(3, Pin.IN, Pin.PULL_UP)
sw  = Pin(4, Pin.IN, Pin.PULL_UP)
last_press_ms = 0

def on_rotate(pin):
    global cursor, dirty
    if not tags:
        return
    cursor = (cursor + 1) % len(tags) if dt.value() != clk.value() else (cursor - 1) % len(tags)
    dirty = True

def on_press(pin):
    global last_press_ms, cursor, dirty
    now = time.ticks_ms()
    if time.ticks_diff(now, last_press_ms) < 200:
        return
    last_press_ms = now
    if tags:
        tags.pop(cursor)
        save_tags(tags)
        cursor = 0
        dirty = True

clk.irq(trigger=Pin.IRQ_FALLING, handler=on_rotate)
sw.irq(trigger=Pin.IRQ_FALLING, handler=on_press)

while True:
    if reader.request():
        uid_bytes = reader.read_uid()
        if uid_bytes:
            uid = "-".join("{:02X}".format(b) for b in uid_bytes)
            if uid != last_uid:
                last_uid = uid
                if uid not in tags:
                    tags.append(uid)
                    save_tags(tags)
                    cursor = len(tags) - 1
                    dirty = True
    else:
        last_uid = None

    if dirty:
        refresh()
        dirty = False

    time.sleep_ms(150)
```

### Status
✅ Working — tag registration confirmed, persists across reboot.

---

## 5. The game

States: `REGISTER` → `SELECT_PLAYERS` → `GAMEPLAY` → `VICTORY`, moved between with a long press (~0.6s). Short press means something different per state (see table). Register tags in pairs as before — pairing is still implicit by scan order.

| State | Rotate | Short press | Long press |
|---|---|---|---|
| REGISTER | scroll tag list | delete highlighted tag | → SELECT_PLAYERS (needs ≥1 pair) |
| SELECT_PLAYERS | change player count (2-6) | → GAMEPLAY (start) | → REGISTER |
| GAMEPLAY | (unused) | acknowledge a mismatch, pass turn | → SELECT_PLAYERS (abort) |
| VICTORY | (unused) | replay, same tags → SELECT_PLAYERS | → REGISTER (add more tags) |

### Script — save as `main.py`
```python
from machine import Pin, SPI
from picographics import PicoGraphics, DISPLAY_PICO_DISPLAY, PEN_P4
from minimal_rc522 import MinimalRC522
import ujson, time

TAGS_FILE = "tags.json"

def load_tags():
    try:
        with open(TAGS_FILE) as f:
            return ujson.load(f)
    except OSError:
        return []

def save_tags(tags):
    with open(TAGS_FILE, "w") as f:
        ujson.dump(tags, f)

def partner(idx):
    return idx - 1 if idx % 2 else idx + 1

# --- state ---
REGISTER, SELECT_PLAYERS, GAMEPLAY, VICTORY = range(4)
state = REGISTER
tags = load_tags()
cursor = 0
num_players = 2
scores = []
current_player = 0
matched = set()
flipped = []          # up to 2 indices currently face-up
awaiting_ack = False   # true after a mismatch, until player presses to continue
dirty = True

# --- display ---
display = PicoGraphics(display=DISPLAY_PICO_DISPLAY, pen_type=PEN_P4, rotate=0)
display.set_backlight(0.8)
display.set_font("bitmap8")
WHITE = display.create_pen(255, 255, 255)
BLACK = display.create_pen(0, 0, 0)
GREEN = display.create_pen(0, 255, 0)
RED   = display.create_pen(255, 60, 60)
YELLOW = display.create_pen(255, 220, 0)

def refresh():
    display.set_pen(BLACK); display.clear()
    if state == REGISTER:
        display.set_pen(WHITE); display.text("Tags: {}".format(len(tags)), 10, 5, 220, 2)
        if tags:
            display.set_pen(GREEN)
            display.text("{}/{}: {}".format(cursor + 1, len(tags), tags[cursor]), 10, 40, 220, 2)
        else:
            display.set_pen(RED); display.text("Scan tags to add", 10, 40, 220, 2)
        display.set_pen(WHITE)
        display.text("Press=del  Hold=play", 10, 100, 220, 1)
    elif state == SELECT_PLAYERS:
        display.set_pen(WHITE); display.text("Select Players", 10, 10, 220, 2)
        display.set_pen(GREEN); display.text("< {} >".format(num_players), 10, 50, 220, 3)
        display.set_pen(WHITE); display.text("Press=start Hold=back", 10, 105, 220, 1)
    elif state == GAMEPLAY:
        display.set_pen(WHITE)
        display.text("Player {}".format(current_player + 1), 10, 5, 220, 2)
        scoreline = " ".join("P{}:{}".format(i + 1, s) for i, s in enumerate(scores))
        display.text(scoreline, 10, 30, 220, 1)
        if awaiting_ack:
            display.set_pen(RED); display.text("No match - press", 10, 60, 220, 2)
        elif len(flipped) == 1:
            display.set_pen(YELLOW); display.text("Card 1 scanned...", 10, 60, 220, 2)
        else:
            display.set_pen(GREEN); display.text("Scan a card", 10, 60, 220, 2)
        display.set_pen(WHITE)
        display.text("Matched {}/{}".format(len(matched), len(tags)), 10, 100, 220, 1)
    elif state == VICTORY:
        winner = scores.index(max(scores))
        display.set_pen(GREEN)
        display.text("Player {} wins!".format(winner + 1), 10, 20, 220, 2)
        display.set_pen(WHITE)
        display.text("Score: {}".format(scores[winner]), 10, 55, 220, 2)
        display.text("Press=replay Hold=+tags", 10, 100, 220, 1)
    display.update()

# --- RC522 (SPI1) ---
rst = Pin(22, Pin.OUT); rst.value(1)
spi = SPI(1, baudrate=1_000_000, polarity=0, phase=0,
          sck=Pin(10), mosi=Pin(11), miso=Pin(28))
cs = Pin(9, Pin.OUT)
reader = MinimalRC522(spi, cs, rst)
last_uid = None

# --- encoder ---
clk = Pin(2, Pin.IN, Pin.PULL_UP)
dt  = Pin(3, Pin.IN, Pin.PULL_UP)
sw  = Pin(4, Pin.IN, Pin.PULL_UP)
press_start_ms = 0

def on_rotate(pin):
    global cursor, num_players, dirty
    cw = dt.value() != clk.value()
    if state == REGISTER and tags:
        cursor = (cursor + 1) % len(tags) if cw else (cursor - 1) % len(tags)
        dirty = True
    elif state == SELECT_PLAYERS:
        num_players = min(6, num_players + 1) if cw else max(2, num_players - 1)
        dirty = True

def short_press():
    global state, tags, cursor, scores, current_player, matched, flipped, awaiting_ack, dirty
    if state == REGISTER:
        if tags:
            tags.pop(cursor); save_tags(tags); cursor = 0
    elif state == SELECT_PLAYERS:
        scores = [0] * num_players
        current_player = 0
        matched = set()
        flipped = []
        awaiting_ack = False
        state = GAMEPLAY
    elif state == GAMEPLAY and awaiting_ack:
        flipped = []
        awaiting_ack = False
        current_player = (current_player + 1) % num_players
    elif state == VICTORY:
        state = SELECT_PLAYERS
    dirty = True

def long_press():
    global state, dirty
    if state == REGISTER and len(tags) >= 2 and len(tags) % 2 == 0:
        state = SELECT_PLAYERS
    elif state == SELECT_PLAYERS:
        state = REGISTER
    elif state == GAMEPLAY:
        state = SELECT_PLAYERS
    elif state == VICTORY:
        state = REGISTER
    dirty = True

def on_switch(pin):
    global press_start_ms
    now = time.ticks_ms()
    if sw.value() == 0:
        press_start_ms = now
    else:
        dur = time.ticks_diff(now, press_start_ms)
        if dur < 20:
            return
        long_press() if dur > 600 else short_press()

clk.irq(trigger=Pin.IRQ_FALLING, handler=on_rotate)
sw.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=on_switch)

refresh()

while True:
    if reader.request():
        uid_bytes = reader.read_uid()
        if uid_bytes:
            uid = "-".join("{:02X}".format(b) for b in uid_bytes)
            if uid != last_uid:
                last_uid = uid

                if state == REGISTER and uid not in tags:
                    tags.append(uid); save_tags(tags); cursor = len(tags) - 1
                    dirty = True

                elif state == GAMEPLAY and not awaiting_ack and uid in tags:
                    idx = tags.index(uid)
                    if idx not in matched and idx not in flipped:
                        flipped.append(idx)
                        if len(flipped) == 2:
                            if flipped[1] == partner(flipped[0]):
                                matched.update(flipped)
                                scores[current_player] += 1
                                flipped = []
                                if len(matched) == len(tags):
                                    state = VICTORY
                            else:
                                awaiting_ack = True
                        dirty = True
    else:
        last_uid = None

    if dirty:
        refresh()
        dirty = False

    time.sleep_ms(150)
```

### Status
✅ Full game loop confirmed working. *(Superseded visually by the polished version below — kept here as the bare mechanics without UI flourishes.)*

---

## 6. Polish

Adds a colored header bar per screen, centered text, a drawn checkmark/X for match/miss feedback, and a confetti victory screen. Same wiring/logic as Step 5 — drop-in replacement for `main.py`. (Concepts: [Understanding.md §7](./Understanding.md#7-polish))

### Script — save as `main.py`
```python
from machine import Pin, SPI
from picographics import PicoGraphics, DISPLAY_PICO_DISPLAY, PEN_P4
from minimal_rc522 import MinimalRC522
import ujson, time, random

TAGS_FILE = "tags.json"
W, H = 240, 135

def load_tags():
    try:
        with open(TAGS_FILE) as f:
            return ujson.load(f)
    except OSError:
        return []

def save_tags(tags):
    with open(TAGS_FILE, "w") as f:
        ujson.dump(tags, f)

def partner(idx):
    return idx - 1 if idx % 2 else idx + 1

# --- state ---
BOOT, REGISTER, SELECT_PLAYERS, GAMEPLAY, VICTORY = range(5)
state = BOOT
tags = load_tags()
cursor = 0
num_players = 2
scores = []
current_player = 0
matched = set()
flipped = []
dirty = True

# --- display & palette ---
display = PicoGraphics(display=DISPLAY_PICO_DISPLAY, pen_type=PEN_P4, rotate=0)
display.set_backlight(0.8)
display.set_font("bitmap8")
WHITE  = display.create_pen(255, 255, 255)
BLACK  = display.create_pen(0, 0, 0)
GRAY   = display.create_pen(120, 120, 120)
GREEN  = display.create_pen(0, 255, 0)
RED    = display.create_pen(255, 60, 60)
YELLOW = display.create_pen(255, 220, 0)
CYAN   = display.create_pen(0, 220, 255)
PURPLE = display.create_pen(180, 80, 255)
ORANGE = display.create_pen(255, 150, 0)
PINK   = display.create_pen(255, 105, 180)
GOLD   = display.create_pen(255, 200, 40)
BLUE   = display.create_pen(60, 130, 255)
PLAYER_COLORS = [GREEN, CYAN, PURPLE, ORANGE, PINK, WHITE]

def center_text(text, y, scale, pen):
    display.set_pen(pen)
    w = display.measure_text(text, scale)
    display.text(text, (W - w) // 2, y, W, scale)

def header(text, color):
    display.set_pen(color)
    display.rectangle(0, 0, W, 24)
    center_text(text, 5, 2, BLACK)

def progress_bar(y, frac):
    display.set_pen(WHITE); display.rectangle(20, y, W - 40, 8)
    display.set_pen(BLACK); display.rectangle(21, y + 1, W - 42, 6)
    display.set_pen(GREEN); display.rectangle(21, y + 1, int((W - 42) * frac), 6)

def flash_feedback(color, is_match, label, ms=500):
    display.set_pen(BLACK); display.clear()
    cx, cy = W // 2, 58
    display.set_pen(WHITE); display.circle(cx, cy, 40)
    display.set_pen(color);  display.circle(cx, cy, 34)
    display.set_pen(WHITE)
    if is_match:
        for o in (-1, 0, 1):
            display.line(cx - 16 + o, cy + 2, cx - 4 + o, cy + 14)
            display.line(cx - 4 + o, cy + 14, cx + 18 + o, cy - 12)
    else:
        for o in (-1, 0, 1):
            display.line(cx - 14 + o, cy - 14, cx + 14 + o, cy + 14)
            display.line(cx - 14 + o, cy + 14, cx + 14 + o, cy - 14)
    center_text(label, 105, 2, WHITE)
    display.update()
    time.sleep_ms(ms)

def refresh():
    display.set_pen(BLACK); display.clear()

    if state == REGISTER:
        header("Tag Registration", BLUE)
        if tags:
            center_text("{}/{}".format(cursor + 1, len(tags)), 40, 2, WHITE)
            center_text(tags[cursor], 65, 2, GREEN)
        else:
            center_text("Scan a tag to begin", 55, 2, RED)
        center_text("Press=delete   Hold=play", 112, 1, GRAY)

    elif state == SELECT_PLAYERS:
        header("Select Players", PURPLE)
        color = PLAYER_COLORS[num_players - 1]
        center_text("< {} >".format(num_players), 45, 4, color)
        center_text("Press=start   Hold=back", 112, 1, GRAY)

    elif state == GAMEPLAY:
        pc = PLAYER_COLORS[current_player % len(PLAYER_COLORS)]
        header("Player {}'s Turn".format(current_player + 1), pc)
        scoreline = "   ".join("P{}: {}".format(i + 1, s) for i, s in enumerate(scores))
        center_text(scoreline, 32, 1, WHITE)
        if len(flipped) == 1:
            center_text("Card 1 scanned...", 58, 2, YELLOW)
        else:
            center_text("Scan a card", 58, 2, pc)
        center_text("{}/{} pairs found".format(len(matched) // 2, len(tags) // 2), 90, 1, GRAY)
        progress_bar(108, len(matched) / len(tags) if tags else 0)

    elif state == VICTORY:
        header("Game Over!", GOLD)
        for _ in range(18):
            display.set_pen(random.choice(PLAYER_COLORS))
            display.circle(random.randint(5, W - 5), random.randint(28, H - 20), 2)
        winner = scores.index(max(scores))
        center_text("Player {} wins!".format(winner + 1), 45, 2, PLAYER_COLORS[winner % len(PLAYER_COLORS)])
        center_text("Score: {}".format(scores[winner]), 72, 2, WHITE)
        center_text("Press=replay   Hold=+tags", 112, 1, GRAY)

    display.update()

# --- RC522 (SPI1) ---
rst = Pin(22, Pin.OUT); rst.value(1)
spi = SPI(1, baudrate=1_000_000, polarity=0, phase=0,
          sck=Pin(10), mosi=Pin(11), miso=Pin(28))
cs = Pin(9, Pin.OUT)
reader = MinimalRC522(spi, cs, rst)
last_uid = None

# --- encoder ---
clk = Pin(2, Pin.IN, Pin.PULL_UP)
dt  = Pin(3, Pin.IN, Pin.PULL_UP)
sw  = Pin(4, Pin.IN, Pin.PULL_UP)
press_start_ms = 0

def on_rotate(pin):
    global cursor, num_players, dirty
    cw = dt.value() != clk.value()
    if state == REGISTER and tags:
        cursor = (cursor + 1) % len(tags) if cw else (cursor - 1) % len(tags)
        dirty = True
    elif state == SELECT_PLAYERS:
        num_players = min(6, num_players + 1) if cw else max(2, num_players - 1)
        dirty = True

def short_press():
    global state, tags, cursor, scores, current_player, matched, flipped, dirty
    if state == REGISTER:
        if tags:
            tags.pop(cursor); save_tags(tags); cursor = 0
    elif state == SELECT_PLAYERS:
        scores = [0] * num_players
        current_player = 0
        matched = set()
        flipped = []
        state = GAMEPLAY
    elif state == VICTORY:
        state = SELECT_PLAYERS
    dirty = True

def long_press():
    global state, dirty
    if state == REGISTER and len(tags) >= 2 and len(tags) % 2 == 0:
        state = SELECT_PLAYERS
    elif state == SELECT_PLAYERS:
        state = REGISTER
    elif state == GAMEPLAY:
        state = SELECT_PLAYERS
    elif state == VICTORY:
        state = REGISTER
    dirty = True

def on_switch(pin):
    global press_start_ms
    now = time.ticks_ms()
    if sw.value() == 0:
        press_start_ms = now
    else:
        dur = time.ticks_diff(now, press_start_ms)
        if dur < 20:
            return
        long_press() if dur > 600 else short_press()

clk.irq(trigger=Pin.IRQ_FALLING, handler=on_rotate)
sw.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=on_switch)

# --- boot splash ---
display.set_pen(BLACK); display.clear()
display.set_pen(GREEN); display.rectangle(70, 25, 45, 60)
display.set_pen(CYAN);  display.rectangle(85, 15, 45, 60)
display.set_pen(BLACK)
display.rectangle(90, 20, 35, 50)
center_text("NFC", 35, 2, WHITE)
center_text("Memory Game", 90, 2, WHITE)
display.update()
time.sleep_ms(1600)
state = REGISTER
refresh()

while True:
    if reader.request():
        uid_bytes = reader.read_uid()
        if uid_bytes:
            uid = "-".join("{:02X}".format(b) for b in uid_bytes)
            if uid != last_uid:
                last_uid = uid

                if state == REGISTER and uid not in tags:
                    tags.append(uid); save_tags(tags); cursor = len(tags) - 1
                    dirty = True

                elif state == GAMEPLAY and uid in tags:
                    idx = tags.index(uid)
                    if idx not in matched and idx not in flipped:
                        flipped.append(idx)
                        if len(flipped) == 2:
                            if flipped[1] == partner(flipped[0]):
                                matched.update(flipped)
                                scores[current_player] += 1
                                flipped = []
                                flash_feedback(GREEN, True, "MATCH!")
                                if len(matched) == len(tags):
                                    state = VICTORY
                            else:
                                flash_feedback(RED, False, "No match")
                                flipped = []
                                current_player = (current_player + 1) % num_players
                        dirty = True
    else:
        last_uid = None

    if dirty:
        refresh()
        dirty = False

    time.sleep_ms(150)
```

### Status
⏳ Waiting on you to test the v2 UI.

---

## 7. Web server & data logging

### `wifi_config.py` — save to the Pico, fill in your password
```python
WIFI_SSID = "Edelweiss"
WIFI_PASSWORD = "your-password-here"
```

### `web.py` — save to the Pico
```python
import network, socket, time
try:
    import ntptime
except ImportError:
    ntptime = None

def connect_wifi(ssid, password, timeout_s=15):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(ssid, password)
    start = time.ticks_ms()
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), start) > timeout_s * 1000:
            return None
        time.sleep_ms(200)
    if ntptime:
        try:
            ntptime.settime()
        except Exception:
            pass  # game still works fine without accurate timestamps
    return wlan.ifconfig()[0]

def start_server(port=80):
    addr = socket.getaddrinfo("0.0.0.0", port)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(2)
    s.setblocking(False)
    return s

def poll_server(server, render_fn):
    """Call every loop iteration. Does nothing if no one is connecting."""
    try:
        client, _ = server.accept()
    except OSError:
        return
    try:
        client.settimeout(1.0)
        client.recv(1024)  # we don't parse the request - every hit gets the same page
        body = render_fn()
        client.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n" + body)
    except Exception:
        pass
    finally:
        client.close()
```

### Additions to `main.py`
Add near the top, alongside your other imports:
```python
import ujson, time
from web import connect_wifi, start_server, poll_server
from wifi_config import WIFI_SSID, WIFI_PASSWORD

GAME_LOG_FILE = "game_log.json"

def load_log():
    try:
        with open(GAME_LOG_FILE) as f:
            return ujson.load(f)
    except OSError:
        return []

def save_log(log):
    with open(GAME_LOG_FILE, "w") as f:
        ujson.dump(log, f)

def record_game(scores, winner):
    global game_log
    entry = {
        "time": "{:04d}-{:02d}-{:02d} {:02d}:{:02d}".format(*time.localtime()[:5]),
        "players": len(scores),
        "scores": scores,
        "winner": winner + 1,
    }
    game_log.append(entry)
    game_log = game_log[-50:]  # keep flash + RAM usage bounded
    save_log(game_log)

game_log = load_log()
ip_address = None
server = None

def render_page():
    win_counts = {}
    for g in game_log:
        win_counts[g["winner"]] = win_counts.get(g["winner"], 0) + 1
    max_wins = max(win_counts.values()) if win_counts else 1

    bars = ""
    for p in sorted(win_counts):
        pct = int(100 * win_counts[p] / max_wins)
        bars += ("<div class='bar-row'><span class='bar-label'>P{p}</span>"
                  "<div class='bar-track'><div class='bar-fill' style='width:{pct}%'></div></div>"
                  "<span class='bar-count'>{c}</span></div>").format(p=p, pct=pct, c=win_counts[p])

    rows = ""
    for g in reversed(game_log[-10:]):
        rows += "<tr><td>{t}</td><td>{p}</td><td>{s}</td><td>P{w}</td></tr>".format(
            t=g["time"], p=g["players"], s=g["scores"], w=g["winner"])

    return """<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<title>NFC Memory Game</title><style>
body{{background:#111827;color:#e5e7eb;font-family:sans-serif;margin:0;padding:24px}}
h1{{font-size:1.4em;margin-bottom:4px}}
.sub{{color:#9ca3af;margin-bottom:24px}}
.card{{background:#1f2937;border-radius:12px;padding:18px;margin-bottom:20px;box-shadow:0 2px 8px rgba(0,0,0,.3)}}
.stat{{font-size:2em;font-weight:bold;color:#34d399}}
.bar-row{{display:flex;align-items:center;margin:8px 0}}
.bar-label{{width:40px}}
.bar-track{{flex:1;background:#374151;border-radius:6px;height:14px;margin:0 10px;overflow:hidden}}
.bar-fill{{background:linear-gradient(90deg,#34d399,#22d3ee);height:100%}}
table{{width:100%;border-collapse:collapse}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #374151;font-size:.9em}}
</style></head><body>
<h1>NFC Memory Game</h1><div class="sub">Live stats from the Pico</div>
<div class="card"><div>Total games played</div><div class="stat">{total}</div></div>
<div class="card"><div>Wins by player</div>{bars}</div>
<div class="card"><div>Recent games</div><table><tr><th>Time</th><th>Players</th><th>Scores</th><th>Winner</th></tr>{rows}</table></div>
</body></html>""".format(total=len(game_log), bars=bars or "<i>No games yet</i>",
                          rows=rows or "<tr><td colspan=4><i>No games yet</i></td></tr>")
```

In the **boot splash section**, right before `state = REGISTER`, add:
```python
center_text("Connecting WiFi...", 118, 1, GRAY)
display.update()
ip_address = connect_wifi(WIFI_SSID, WIFI_PASSWORD)
if ip_address:
    server = start_server()
```

In **`refresh()`**, add an IP line to the REGISTER screen footer so you know where to browse:
```python
if ip_address:
    center_text(ip_address, 124, 1, GRAY)
```
*(nudge the existing "Press=delete Hold=play" line up a few pixels to make room, e.g. to y=108)*

Where a game ends (`if len(matched) == len(tags): state = VICTORY`), add logging right after:
```python
record_game(scores, winner=scores.index(max(scores)))
```

In the **main `while True:` loop**, add one line so the server actually gets serviced:
```python
if server:
    poll_server(server, render_page)
```

### Status
⏳ Waiting on you to fill in `wifi_config.py`, upload `web.py`, wire the snippets above into `main.py`, and test — power on, check the display shows an IP, visit `http://<that-ip>` from your phone/laptop on the same WiFi, then play a game and refresh the page.
