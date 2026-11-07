import network
import socket
import time
import random
import json
import math
import machine
import plasma

# ------------------------------------------------------------
# GRID CONFIGURATION
# ------------------------------------------------------------
#
# The grid is 10 rows x 6 columns of "bricks". Each brick is
# made up of 4 LEDs. Each COLUMN of bricks is driven by its own
# physical LED strip, wired to its own GPIO pin.
#
# Right now only column 0 is wired up (the 50 LED strip you
# already have - the first 10 LEDs are skipped, then 40 LEDs are
# used for 10 bricks x 4 LEDs). To add another column, just plug the pin
# name in below - everything else works automatically.
# ------------------------------------------------------------

GRID_ROWS = 10
GRID_COLUMNS = 6
LEDS_PER_BRICK = 4
LED_START_OFFSET = 10

BRIGHTNESS = 1

# One entry per column: (pin_name, physical_led_count) or None
# if that strip isn't connected yet.

STRIP_CONFIG = [
    ("GP15", 50),          # column 0 - physical pin 1
    ("GP12", 50),          # column 1 - physical pin 2
    ("GP9", 50),          # column 2 - physical pin 4
    ("GP5", 50),          # column 3 - physical pin 5
    ("GP3", 50),          # column 4 - physical pin 6
    ("GP0", 50),          # column 5 - physical pin 7
]


# ------------------------------------------------------------
# LED STRIPS
# ------------------------------------------------------------

strips = [None] * GRID_COLUMNS

# The RP2040 has 2 PIO blocks, each with 4 state machines, so
# up to 8 WS2812 strips can run at once. We hand out a fresh
# pio/sm pair to each connected strip so they don't clash.

for column, config in enumerate(STRIP_CONFIG):

    if config is None:
        continue

    pin_name, led_count = config

    pio = column // 4
    sm = column % 4

    strip = plasma.WS2812(
        led_count,
        pio,
        sm,
        machine.Pin(pin_name),
        color_order=plasma.COLOR_ORDER_RGB
    )

    strip.start()

    strips[column] = strip

    print("Column", column, "connected on", pin_name)


# Virtual grid state, so /state can tell the browser what's
# currently lit without needing to ask the strips directly.
# None = off / unlit.

grid = [
    [None for _ in range(GRID_COLUMNS)]
    for _ in range(GRID_ROWS)
]


def hex_colour(r, g, b):
    return "#{:02x}{:02x}{:02x}".format(r, g, b)


def physical_column(column):
    # The strips are wired up mirrored left-right versus the on-screen
    # grid, so column 0 on screen is actually the rightmost strip.
    return GRID_COLUMNS - 1 - column


def set_brick(row, column, r, g, b):

    if not (0 <= row < GRID_ROWS and 0 <= column < GRID_COLUMNS):
        return False

    strip = strips[physical_column(column)]

    if strip is None:
        return False

    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))

    base = LED_START_OFFSET + (row * LEDS_PER_BRICK)

    for i in range(LEDS_PER_BRICK):

        strip.set_rgb(
            base + i,
            int(r * BRIGHTNESS),
            int(g * BRIGHTNESS),
            int(b * BRIGHTNESS)
        )

    if r == 0 and g == 0 and b == 0:
        grid[row][column] = None
    else:
        grid[row][column] = hex_colour(r, g, b)

    return True


def clear_grid():
    for row in range(GRID_ROWS):
        for column in range(GRID_COLUMNS):
            set_brick(row, column, 0, 0, 0)


def startup_column_test():
    test_colours = [
        (255, 0, 0),
        (255, 120, 0),
        (255, 255, 0),
        (0, 255, 0),
        (0, 120, 255),
        (180, 0, 255),
    ]

    clear_grid()

    for column in range(GRID_COLUMNS):
        if strips[physical_column(column)] is None:
            continue

        print("Testing column", column)

        for row in range(GRID_ROWS):
            set_brick(row, column, *test_colours[column])

        time.sleep_ms(500)
        clear_grid()


def fill_grid(r, g, b):
    for row in range(GRID_ROWS):
        for column in range(GRID_COLUMNS):
            set_brick(row, column, r, g, b)


def random_grid():
    for row in range(GRID_ROWS):
        for column in range(GRID_COLUMNS):
            set_brick(
                row,
                column,
                random.randint(0, 255),
                random.randint(0, 255),
                random.randint(0, 255)
            )


def hsv_to_rgb(h, s, v):

    # h in degrees (0-360), s and v in (0-1)

    c = v * s
    x = c * (1 - abs(((h / 60.0) % 2) - 1))
    m = v - c

    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x

    return (
        int((r + m) * 255),
        int((g + m) * 255),
        int((b + m) * 255)
    )


