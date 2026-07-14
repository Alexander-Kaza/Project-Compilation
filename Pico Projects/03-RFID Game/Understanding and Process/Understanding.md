# Understanding.md
### The concepts behind the NFC Memory Game

This file is the *why*. For wiring, code, and setup steps, see [`Process.md`](./Process.md).

**Hardware:** Raspberry Pi Pico 2 W · Pimoroni Pico Display Pack (1.14", ST7789) · RC522 reader · NFC tags · 5-pin rotary encoder, all on a Pico Decker
**Firmware:** [Pimoroni MicroPython (RP2350 build)](https://github.com/pimoroni/pimoroni-pico-rp2350/releases/latest)

## Contents
1. [RC522 & NFC basics](#1-rc522--nfc-basics)
2. [Writing our own RC522 driver](#2-writing-our-own-rc522-driver)
3. [Display basics & the pin conflict](#3-display-basics--the-pin-conflict)
4. [Rotary encoder](#4-rotary-encoder)
5. [Persisting tags to flash](#5-persisting-tags-to-flash)
6. [Game logic — the state machine](#6-game-logic--the-state-machine)
7. [Polish](#7-polish)
8. [Web server & data logging](#8-web-server--data-logging)

---

## 1. RC522 & NFC basics

**RFID vs. NFC:** the RC522 reads **MIFARE** cards (13.56MHz, ISO 14443A) — technically RFID, and a subset of what "NFC" covers more broadly. In this project the terms are used interchangeably.

**How it works:** the reader emits a radio field; a passive tag (no battery — powered *by* that field) modulates it to send data back. That's why range is only a couple of centimeters.

**SPI wiring:** four wires — **SCK** (clock, keeps both chips in sync), **MOSI** (Pico → RC522), **MISO** (RC522 → Pico), **CS** (chip select — "the next data is for you," needed since devices can share a bus) — plus power, ground, and **RST**.

**UID:** every tag has a factory-burned, read-only, unique 4–7 byte ID. That's all we need to tell tags apart — no need to write custom data onto them.

## 2. Writing our own RC522 driver

Rather than trust a third-party file, we implement just enough of the datasheet ourselves — a pattern that transfers to *any* SPI peripheral.

- **Registers:** the chip exposes numbered 8-bit settings/status slots (e.g. "which command to run," "how many bytes are waiting"). You configure it and read results purely by writing/reading these over SPI.
- **Address byte:** every transaction starts with one byte encoding which register and read-vs-write (top bit = read). Chip-specific, but "one byte says what you want, the rest is data" is a common SPI shape.
- **FIFO buffer:** a small internal buffer for data to/from the tag — write command bytes in, trigger "transceive," read the reply back out.
- **Polled interrupts:** the chip has a real IRQ pin (left unconnected) but also mirrors interrupt state into a status register, which we poll instead — simpler, at the cost of a little extra SPI chatter.
- **BCC checksum:** the anti-collision reply includes a checksum (XOR of the 4 UID bytes) we verify before trusting a read.
- **Left out on purpose:** authentication, reading/writing data blocks, multi-tag collision handling — real complexity for capabilities this game doesn't need.

## 3. Display basics & the pin conflict

**Fixed pins:** the Pico Display Pack hardwires itself to GP16–20 via its own PCB traces (DC, CS, SCK, MOSI, backlight) — not jumper wires. That's why it "just works" once plugged in, and why those 5 pins are permanently unavailable for anything else. (This is why the RC522 lives on SPI1, not SPI0.)

**Pico Decker ≠ more pins:** it's a fan-out board, not a GPIO expander. Each of its 4 slots exposes the *same* 26 Pico pins — convenient for wiring multiple things without stacking packs, but it doesn't resolve conflicts between two devices wanting the same pin.

**Framebuffer:** `PicoGraphics` draws into a RAM buffer first; nothing hits the screen until `.update()` pushes the whole frame over SPI in one burst. This avoids flicker and torn frames — standard practice in graphics programming generally.

**Pens:** `create_pen(r, g, b)` just registers a color and returns a lightweight reference for `set_pen()`. `PEN_P4` caps the palette at 16 simultaneous colors, trading range for lower RAM use — plenty for a text/shape UI.

## 4. Rotary encoder

**Quadrature encoding:** two output pins (CLK/A, DT/B) pulse slightly out of phase as the shaft turns; *which one changes first* tells you direction. This 2-signal trick needs no calibration, unlike a potentiometer.

**Interrupts, not polling:** encoders spin fast enough that a slow polling loop can miss a click between iterations. `Pin.irq()` instead fires a callback the instant a pin changes, regardless of what else the program is doing — so we never miss a turn even while busy drawing or polling the RC522.

**Debouncing:** the built-in switch is mechanical — contacts bounce on press, registering as several rapid transitions instead of one. We ignore any second trigger within a short window (tens of ms) of the last.

## 5. Persisting tags to flash

**Where storage lives:** the Pico has no SD card/EEPROM — persistent storage is a section of the same flash chip holding your code, exposed as a normal filesystem. `open("tags.json", "w")` just works.

**Why JSON:** `ujson` converts a Python list to a text file and back in one line each way — simpler than a hand-rolled format, still human-readable.

**Implicit pairing:** rather than storing explicit pair links, we register tags in scan order and treat every 2 consecutive entries as a pair (`index // 2`). Flat, simple storage.

**Flash wear:** endurance is tens of thousands of write cycles per sector — saving on every add/delete during casual play is nowhere near that limit, so no wear-leveling needed here.

**Selection cursor:** move a `cursor` index with the encoder, act on `list[cursor]` on press — a general UI pattern reused for player-count selection in Step 6.

## 6. Game logic — the state machine

**Why one `state` variable:** the same physical inputs (rotate, press, scan) need to do different things depending on mode (registering, picking players, playing, showing a winner). One global `state`, checked first by every handler, is a **finite state machine** — the same pattern behind microwaves, game menus, traffic lights.

**Short vs. long press, one button:** timing the gap between the `FALLING` (pressed) and `RISING` (released) interrupt edges lets one switch produce two distinct gestures.

**Turn logic as data:** a single `current_player` index into a `scores` list, incremented with `%` on a miss, scales to any player count with no extra branches — data-driven logic over duplicated code paths.

## 7. Polish

**Animation = fast sequential drawing:** no special "animation mode" exists — a flash effect is just: draw a frame, `update()`, `sleep_ms()`, draw the normal frame, `update()` again. Safe to block briefly here since match detection runs in the main loop, not an interrupt handler — IRQs still queue independently.

**Centering text:** `measure_text(text, scale)` returns pixel width; centering is just `x = (screen_width - text_width) // 2` — the technique any UI toolkit uses internally.

**Icons from primitives:** no built-in checkmark/X — composed from `circle()` + a few offset `line()` calls (to fake stroke thickness, since lines are 1px).

**Progress bar:** a filled rectangle whose width is `(matched / total) * max_width` — proportional arithmetic, not a special widget.

## 8. Web server & data logging

**Non-blocking, not multi-core:** the Pico 2 W is dual-core, and the server *could* run on core 1 via `_thread` — but sharing `tags`/`scores`/`matched` safely across cores needs locks, and bugs there are nasty and intermittent. Instead, one core, non-blocking socket: `accept()` raises instantly if nobody's connecting, so we just try it once per loop iteration — same "keep the main loop always moving" principle as everything else.

**What a raw HTTP server is:** frameworks hide this, but underneath it's: open a TCP socket, `accept()`, read the raw request bytes, write back a status line + headers + blank line + content. We skip parsing routes entirely — every hit gets the same dashboard, fine for a single-purpose device.

**NTP:** the Pico has no battery-backed clock (boots thinking it's 2021). `ntptime.settime()` fetches real time from a network server now that we're on WiFi — one line for accurate log timestamps.

**Capping the log:** keeping only the last ~50 games bounds both flash usage and RAM (the whole log loads into memory to render the page).

**No authentication:** anyone on the same WiFi can view — and in a more advanced version, tamper with — the page. Fine for a hobby device on a home network; the reason you'd never expose this design directly to the internet.
