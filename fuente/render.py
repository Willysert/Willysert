"""Render AXIS Dental Studio WhatsApp status video (1080x1920, 9:16).
Usage: python3 -I render.py <source_video> <flyer_dir> <out_mp4> [preview_times...]
"""
import sys, subprocess, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

SRC, FLY, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
PREVIEW = [float(x) for x in sys.argv[4:]]
W, H, FPS = 1080, 1920, 30
FONT = "/usr/share/fonts/opentype/inter/InterDisplay-Black.otf"
VOICE_END = 22.6

# ---------- helpers ----------
def ease_out_back(x, s=1.4):
    x = min(max(x, 0), 1); x -= 1
    return x * x * ((s + 1) * x + s) + 1
def ease_out(x):
    x = min(max(x, 0), 1); return 1 - (1 - x) ** 3
def ease_in(x):
    x = min(max(x, 0), 1); return x ** 3

def cover(img, w, h):
    r = max(w / img.width, h / img.height)
    im = img.resize((math.ceil(img.width * r), math.ceil(img.height * r)), Image.LANCZOS)
    l, t = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((l, t, l + w, t + h))

def bg_from(img, dark=0.45):
    b = cover(img.convert("RGB"), W // 4, H // 4).filter(ImageFilter.GaussianBlur(6))
    b = b.resize((W, H), Image.BILINEAR)
    a = np.asarray(b).astype(np.float32) * dark
    tint = np.array([60, 40, 28], np.float32)  # warm brand brown
    a = a * 0.75 + tint * 0.25
    return Image.fromarray(a.clip(0, 255).astype(np.uint8))

def round_mask(w, h, r):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
    return m

SHADOW_CACHE = {}
def shadow(w, h, r):
    k = (w, h)
    if k not in SHADOW_CACHE:
        pad = 120
        s = Image.new("L", (w + pad * 2, h + pad * 2), 0)
        ImageDraw.Draw(s).rounded_rectangle((pad, pad + 30, pad + w, pad + h + 30), r, fill=170)
        SHADOW_CACHE[k] = (s.filter(ImageFilter.GaussianBlur(45)), pad)
    return SHADOW_CACHE[k]

WORD_CACHE = {}
def word_strip(word, size, outline):
    k = (word, size, outline)
    if k not in WORD_CACHE:
        f = ImageFont.truetype(FONT, size)
        txt = (word + "  ·  ") * 4
        bbox = f.getbbox(txt)
        im = Image.new("L", (bbox[2] + 20, bbox[3] + 20), 0)
        d = ImageDraw.Draw(im)
        if outline:
            d.text((10, 0), txt, font=f, fill=0, stroke_width=4, stroke_fill=255)
        else:
            d.text((10, 0), txt, font=f, fill=255)
        unit = f.getlength(word + "  ·  ")
        WORD_CACHE[k] = (im, unit)
    return WORD_CACHE[k]

def draw_depth_words(canvas, word, t, color=(245, 228, 205)):
    """Three marquee rows of giant text at different speeds = parallax depth."""
    rows = [  # y, size, speed px/s, opacity, outline, direction
        (90, 260, 70, 0.22, False, -1),
        (720, 420, 140, 0.30, False, 1),
        (1500, 300, 95, 0.35, True, -1),
    ]
    for y, size, speed, op, outline, d in rows:
        strip, unit = word_strip(word, size, outline)
        off = (t * speed * d) % unit
        x = int(-unit + off) if d > 0 else int(-off)
        alpha = strip.point(lambda v, o=op: int(v * o))
        col = Image.new("RGB", strip.size, color)
        canvas.paste(col, (x, y), alpha)

def place_card(canvas, card, cx, cy, scale, radius=34):
    w, h = int(card.width * scale), int(card.height * scale)
    c = card.resize((w, h), Image.BILINEAR)
    sh, pad = shadow(w // 8 * 8, h // 8 * 8, radius)
    sh = sh.resize((w + pad * 2, h + pad * 2))
    x, y = int(cx - w / 2), int(cy - h / 2)
    canvas.paste((0, 0, 0), (x - pad, y - pad), sh)
    canvas.paste(c, (x, y), round_mask(w, h, radius))
    return x, y, w, h

def light_sweep(canvas, box, p):
    """Diagonal glossy shine moving across the card."""
    if not 0 < p < 1: return
    x, y, w, h = box
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    cx = -w * 0.6 + p * w * 2.2
    d.polygon([(cx, 0), (cx + 140, 0), (cx + 140 - h * 0.35, h), (cx - h * 0.35, h)], fill=70)
    m = m.filter(ImageFilter.GaussianBlur(30))
    m = Image.composite(m, Image.new("L", (w, h), 0), round_mask(w, h, 34))
    canvas.paste((255, 255, 255), (x, y), m)

# ---------- assets ----------
fly = {k: Image.open(f"{FLY}/{k}.jpg").convert("RGB") for k in ("horario", "serv1", "serv2", "agenda")}
# service button boxes in flyer pixel coords (1024x1280)
BTN = [(262, 418, 762, 503), (262, 531, 762, 616), (262, 645, 762, 730), (262, 758, 762, 843), (262, 871, 762, 957)]

# ---------- timeline ----------
# (key, start, dur, depth word)
FLYER_SCENES = [
    ("serv1", VOICE_END, 4.3, "SONRISA"),
    ("serv2", VOICE_END + 4.3, 4.3, "CUIDADO"),
    ("horario", VOICE_END + 8.6, 3.6, "HORARIO"),
    ("agenda", VOICE_END + 12.2, 4.4, "HOY"),
]
TOTAL = VOICE_END + 16.6
VIDEO_WORDS = [(0, "AXIS"), (7.6, "CONFIANZA"), (16.0, "SONRISA")]
NF = int(TOTAL * FPS)

# source video frames
probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "csv=p=0", SRC], capture_output=True, text=True)
sw, sh_ = map(int, probe.stdout.strip().split(","))
dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", SRC, "-vf", f"fps={FPS}", "-f", "rawvideo",
                        "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