def rainbow_grid():

    total = GRID_ROWS * GRID_COLUMNS
    index = 0

    for row in range(GRID_ROWS):
        for column in range(GRID_COLUMNS):

            hue = (index / total) * 360
            r, g, b = hsv_to_rgb(hue, 1, 1)

            set_brick(row, column, r, g, b)

            index += 1


startup_column_test()


# ------------------------------------------------------------
# ANIMATIONS
#
# Each animation blocks for roughly ANIM_DURATION_MS, driving
# the strips directly frame by frame. That's fine here because
# the HTTP server already only deals with one client at a time -
# the browser's fetch() just waits a bit longer for the response.
# Grid is cleared to off once the animation finishes.
# ------------------------------------------------------------

ANIM_DURATION_MS = 10000


def now_ms():
    return time.ticks_ms()


def elapsed_ms(start):
    return time.ticks_diff(time.ticks_ms(), start)


def animate_rain(duration_ms=ANIM_DURATION_MS):

    # A falling drop per column. Colours are randomised between an
    # icy white (snow) and a cool blue (rain) each time a new drop
    # spawns, so it reads as a wintry rain/snow mix.

    clear_grid()

    drop_row = [None] * GRID_COLUMNS
    drop_colour = [None] * GRID_COLUMNS

    frame_delay = 150
    start = now_ms()

    while elapsed_ms(start) < duration_ms:

        for column in range(GRID_COLUMNS):

            if drop_row[column] is not None:
                set_brick(drop_row[column], column, 0, 0, 0)
                drop_row[column] += 1

                if drop_row[column] >= GRID_ROWS:
                    drop_row[column] = None

            if drop_row[column] is None and random.random() < 0.25:
                drop_row[column] = 0
                drop_colour[column] = (
                    (230, 230, 255) if random.random() < 0.5 else (60, 120, 255)
                )

        for column in range(GRID_COLUMNS):
            if drop_row[column] is not None:
                set_brick(drop_row[column], column, *drop_colour[column])

        time.sleep_ms(frame_delay)

    clear_grid()


# 5-row-tall block font, just enough letters for "HELLO WORLD".
# Each glyph is a list of row strings ('1' = lit). Unknown
# characters fall back to a blank space.

FONT_HEIGHT = 5

FONT = {
    "A": ["0110", "1001", "1111", "1001", "1001"],
    "B": ["1110", "1001", "1110", "1001", "1110"],
    "C": ["0111", "1000", "1000", "1000", "0111"],
    "D": ["1110", "1001", "1001", "1001", "1110"],
    "E": ["1111", "1000", "1110", "1000", "1111"],
    "F": ["1111", "1000", "1110", "1000", "1000"],
    "G": ["0111", "1000", "1011", "1001", "0111"],
    "H": ["1001", "1001", "1111", "1001", "1001"],
    "I": ["111", "010", "010", "010", "111"],
    "J": ["0111", "0010", "0010", "1010", "0100"],
    "K": ["1001", "1010", "1100", "1010", "1001"],
    "L": ["1000", "1000", "1000", "1000", "1111"],
    "M": ["10001", "11011", "10101", "10001", "10001"],
    "N": ["1001", "1101", "1101", "1011", "1001"],
    "O": ["0110", "1001", "1001", "1001", "0110"],
    "P": ["1110", "1001", "1110", "1000", "1000"],
    "Q": ["0110", "1001", "1001", "1011", "0111"],
    "R": ["1110", "1001", "1110", "1010", "1001"],
    "S": ["0111", "1000", "0110", "0001", "1110"],
    "T": ["111", "010", "010", "010", "010"],
    "U": ["1001", "1001", "1001", "1001", "0110"],
    "V": ["1001", "1001", "1001", "0110", "0110"],
    "W": ["1001", "1001", "1101", "1011", "1001"],
    "X": ["1001", "0110", "0110", "0110", "1001"],
    "Y": ["1001", "0110", "0110", "0010", "0010"],
    "Z": ["1111", "0010", "0100", "1000", "1111"],
    "0": ["0110", "1001", "1001", "1001", "0110"],
    "1": ["010", "110", "010", "010", "111"],
    "2": ["1111", "0001", "0111", "1000", "1111"],
    "3": ["1111", "0001", "0111", "0001", "1111"],
    "4": ["1001", "1001", "1111", "0001", "0001"],
    "5": ["1111", "1000", "1111", "0001", "1111"],
    "6": ["1111", "1000", "1111", "1001", "1111"],
    "7": ["1111", "0001", "0010", "0100", "0100"],
    "8": ["1111", "1001", "1111", "1001", "1111"],
    "9": ["1111", "1001", "1111", "0001", "1111"],
    "!": ["1", "1", "1", "0", "1"],
    "?": ["110", "001", "010", "000", "010"],
    " ": ["00", "00", "00", "00", "00"],
}


