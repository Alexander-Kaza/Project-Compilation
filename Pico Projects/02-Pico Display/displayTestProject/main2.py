import time
import random
from machine import Pin
from picographics import PicoGraphics, DISPLAY_PICO_DISPLAY, PEN_RGB332

# Initialize Pico Display (240x135)
display = PicoGraphics(display=DISPLAY_PICO_DISPLAY, pen_type=PEN_RGB332, rotate=0)
display.set_backlight(0.8)

# Board Dimensions (Standard Tetris scale optimized for screen height)
BOARD_WIDTH = 10
BOARD_HEIGHT = 15
BLOCK_SIZE = 8
X_OFFSET = 10   # Position where the board renders on screen
Y_OFFSET = 5

# Set up the physical buttons on the Display Pack
btn_a = Pin(12, Pin.IN, Pin.PULL_UP) # Top Left
btn_b = Pin(13, Pin.IN, Pin.PULL_UP) # Bottom Left
btn_x = Pin(14, Pin.IN, Pin.PULL_UP) # Top Right
btn_y = Pin(15, Pin.IN, Pin.PULL_UP) # Bottom Right

# Setup Colors
BLACK = display.create_pen(0, 0, 0)
WHITE = display.create_pen(255, 255, 255)
RED = display.create_pen(255, 0, 0)
BLUE = display.create_pen(0, 0, 255)
GREEN = display.create_pen(0, 255, 0)
YELLOW = display.create_pen(255, 255, 0)
CYAN = display.create_pen(0, 255, 255)
MAGENTA = display.create_pen(255, 0, 255)
ORANGE = display.create_pen(255, 165, 0)
GRAY = display.create_pen(50, 50, 50)

SHAPES = [
    [[1, 1, 1, 1]],                                 # I
    [[0, 1, 0], [1, 1, 1]],                         # T
    [[1, 1, 0], [0, 1, 1]],                         # Z
    [[0, 1, 1], [1, 1, 0]],                         # S
    [[1, 1], [1, 1]],                               # O
    [[1, 0, 0], [1, 1, 1]],                         # L
    [[0, 0, 1], [1, 1, 1]]                          # J
]
COLORS = [CYAN, MAGENTA, RED, GREEN, YELLOW, ORANGE, BLUE]

class Tetris:
    def __init__(self):
        self.board = [[0] * BOARD_WIDTH for _ in range(BOARD_HEIGHT)]
        self.score = 0
        self.game_over = False
        self.new_piece()

    def new_piece(self):
        self.piece_idx = random.randint(0, len(SHAPES) - 1)
        self.piece = SHAPES[self.piece_idx]
        self.color = COLORS[self.piece_idx]
        self.px = BOARD_WIDTH // 2 - len(self.piece[0]) // 2
        self.py = 0
        if self.check_collision(self.px, self.py, self.piece):
            self.game_over = True

    def check_collision(self, x, y, piece):
        for r, row in enumerate(piece):
            for c, val in enumerate(row):
                if val:
                    if (x + c < 0 or x + c >= BOARD_WIDTH or 
                        y + r >= BOARD_HEIGHT or 
                        (y + r >= 0 and self.board[y + r][x + c])):
                        return True
        return False

    def freeze(self):
        for r, row in enumerate(self.piece):
            for c, val in enumerate(row):
                if val and self.py + r >= 0:
                    self.board[self.py + r][self.px + c] = self.color
        self.clear_lines()
        self.new_piece()

    def clear_lines(self):
        new_board = [row for row in self.board if any(v == 0 for v in row)]
        cleared = BOARD_HEIGHT - len(new_board)
        self.score += cleared * 100
        while len(new_board) < BOARD_HEIGHT:
            new_board.insert(0, [0] * BOARD_WIDTH)
        self.board = new_board

    def move(self, dx):
        if not self.check_collision(self.px + dx, self.py, self.piece):
            self.px += dx

    def drop(self):
        if not self.check_collision(self.px, self.py + 1, self.piece):
            self.py += 1
        else:
            self.freeze()

    def rotate(self):
        rotated = [list(x) for x in zip(*self.piece[::-1])]
        if not self.check_collision(self.px, self.py, rotated):
            self.piece = rotated

    def draw(self):
        display.set_pen(BLACK)
        display.clear()
        
        # Border box
        display.set_pen(GRAY)
        display.rectangle(X_OFFSET - 2, Y_OFFSET - 2, BOARD_WIDTH * BLOCK_SIZE + 4, BOARD_HEIGHT * BLOCK_SIZE + 4)
        display.set_pen(BLACK)
        display.rectangle(X_OFFSET, Y_OFFSET, BOARD_WIDTH * BLOCK_SIZE, BOARD_HEIGHT * BLOCK_SIZE)

        # Draw resting board blocks
        for r in range(BOARD_HEIGHT):
            for c in range(BOARD_WIDTH):
                if self.board[r][c]:
                    display.set_pen(self.board[r][c])
                    display.rectangle(X_OFFSET + c * BLOCK_SIZE, Y_OFFSET + r * BLOCK_SIZE, BLOCK_SIZE - 1, BLOCK_SIZE - 1)

        # Draw active moving piece
        if not self.game_over:
            display.set_pen(self.color)
            for r, row in enumerate(self.piece):
                for c, val in enumerate(row):
                    if val and (self.py + r) >= 0:
                        display.rectangle(X_OFFSET + (self.px + c) * BLOCK_SIZE, Y_OFFSET + (self.py + r) * BLOCK_SIZE, BLOCK_SIZE - 1, BLOCK_SIZE - 1)

        # Score board text panel
        display.set_pen(WHITE)
        display.text("SCORE", 110, 10, scale=3)
        display.text(f"{self.score:05d}", 110, 30, scale=3)
        
        display.text("CONTROLS:", 110, 65, scale=2)
        display.text("X: Left  Y: Right", 110, 80, scale=2)
        display.text("A: Rotate B: Drop", 110, 95, scale=2)

        if self.game_over:
            display.set_pen(RED)
            display.text("GAME OVER", 110, 115, scale=3)

        display.update()

# Runtime Engine Engine
game = Tetris()
last_drop = time.ticks_ms()
drop_interval = 400 

while True:
    current_time = time.ticks_ms()
    
    # Process physical button inputs (Active Low: returns 0 when pressed)
    if not btn_x.value(): 
        game.move(-1)
        time.sleep(0.12)
    if not btn_y.value(): 
        game.move(1)
        time.sleep(0.12)
    if not btn_a.value(): 
        game.rotate()
        time.sleep(0.18)
    if not btn_b.value(): 
        game.drop()
        time.sleep(0.06)

    # Periodic fall clock tick
    if time.ticks_diff(current_time, last_drop) > drop_interval:
        if not game.game_over:
            game.drop()
        last_drop = current_time

    game.draw()
    time.sleep(0.01)
