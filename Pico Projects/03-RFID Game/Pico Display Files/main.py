from machine import Pin, SPI
from picographics import PicoGraphics, DISPLAY_PICO_DISPLAY, PEN_P4
from minimal_rc522 import MinimalRC522
import ujson, time, random
from web import connect_wifi, start_server, poll_server
from wifi_config import WIFI_SSID, WIFI_PASSWORD

TAGS_FILE = "tags.json"
GAME_LOG_FILE = "game_log.json"
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

# --- state ---
BOOT, REGISTER, SELECT_PLAYERS, GAMEPLAY, VICTORY = range(5)
state = BOOT
tags = load_tags()
game_log = load_log()
ip_address = None
server = None
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
        center_text("Press=delete   Hold=play", 108, 1, GRAY)
        if ip_address:
            center_text(ip_address, 124, 1, GRAY)

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
time.sleep_ms(1200)

center_text("Connecting WiFi...", 118, 1, GRAY)
display.update()
ip_address = connect_wifi(WIFI_SSID, WIFI_PASSWORD)
if ip_address:
    server = start_server()

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
                                    record_game(scores, winner=scores.index(max(scores)))
                                    state = VICTORY
                            else:
                                flash_feedback(RED, False, "No match")
                                flipped = []
                                current_player = (current_player + 1) % num_players
                        dirty = True
    else:
        last_uid = None

    if server:
        poll_server(server, render_page)

    if dirty:
        refresh()
        dirty = False

    time.sleep_ms(150)