fsize = sw * sh_ * 3
last_src = None
def next_src():
    global last_src
    b = dec.stdout.read(fsize)
    if len(b) == fsize:
        last_src = Image.frombytes("RGB", (sw, sh_), b)
    return last_src

FLY_BG = {k: bg_from(v) for k, v in fly.items()}

def video_frame(t, src):
    canvas = bg_from(src, 0.40)
    word = [w for s, w in VIDEO_WORDS if t >= s][-1]
    draw_depth_words(canvas, word, t)
    # card intro: zoom from full-screen into floating card during first 0.9s
    p = ease_out(t / 0.9)
    base = 0.80 + (1.0 - 0.80) * 0  # card width fraction
    target_w = W * 0.74
    full_w = W * 1.02
    cw = full_w + (target_w - full_w) * p
    scale = cw / src.width * (1 + 0.015 * math.sin(t * 1.3))
    cy = H / 2 + 14 * math.sin(t * 0.9)
    place_card(canvas, src, W / 2, cy, scale, radius=int(34 * p) + 1)
    # outro: card flies up & fades into flash
    return canvas

def flyer_frame(key, lt, dur, word, gt):
    img = fly[key]
    canvas = FLY_BG[key].copy()
    draw_depth_words(canvas, word, gt)
    target_w = W * (0.80 if key == "horario" else 0.84)
    if key == "horario":
        target_w = min(target_w, H * 0.80 * img.width / img.height)
    s_in = ease_out_back(lt / 0.7)
    s_out = ease_in((lt - (dur - 0.35)) / 0.35) if key != "agenda" else 0
    scale = target_w / img.width * (0.86 + 0.14 * s_in) * (1 + 0.025 * lt / dur) * (1 + 0.1 * s_out)
    cy = H / 2 + (1 - ease_out(lt / 0.7)) * 500 - s_out * 1400 + 10 * math.sin(gt * 1.1)
    # service highlights drawn onto a copy of the flyer
    card = img
    if key in ("serv1", "serv2"):
        card = img.copy()
        step = (dur - 0.9) / len(BTN)
        i = int((lt - 0.6) / step) if lt >= 0.6 else -1
        if 0 <= i < len(BTN):
            k = (lt - 0.6 - i * step) / step
            e = math.sin(math.pi * min(k * 1.3, 1))
            x0, y0, x1, y1 = BTN[i]
            g = 4 + int(8 * e)
            glow = Image.new("L", card.size, 0)
            ImageDraw.Draw(glow).rounded_rectangle((x0 - g, y0 - g, x1 + g, y1 + g), 22, outline=int(255 * e), width=10)
            card.paste((235, 196, 140), (0, 0), glow.filter(ImageFilter.GaussianBlur(9)))
            ring = Image.new("L", card.size, 0)
            ImageDraw.Draw(ring).rounded_rectangle((x0 - 3, y0 - 3, x1 + 3, y1 + 3), 20, outline=int(255 * e), width=4)
            card.paste((250, 225, 185), (0, 0), ring)
    box = place_card(canvas, card, W / 2, cy, scale)
    light_sweep(canvas, box, (lt - 0.5) / 1.1)
    if key == "agenda":
        # pulsing call-to-action ring under the card
        p = (lt % 1.2) / 1.2
        x, y, w, h = box
        r = 40 + 60 * p
        ring = Image.new("L", (W, H), 0)
        cxr, cyr = W / 2, y + h + 110
        ImageDraw.Draw(ring).ellipse((cxr - r, cyr - r * 0.45, cxr + r, cyr + r * 0.45), outline=int(200 * (1 - p)), width=5)
        canvas.paste((245, 228, 205), (0, 0), ring)
        f = ImageFont.truetype(FONT, 46)
        d = ImageDraw.Draw(canvas)
        msg = "¡Escríbenos por WhatsApp!"
        d.text((W / 2, cyr), msg, font=f, fill=(255, 245, 230), anchor="mm")
    return canvas

