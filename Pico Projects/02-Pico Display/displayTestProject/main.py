from picographics import PicoGraphics, DISPLAY_PICO_DISPLAY
from pimoroni import Button
import time

# --- Hardware ---
display = PicoGraphics(display=DISPLAY_PICO_DISPLAY, rotate=180)
WIDTH, HEIGHT = display.get_bounds()  # 240 x 135

button_a = Button(12)
button_b = Button(13)
button_x = Button(14)
button_y = Button(15)

# --- Options each button cycles through ---
COLORS = [
    ("RED",     (255,   0,   0)),
    ("GREEN",   (  0, 255,   0)),
    ("BLUE",    ( 50, 120, 255)),
    ("YELLOW",  (255, 220,   0)),
    ("MAGENTA", (255,   0, 200)),
    ("CYAN",    (  0, 220, 220)),
    ("WHITE",   (255, 255, 255)),
]
BRIGHTNESSES = [0.1, 0.25, 0.5, 0.75, 1.0]
SHAPES   = ["RECTANGLE", "CIRCLE", "TRIANGLE"]
MESSAGES = ["Hello!", "Pico Display", "MicroPython", "A B X Y"]

# --- State ---
color_idx      = 0     # A cycles this
brightness_idx = 2     # B cycles this
shape_idx      = 0     # X cycles this
message_idx    = 0     # Y cycles this

display.set_backlight(BRIGHTNESSES[brightness_idx])

# --- Main loop ---
while True:
    # Read buttons (each .read() returns True once per press)
    if button_a.read():
        color_idx = (color_idx + 1) % len(COLORS)
    if button_b.read():
        brightness_idx = (brightness_idx + 1) % len(BRIGHTNESSES)
        display.set_backlight(BRIGHTNESSES[brightness_idx])
    if button_x.read():
        shape_idx = (shape_idx + 1) % len(SHAPES)
    if button_y.read():
        message_idx = (message_idx + 1) % len(MESSAGES)

    # Clear to dark background
    bg = display.create_pen(15, 15, 20)
    display.set_pen(bg)
    display.clear()
    

    # Draw the current shape in the current color, centered
    name, rgb = COLORS[color_idx]
    fg = display.create_pen(*rgb)
    display.set_pen(fg)

    cx, cy = WIDTH // 2, HEIGHT // 2
    shape = SHAPES[shape_idx]
    if shape == "RECTANGLE":
        display.rectangle(cx - 40, cy - 25, 80, 50)
    elif shape == "CIRCLE":
        display.circle(cx, cy, 30)
    elif shape == "TRIANGLE":
        display.triangle(cx, cy - 30, cx - 35, cy + 25, cx + 35, cy + 25)

    # Overlay text in white
    white = display.create_pen(255, 255, 255)
    display.set_pen(white)
    display.text(MESSAGES[message_idx], 5, 5, WIDTH, 2)
    display.text("A: color "      + name,                                5, HEIGHT - 40, WIDTH, 1)
    display.text("B: brightness " + str(int(BRIGHTNESSES[brightness_idx] * 100)) + "%", 5, HEIGHT - 30, WIDTH, 1)
    display.text("X: shape "      + shape,                               5, HEIGHT - 20, WIDTH, 1)
    display.text("Y: message",                                           5, HEIGHT - 10, WIDTH, 1)

    display.update()
    time.sleep(0.02)