def build_text_bitmap(text):

    rows = ["" for _ in range(FONT_HEIGHT)]

    for character in text.upper():

        glyph = FONT.get(character, FONT[" "])

        for row in range(FONT_HEIGHT):
            rows[row] += glyph[row] + "0"  # 1 column gap after each letter

    return rows


def animate_scroll_text(text, duration_ms=ANIM_DURATION_MS, colour=(0, 220, 255)):

    clear_grid()

    bitmap = build_text_bitmap(text)
    width = len(bitmap[0])
    row_offset = (GRID_ROWS - FONT_HEIGHT) // 2

    # Scroll on from the right, all the way off to the left.
    total_frames = width + GRID_COLUMNS
    frame_delay = max(30, duration_ms // total_frames)

    start = now_ms()

    for frame in range(total_frames):

        if elapsed_ms(start) >= duration_ms:
            break

        offset = frame - GRID_COLUMNS

        for column in range(GRID_COLUMNS):

            bitmap_column = offset + column

            for font_row in range(FONT_HEIGHT):

                lit = (
                    0 <= bitmap_column < width
                    and bitmap[font_row][bitmap_column] == "1"
                )

                row = row_offset + font_row

                if lit:
                    set_brick(row, column, *colour)
                else:
                    set_brick(row, column, 0, 0, 0)

        time.sleep_ms(frame_delay)

    clear_grid()


def spiral_coordinates():

    coordinates = []

    top, bottom = 0, GRID_ROWS - 1
    left, right = 0, GRID_COLUMNS - 1

    while top <= bottom and left <= right:

        for column in range(left, right + 1):
            coordinates.append((top, column))
        top += 1

        for row in range(top, bottom + 1):
            coordinates.append((row, right))
        right -= 1

        if top <= bottom:
            for column in range(right, left - 1, -1):
                coordinates.append((bottom, column))
            bottom -= 1

        if left <= right:
            for row in range(bottom, top - 1, -1):
                coordinates.append((row, left))
            left += 1

    return coordinates


def animate_spiral(duration_ms=ANIM_DURATION_MS):

    clear_grid()

    coordinates = spiral_coordinates()
    step_delay = 40
    hue = 0

    start = now_ms()

    while elapsed_ms(start) < duration_ms:

        # Wind in, colour cycling as it goes.
        for row, column in coordinates:

            if elapsed_ms(start) >= duration_ms:
                break

            r, g, b = hsv_to_rgb(hue, 1, 1)
            set_brick(row, column, r, g, b)
            time.sleep_ms(step_delay)

        hue = (hue + 40) % 360

        # Unwind back to dark, same path.
        for row, column in coordinates:

            if elapsed_ms(start) >= duration_ms:
                break

            set_brick(row, column, 0, 0, 0)
            time.sleep_ms(step_delay)

    clear_grid()


# Sprite-based Pacman, matching the browser debug version.
SPRITE_WIDTH = 3
SPRITE_HEIGHT = 3

PACMAN_CLOSED = ["111", "111", "111"]
PACMAN_OPEN_RIGHT = ["111", "100", "111"]
PACMAN_OPEN_LEFT = ["111", "001", "111"]
GHOST_SHAPE = ["111", "111", "101"]


def draw_sprite(x, row_offset, bitmap, colour):

    for sprite_row in range(SPRITE_HEIGHT):
        for sprite_column in range(SPRITE_WIDTH):

            if bitmap[sprite_row][sprite_column] != "1":
                continue

            column = x + sprite_column

            if 0 <= column < GRID_COLUMNS:
                set_brick(row_offset + sprite_row, column, *colour)


def clear_rows(row_offset, height):

    for row in range(row_offset, row_offset + height):
        for column in range(GRID_COLUMNS):
            set_brick(row, column, 0, 0, 0)


def animate_pacman(duration_ms=ANIM_DURATION_MS):

    clear_grid()

    row_offset = (GRID_ROWS - SPRITE_HEIGHT) // 2
    gap = SPRITE_WIDTH + 1
    pacman_colour = (255, 255, 0)
    dead_ghost_colour = (130, 130, 255)
    red_ghost_colour = (255, 0, 0)
    off_left = -SPRITE_WIDTH
    off_right = GRID_COLUMNS
    frames = []

    # Phase 1: Pacman chases the dead ghost, moving right.
    for x in range(off_left, off_right + gap + 1):
        frames.append((x, x + gap, dead_ghost_colour, PACMAN_OPEN_RIGHT))

    # Phase 2: Pacman legs it back left, red ghost right behind.
    for x in range(off_right + gap, off_left - gap - 1, -1):
        frames.append((x - gap, x, red_ghost_colour, PACMAN_OPEN_LEFT))

    frame_delay = max(120, duration_ms // max(1, len(frames)))
    start = now_ms()

    for index, (pacman_x, ghost_x, ghost_colour, open_bitmap) in enumerate(frames):

        if elapsed_ms(start) >= duration_ms:
            break

        clear_rows(row_offset, SPRITE_HEIGHT)
        draw_sprite(ghost_x, row_offset, GHOST_SHAPE, ghost_colour)

        pacman_bitmap = PACMAN_CLOSED if index % 2 == 1 else open_bitmap
        draw_sprite(pacman_x, row_offset, pacman_bitmap, pacman_colour)

        time.sleep_ms(frame_delay)

    clear_grid()


def animate_pumpkin(duration_ms=ANIM_DURATION_MS):

    clear_grid()

    pumpkin = [
        "001100",
        "011110",
        "111111",
        "111111",
        "111111",
        "111111",
        "111111",
        "011110",
        "001100",
    ]
    laughing_faces = [
        ["000000", "010010", "000000", "001100", "011110", "001100"],
        ["000000", "010010", "001100", "011110", "011110", "000000"],
    ]
    row_offset = (GRID_ROWS - len(pumpkin)) // 2
    pumpkin_colour = (255, 100, 0)
    stem_colour = (40, 200, 30)
    face_colour = (80, 20, 0)
    frame_delay = 250
    start = now_ms()
    frame = 0

    while elapsed_ms(start) < duration_ms:
        clear_grid()

        for pumpkin_row, bitmap_row in enumerate(pumpkin):
            for column, pixel in enumerate(bitmap_row):
                if pixel == "1":
                    colour = stem_colour if pumpkin_row == 0 else pumpkin_colour
                    set_brick(row_offset + pumpkin_row, column, *colour)

        face = laughing_faces[frame % len(laughing_faces)]
        for face_row, bitmap_row in enumerate(face):
            for column, pixel in enumerate(bitmap_row):
                if pixel == "1":
                    set_brick(row_offset + 2 + face_row, column, *face_colour)

        time.sleep_ms(frame_delay)
        frame += 1

    clear_grid()


def animate_fireworks(duration_ms=ANIM_DURATION_MS):

    clear_grid()
    start = now_ms()

    while elapsed_ms(start) < duration_ms:

        launch_column = random.randint(0, GRID_COLUMNS - 1)
        burst_row = random.randint(1, max(1, GRID_ROWS // 3))
        hue = random.randint(0, 359)
        r, g, b = hsv_to_rgb(hue, 1, 1)

        for row in range(GRID_ROWS - 1, burst_row - 1, -1):

            if elapsed_ms(start) >= duration_ms:
                clear_grid()
                return

            set_brick(row + 1, launch_column, 0, 0, 0)
            set_brick(row, launch_column, 200, 200, 200)
            time.sleep_ms(35)

        set_brick(burst_row, launch_column, 0, 0, 0)

        for radius in range(3):

            if elapsed_ms(start) >= duration_ms:
                clear_grid()
                return

            brightness = 1.0 - (radius / 3)

            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):

                    if abs(dr) + abs(dc) != radius:
                        continue

                    row = burst_row + dr
                    column = launch_column + dc

                    if 0 <= row < GRID_ROWS and 0 <= column < GRID_COLUMNS:
                        set_brick(
                            row,
                            column,
                            int(r * brightness),
                            int(g * brightness),
                            int(b * brightness)
                        )

            time.sleep_ms(120)

        for radius in range(3):
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):

                    if abs(dr) + abs(dc) != radius:
                        continue

                    row = burst_row + dr
                    column = launch_column + dc

                    if 0 <= row < GRID_ROWS and 0 <= column < GRID_COLUMNS:
                        set_brick(row, column, 0, 0, 0)

        time.sleep_ms(200)

    clear_grid()


def animate_breathe(duration_ms=ANIM_DURATION_MS, colour=(0, 150, 255), period_ms=2400):

    start = now_ms()
    while elapsed_ms(start) < duration_ms:

        elapsed = elapsed_ms(start)
        phase = ((elapsed % period_ms) / period_ms) * 2 * math.pi
        brightness = (1 - math.cos(phase)) / 2

        for row in range(GRID_ROWS):
            for column in range(GRID_COLUMNS):
                set_brick(
                    row,
                    column,
                    int(colour[0] * brightness),
                    int(colour[1] * brightness),
                    int(colour[2] * brightness)
                )

        time.sleep_ms(40)

    clear_grid()


def animate_matrix_rain(duration_ms=ANIM_DURATION_MS):

    clear_grid()
    trail_length = 4
    base_colour = (0, 255, 70)
    head = [None] * GRID_COLUMNS
    start = now_ms()

    while elapsed_ms(start) < duration_ms:

        for column in range(GRID_COLUMNS):

            if head[column] is None:
                if random.random() < 0.2:
                    head[column] = 0
            else:
                head[column] += 1
                if head[column] - trail_length > GRID_ROWS:
                    head[column] = None

        for row in range(GRID_ROWS):
            for column in range(GRID_COLUMNS):

                if head[column] is None:
                    set_brick(row, column, 0, 0, 0)
                    continue

                distance = head[column] - row

                if distance < 0 or distance > trail_length:
                    set_brick(row, column, 0, 0, 0)
                else:
                    brightness = 1.0 if distance == 0 else 1.0 - (distance / trail_length)
                    set_brick(
                        row,
                        column,
                        int(base_colour[0] * brightness),
                        int(base_colour[1] * brightness),
                        int(base_colour[2] * brightness)
                    )

        time.sleep_ms(150)

    clear_grid()


IDLE_PAUSE_MS = 5000
IDLE_ANIMATIONS = [
    (animate_rain, ()),
    (animate_scroll_text, ("HI MADDIE",)),
    (animate_spiral, ()),
    (animate_pacman, ()),
    (animate_pumpkin, ()),
    (animate_fireworks, ()),
    (animate_breathe, ()),
    (animate_matrix_rain, ()),
]


# ------------------------------------------------------------
# WIFI ACCESS POINT
# ------------------------------------------------------------

SSID = "GlassBricks"
PASSWORD = "glassbricks"

IP = "192.168.4.1"
NETMASK = "255.255.255.0"

ap = network.WLAN(network.AP_IF)

ap.active(True)

time.sleep(1)

ap.config(
    essid=SSID,
    password=PASSWORD
)

time.sleep(1)

ap.ifconfig(
    (
        IP,
        NETMASK,
        IP,
        IP
    )
)

print()
print("==============================")
print("GLASS BRICKS")
print("==============================")
print()
print("Wi-Fi:", SSID)
print("Password:", PASSWORD)
print("IP:", IP)
print()


# ------------------------------------------------------------
# LOAD WEBSITE
# ------------------------------------------------------------

try:

    with open("index.html", "r") as f:
        html = f.read()

    print("index.html loaded")

except Exception as e:

    print("ERROR loading index.html:", e)

    html = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width">
<title>Glass Bricks</title>
</head>
<body>
<h1>Glass Bricks</h1>
<p>index.html could not be loaded.</p>
</body>
</html>
"""


# ------------------------------------------------------------
# DNS SERVER
# ------------------------------------------------------------

dns = socket.socket(
    socket.AF_INET,
    socket.SOCK_DGRAM
)

dns.setsockopt(
    socket.SOL_SOCKET,
    socket.SO_REUSEADDR,
    1
)

dns.bind(
    ("0.0.0.0", 53)
)

dns.setblocking(False)


def dns_reply(data):

    if len(data) < 12:
        return None

    transaction = data[0:2]
    flags = b"\x81\x80"
    questions = data[4:6]
    answers = b"\x00\x01"
    authority = b"\x00\x00"
    additional = b"\x00\x00"
    question = data[12:]

    answer = (
        b"\xc0\x0c"
        + b"\x00\x01"
        + b"\x00\x01"
        + b"\x00\x00\x00\x3c"
        + b"\x00\x04"
        + b"\xc0\xa8\x04\x01"
    )

    return (
        transaction
        + flags
        + questions
        + answers
        + authority
        + additional
        + question
        + answer
    )


print("DNS SERVER READY")


# ------------------------------------------------------------
# HTTP SERVER
# ------------------------------------------------------------

server = socket.socket(
    socket.AF_INET,
    socket.SOCK_STREAM
)

server.setsockopt(
    socket.SOL_SOCKET,
    socket.SO_REUSEADDR,
    1
)

server.bind(
    ("0.0.0.0", 80)
)

server.listen(4)

server.settimeout(0.5)

print("HTTP SERVER READY")
print("Captive portal enabled")
print("http://192.168.4.1")
print("Waiting for phones...")
print()


# ------------------------------------------------------------
# TURN LOCK
# ------------------------------------------------------------

TURN_SECONDS = 120
turn_lock_until = 0
turn_lock_owner = None


def turn_seconds_left():
    remaining = turn_lock_until - time.ticks_ms()
    return max(0, (remaining + 999) // 1000)


def turn_is_locked():
    return time.ticks_ms() < turn_lock_until


def turn_is_locked_for_session(session_id):
    # Session owns lock if lock is active AND this session is the owner
    if not turn_is_locked():
        return False
    return turn_lock_owner != session_id


def expire_turn_if_needed():
    global turn_lock_until, turn_lock_owner

    if turn_lock_owner is not None and not turn_is_locked():
        clear_grid()
        turn_lock_until = 0
        turn_lock_owner = None
        return True

    return False


def acquire_turn(session_id):
    global turn_lock_until, turn_lock_owner
    # Only acquire if this session doesn't already own it
    if session_id != turn_lock_owner:
        turn_lock_until = time.ticks_ms() + (TURN_SECONDS * 1000)
        turn_lock_owner = session_id
    return turn_seconds_left()


# ------------------------------------------------------------
# URL PARAMETER
# ------------------------------------------------------------

def parameter(query, name, default):

    parts = query.split("&")

    for part in parts:

        if "=" not in part:
            continue

        key, value = part.split("=", 1)

        if key == name:

            try:
                return int(value)

            except ValueError:
                return default

    return default


def parameter_str(query, name, default):
    # Extract string parameters (like session ID)
    parts = query.split("&")

    for part in parts:
        if "=" not in part:
            continue

        key, value = part.split("=", 1)
        if key == name:
            return value

    return default


# ------------------------------------------------------------
# HTTP RESPONSE
# ------------------------------------------------------------

def send_all(client, data):

    # MicroPython's socket.send() is not guaranteed to send every byte
    # in one call - for anything beyond a small packet it can silently
    # send only part of the data. Loop until it's all gone, or the
    # browser will sit waiting for bytes that never arrive.

    view = memoryview(data)
    sent_total = 0

    while sent_total < len(view):

        sent = client.send(view[sent_total:])

        if not sent:
            raise OSError("client closed connection mid-send")

        sent_total += sent


def response(
    client,
    body,
    content_type="text/html",
    status="200 OK"
):

    data = body.encode("utf-8")

    header = (
        "HTTP/1.1 "
        + status
        + "\r\n"
        + "Content-Type: "
        + content_type
        + "; charset=utf-8\r\n"
        + "Content-Length: "
        + str(len(data))
        + "\r\n"
        + "Cache-Control: no-store\r\n"
        + "Connection: close\r\n"
        + "\r\n"
    )

    send_all(client, header.encode("utf-8"))
    send_all(client, data)


def state_payload(session_id=None):
    expire_turn_if_needed()
    return json.dumps({
        "rows": GRID_ROWS,
        "columns": GRID_COLUMNS,
        "connected": [strips[physical_column(column)] is not None for column in range(GRID_COLUMNS)],
        "grid": grid,
        "turn_locked": turn_is_locked_for_session(session_id),
        "turn_seconds_left": turn_seconds_left(),
        "turn_seconds": TURN_SECONDS,
        "turn_owner": turn_lock_owner,  # Send who owns the lock
        "is_owner": session_id == turn_lock_owner,  # Is THIS session the owner?
    })


# ------------------------------------------------------------
# REQUEST HANDLERS
# ------------------------------------------------------------

def handle_brick(query, session_id):

    try:

        if turn_is_locked_for_session(session_id):
            return False

        row = parameter(query, "row", -1)
        column = parameter(query, "col", -1)
        r = parameter(query, "r", 0)
        g = parameter(query, "g", 0)
        b = parameter(query, "b", 0)

        print("BRICK:", row, column, "RGB:", r, g, b)

        acquire_turn(session_id)
        return set_brick(row, column, r, g, b)

    except Exception as e:

        print("BRICK ERROR:", e)
        return False


def handle_gridset(query, session_id):

    # Bulk update: "data" is GRID_ROWS row-strings joined by ".",
    # each row being GRID_COLUMNS 6-digit hex colours concatenated
    # together. Lets a whole board (e.g. a Tetris frame) be pushed
    # in a single request instead of one per brick.

    try:

        if turn_is_locked_for_session(session_id):
            return False

        data = parameter_str(query, "data", "")

        if not data:
            return False

        rows = data.split(".")

        if len(rows) != GRID_ROWS:
            return False

        acquire_turn(session_id)

        for row, row_data in enumerate(rows):

            if len(row_data) != GRID_COLUMNS * 6:
                continue

            for column in range(GRID_COLUMNS):

                hex_chunk = row_data[column * 6:(column * 6) + 6].lower()
                current = grid[row][column]

                # Most cells are unchanged frame-to-frame (only the moving
                # piece differs) - skip the LED write entirely for those,
                # instead of re-driving all 60 bricks on every single frame.
                if current == "#" + hex_chunk or (current is None and hex_chunk == "000000"):
                    continue

                r = int(hex_chunk[0:2], 16)
                g = int(hex_chunk[2:4], 16)
                b = int(hex_chunk[4:6], 16)

                set_brick(row, column, r, g, b)

        return True

    except Exception as e:

        print("GRIDSET ERROR:", e)
        return False


def handle_fill(query, session_id):

    try:

        if turn_is_locked_for_session(session_id):
            return False

        r = parameter(query, "r", 0)
        g = parameter(query, "g", 0)
        b = parameter(query, "b", 0)

        print("FILL:", r, g, b)

        acquire_turn(session_id)
        fill_grid(r, g, b)

        return True

    except Exception as e:

        print("FILL ERROR:", e)
        return False


# ------------------------------------------------------------
# MAIN LOOP
# ------------------------------------------------------------

idle_animation_index = 0
idle_next_animation_at = time.ticks_ms()

while True:

    expire_turn_if_needed()

    if (
        turn_lock_owner is None
        and time.ticks_diff(time.ticks_ms(), idle_next_animation_at) >= 0
    ):
        animation, arguments = IDLE_ANIMATIONS[idle_animation_index]
        idle_animation_index = (idle_animation_index + 1) % len(IDLE_ANIMATIONS)
        animation(*arguments)
        idle_next_animation_at = time.ticks_add(time.ticks_ms(), IDLE_PAUSE_MS)

    # --------------------------------------------------------
    # DNS
    # --------------------------------------------------------

    try:

        data, address = dns.recvfrom(512)
        reply = dns_reply(data)

        if reply:
            dns.sendto(reply, address)

    except OSError:
        pass

    except Exception as e:
        print("DNS ERROR:", e)


    # --------------------------------------------------------
    # HTTP
    # --------------------------------------------------------

    client = None

    try:

        client, address = server.accept()

        client.settimeout(3)

        request = client.recv(2048)

        if request:

            text = request.decode("utf-8", "ignore")

            first_line = text.split("\r\n", 1)[0]

            print("REQUEST:", first_line)

            parts = first_line.split(" ")

            if len(parts) >= 2:

                path = parts[1]
                query = path.split("?", 1)[1] if "?" in path else ""
                session_id = parameter_str(query, "sid", "unknown")


                # ------------------------------------------------
                # SINGLE BRICK
                # ------------------------------------------------

                if path.startswith("/brick?"):

                    if turn_is_locked_for_session(session_id):
                        response(client, json.dumps({
                            "locked": True,
                            "turn_seconds_left": turn_seconds_left(),
                        }), "application/json", "403 Forbidden")
                    elif handle_brick(query, session_id):
                        response(client, state_payload(session_id), "application/json")
                    else:
                        response(client, json.dumps({
                            "locked": True,
                            "turn_seconds_left": turn_seconds_left(),
                        }), "application/json", "400 Bad Request")


                # ------------------------------------------------
                # FILL WHOLE GRID
                # ------------------------------------------------

                elif path.startswith("/fill?"):

                    if turn_is_locked_for_session(session_id):
                        response(client, json.dumps({
                            "locked": True,
                            "turn_seconds_left": turn_seconds_left(),
                        }), "application/json", "403 Forbidden")
                    elif handle_fill(query, session_id):
                        response(client, state_payload(session_id), "application/json")
                    else:
                        response(client, json.dumps({
                            "locked": True,
                            "turn_seconds_left": turn_seconds_left(),
                        }), "application/json", "400 Bad Request")


                # ------------------------------------------------
                # BULK GRID UPDATE (e.g. Tetris frames)
                # ------------------------------------------------

                elif path.startswith("/gridset?"):

                    if turn_is_locked_for_session(session_id):
                        response(client, json.dumps({
                            "locked": True,
                            "turn_seconds_left": turn_seconds_left(),
                        }), "application/json", "403 Forbidden")
                    elif handle_gridset(query, session_id):
                        # The caller (Tetris) never reads this body - it already
                        # knows the board it just sent - so skip re-serialising
                        # the whole grid here, that's what was making every
                        # frame slow enough to fall visibly behind the screen.
                        response(client, "{\"ok\":true}", "application/json")
                    else:
                        response(client, json.dumps({
                            "locked": True,
                            "turn_seconds_left": turn_seconds_left(),
                        }), "application/json", "400 Bad Request")


                # ------------------------------------------------
                # CLEAR WHOLE GRID
                # ------------------------------------------------

                elif path.startswith("/clear"):

                    if turn_is_locked_for_session(session_id):
                        response(client, json.dumps({
                            "locked": True,
                            "turn_seconds_left": turn_seconds_left(),
                        }), "application/json", "403 Forbidden")
                    else:
                        acquire_turn(session_id)
                        clear_grid()
                        response(client, state_payload(session_id), "application/json")


                # ------------------------------------------------
                # RANDOM COLOURS
                # ------------------------------------------------

                elif path.startswith("/random"):

                    if turn_is_locked_for_session(session_id):
                        response(client, json.dumps({
                            "locked": True,
                            "turn_seconds_left": turn_seconds_left(),
                        }), "application/json", "403 Forbidden")
                    else:
                        acquire_turn(session_id)
                        random_grid()
                        response(client, state_payload(session_id), "application/json")


                # ------------------------------------------------
                # RAINBOW
                # ------------------------------------------------

                elif path.startswith("/rainbow"):

                    if turn_is_locked_for_session(session_id):
                        response(client, json.dumps({
                            "locked": True,
                            "turn_seconds_left": turn_seconds_left(),
                        }), "application/json", "403 Forbidden")
                    else:
                        acquire_turn(session_id)
                        rainbow_grid()
                        response(client, state_payload(session_id), "application/json")


                # ------------------------------------------------
                # CURRENT STATE
                # ------------------------------------------------

                elif path.startswith("/state"):

                    response(client, state_payload(session_id), "application/json")


                # ------------------------------------------------
                # PLAY (acquire turn)
                # ------------------------------------------------

                elif path.startswith("/play"):

                    if turn_is_locked_for_session(session_id):
                        response(client, state_payload(session_id), "application/json", "403 Forbidden")
                    else:
                        acquire_turn(session_id)
                        response(client, state_payload(session_id), "application/json")


                # ------------------------------------------------
                # AUTO-CLEAR (called when timer reaches 0)
                # ------------------------------------------------

                elif path.startswith("/autoclear"):

                    expire_turn_if_needed()
                    response(client, state_payload(session_id), "application/json")


                # ------------------------------------------------

                elif path.startswith("/anim/rain"):

                    if turn_is_locked_for_session(session_id):
                        response(client, json.dumps({
                            "locked": True,
                            "turn_seconds_left": turn_seconds_left(),
                        }), "application/json", "403 Forbidden")
                    else:
                        acquire_turn(session_id)
                        animate_rain()
                        response(client, state_payload(session_id), "application/json")

                elif path.startswith("/anim/scroll"):

                    if turn_is_locked_for_session(session_id):
                        response(client, json.dumps({
                            "locked": True,
                            "turn_seconds_left": turn_seconds_left(),
                        }), "application/json", "403 Forbidden")
                    else:
                        acquire_turn(session_id)
                        animate_scroll_text("HI MADDIE")
                        response(client, state_payload(session_id), "application/json")

                elif path.startswith("/anim/spiral"):

                    if turn_is_locked_for_session(session_id):
                        response(client, json.dumps({
                            "locked": True,
                            "turn_seconds_left": turn_seconds_left(),
                        }), "application/json", "403 Forbidden")
                    else:
                        acquire_turn(session_id)
                        animate_spiral()
                        response(client, state_payload(session_id), "application/json")

                elif path.startswith("/anim/pacman"):

                    if turn_is_locked_for_session(session_id):
                        response(client, json.dumps({
                            "locked": True,
                            "turn_seconds_left": turn_seconds_left(),
                        }), "application/json", "403 Forbidden")
                    else:
                        acquire_turn(session_id)
                        animate_pacman()
                        response(client, state_payload(session_id), "application/json")

                elif path.startswith("/anim/pumpkin"):

                    if turn_is_locked_for_session(session_id):
                        response(client, json.dumps({
                            "locked": True,
                            "turn_seconds_left": turn_seconds_left(),
                        }), "application/json", "403 Forbidden")
                    else:
                        acquire_turn(session_id)
                        animate_pumpkin()
                        response(client, state_payload(session_id), "application/json")

                elif path.startswith("/anim/fireworks"):

                    if turn_is_locked_for_session(session_id):
                        response(client, json.dumps({
                            "locked": True,
                            "turn_seconds_left": turn_seconds_left(),
                        }), "application/json", "403 Forbidden")
                    else:
                        acquire_turn(session_id)
                        animate_fireworks()
                        response(client, state_payload(session_id), "application/json")

                elif path.startswith("/anim/breathe"):

                    if turn_is_locked_for_session(session_id):
                        response(client, json.dumps({
                            "locked": True,
                            "turn_seconds_left": turn_seconds_left(),
                        }), "application/json", "403 Forbidden")
                    else:
                        acquire_turn(session_id)
                        animate_breathe()
                        response(client, state_payload(session_id), "application/json")

                elif path.startswith("/anim/matrix"):

                    if turn_is_locked_for_session(session_id):
                        response(client, json.dumps({
                            "locked": True,
                            "turn_seconds_left": turn_seconds_left(),
                        }), "application/json", "403 Forbidden")
                    else:
                        acquire_turn(session_id)
                        animate_matrix_rain()
                        response(client, state_payload(session_id), "application/json")

                # ------------------------------------------------
                # DIRECT LOCAL PAGE ONLY
                # ------------------------------------------------
                #
                # This is intentionally not a captive portal. The AP is a
                # normal Wi‑Fi network. Users connect to it and then open
                # the page directly via the local IP or QR code.
                # ------------------------------------------------

                else:
                    if path in ("/", "/index.html"):
                        response(client, html, "text/html")
                    else:
                        response(client, "Not found", "text/plain", "404 Not Found")

    except OSError:
        pass

    except Exception as e:
        print("HTTP ERROR:", e)

    finally:

        if client is not None:

            try:
                client.close()

            except Exception:
                pass


    time.sleep_ms(10)