def flash(canvas, t):
    """White-warm flash around the video->flyer cut."""
    d = abs(t - VOICE_END)
    if d < 0.25:
        a = int(255 * (1 - d / 0.25) * 0.85)
        canvas.paste((255, 244, 230), (0, 0), Image.new("L", (W, H), a))
    return canvas

def frame_at(i, src):
    t = i / FPS
    if t < VOICE_END:
        c = video_frame(t, src)
    else:
        for key, s, dur, word in FLYER_SCENES:
            if s <= t < s + dur:
                c = flyer_frame(key, t - s, dur, word, t); break
        else:
            key, s, dur, word = FLYER_SCENES[-1]
            c = flyer_frame(key, t - s, dur, word, t)
    c = flash(c, t)
    # final fade to black last 0.5s
    if t > TOTAL - 0.5:
        a = int(255 * (t - (TOTAL - 0.5)) / 0.5)
        c.paste((0, 0, 0), (0, 0), Image.new("L", (W, H), a))
    return c

if PREVIEW:
    for pt in PREVIEW:
        fi = int(pt * FPS)
        src = None
        for _ in range(min(fi, int(VOICE_END * FPS) - 1) + 1):
            src = next_src()
        frame_at(fi, src).save(f"{OUT}_{pt:05.2f}.jpg", quality=85)
        dec.kill()
        dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", SRC, "-vf", f"fps={FPS}", "-f", "rawvideo",
                                "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    sys.exit()

enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                        "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                        "-pix_fmt", "yuv420p", OUT], stdin=subprocess.PIPE)
for i in range(NF):
    src = next_src() if i / FPS < VOICE_END + 0.1 else last_src
    enc.stdin.write(frame_at(i, src).tobytes())
    if i % 150 == 0: print(f"frame {i}/{NF}", flush=True)
enc.stdin.close(); enc.wait(); dec.kill()
print("done", TOTAL)
