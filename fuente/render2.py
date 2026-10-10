"""AXIS Dental Studio - WhatsApp status v2 (full screen, text behind people).
Usage: python3 -I render2.py <models_dir> <source_video> <flyer_dir> <out_mp4> [preview_times...]
"""
import sys, subprocess, math
import numpy as np
import onnxruntime as ort
from PIL import Image, ImageDraw, ImageFont, ImageFilter

MODELS, SRC, FLY, OUT = sys.argv[1:5]
PREVIEW = [float(x) for x in sys.argv[5:]]
W, H, FPS = 1080, 1920, 30
FONT = "/usr/share/fonts/opentype/inter/InterDisplay-Black.otf"
VOICE_END = 22.6
CREAM = (247, 236, 220)

def ease_out(x):
    x = min(max(x, 0), 1); return 1 - (1 - x) ** 3
def ease_in(x):
    x = min(max(x, 0), 1); return x ** 3

# ---------- person segmentation ----------
sess = ort.InferenceSession(f"{MODELS}/u2net_human_seg.onnx", providers=["CPUExecutionProvider"])
MEAN, STD = np.array([0.485, 0.456, 0.406], np.float32), np.array([0.229, 0.224, 0.225], np.float32)
def person_mask(img):
    x = np.asarray(img.resize((320, 320), Image.BILINEAR), np.float32) / 255.
    x = ((x - MEAN) / STD).transpose(2, 0, 1)[None].astype(np.float32)
    o = sess.run(None, {sess.get_inputs()[0].name: x})[0][0, 0]
    o = (o - o.min()) / (o.max() - o.min() + 1e-8)
    return np.clip((o - 0.25) / 0.5, 0, 1)  # 320x320 float

# ---------- depth words ----------
WORDS = [(0.0, "AXIS"), (7.6, "CONFIANZA"), (16.0, "SONRISA")]
WORD_IMG = {}
def word_layer(word):
    if word not in WORD_IMG:
        size = 600
        f = ImageFont.truetype(FONT, size)
        while f.getlength(word) > W * 0.94:
            size -= 10; f = ImageFont.truetype(FONT, size)
        bb = f.getbbox(word)
        im = Image.new("L", (bb[2] - bb[0] + 40, bb[3] - bb[1] + 40), 0)
        ImageDraw.Draw(im).text((20 - bb[0], 20 - bb[1]), word, font=f, fill=255)
        WORD_IMG[word] = im
    return WORD_IMG[word]

def draw_word(canvas, t):
    idx = max(i for i, (s, _) in enumerate(WORDS) if t >= s)
    start, word = WORDS[idx]
    end = WORDS[idx + 1][0] if idx + 1 < len(WORDS) else VOICE_END
    lt, dur = t - start, end - start
    base = word_layer(word)
    p_in = ease_out(lt / 0.8)
    p_out = ease_in((lt - (dur - 0.35)) / 0.35)
    scale = 1.0 + 0.07 * (lt / dur)  # slow push-in
    im = base.resize((int(base.width * scale), int(base.height * scale)), Image.BILINEAR)
    op = 0.92 * p_in * (1 - p_out)
    cx = W / 2
    cy = 640 + (1 - p_in) * 140 - p_out * 80
    x, y = int(cx - im.width / 2), int(cy - im.height / 2)
    # soft shadow for legibility on bright walls
    sh = im.filter(ImageFilter.GaussianBlur(18)).point(lambda v: int(v * 0.35 * op))
    canvas.paste((40, 25, 15), (x + 6, y + 14), sh)
    canvas.paste(CREAM, (x, y), im.point(lambda v: int(v * op)))

# ---------- flyers (full screen) ----------
def cover(img, w, h):
    r = max(w / img.width, h / img.height)
    im = img.resize((math.ceil(img.width * r), math.ceil(img.height * r)), Image.LANCZOS)
    l, t = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((l, t, l + w, t + h)), r, l, t

fly, fly_map = {}, {}
for k in ("serv1", "serv2", "horario", "agenda"):
    im, r, l, t = cover(Image.open(f"{FLY}/{k}.jpg").convert("RGB"), W, H)
    fly[k] = im; fly_map[k] = (r, l, t)
BTN = [(262, 418, 762, 503), (262, 531, 762, 616), (262, 645, 762, 730), (262, 758, 762, 843), (262, 871, 762, 957)]
PHONE = (370, 1100, 710, 1160)  # in agenda flyer coords
def map_box(k, b):
    r, l, t = fly_map[k]
    return tuple(int(v * r - (l if i % 2 == 0 else t)) for i, v in enumerate(b))

SCENES = [("serv1", 4.3), ("serv2", 4.3), ("horario", 3.6), ("agenda", 4.4)]
starts, acc = [], VOICE_END
for k, d in SCENES:
    starts.append((k, acc, d)); acc += d
TOTAL = acc

def zoomed(img, z, dy=0):
    if z == 1 and dy == 0: return img.copy()
    w, h = int(W * z), int(H * z)
    im = img.resize((w, h), Image.BILINEAR)
    l, t = (w - W) // 2, (h - H) // 2 - int(dy)
    return im.crop((l, t, l + W, t + H))

def flyer_frame(k, lt, dur):
    z = 1.10 - 0.10 * ease_out(lt / 0.6) + 0.03 * (lt / dur)  # punch-in then slow push
    card = fly[k].copy()
    d = ImageDraw.Draw(card)
    if k in ("serv1", "serv2"):
        step = (dur - 0.9) / len(BTN)
        i = int((lt - 0.6) / step) if lt >= 0.6 else -1
        if 0 <= i < len(BTN):
            e = math.sin(math.pi * min((lt - 0.6 - i * step) / step * 1.3, 1))
            x0, y0, x1, y1 = map_box(k, BTN[i])
            g = 6 + int(10 * e)
            glow = Image.new("L", (W, H), 0)
            ImageDraw.Draw(glow).rounded_rectangle((x0 - g, y0 - g, x1 + g, y1 + g), 30, outline=int(255 * e), width=14)
            card.paste((235, 196, 140), (0, 0), glow.filter(ImageFilter.GaussianBlur(12)))
            ring = Image.new("L", (W, H), 0)
            ImageDraw.Draw(ring).rounded_rectangle((x0 - 4, y0 - 4, x1 + 4, y1 + 4), 28, outline=int(255 * e), width=5)
            card.paste((250, 225, 185), (0, 0), ring)
    if k == "agenda":
        p = (lt % 1.2) / 1.2
        x0, y0, x1, y1 = map_box(k, PHONE)
        g = int(10 + 50 * p)
        ring = Image.new("L", (W, H), 0)
        ImageDraw.Draw(ring).rounded_rectangle((x0 - g, y0 - g, x1 + g, y1 + g), 60, outline=int(220 * (1 - p)), width=5)
        card.paste(CREAM, (0, 0), ring)
    # glossy light sweep
    p = (lt - 0.4) / 1.2
    if 0 < p < 1:
        m = Image.new("L", (W, H), 0)
        cx = -W * 0.6 + p * W * 2.4
        ImageDraw.Draw(m).polygon([(cx, 0), (cx + 220, 0), (cx + 220 - H * 0.4, H), (cx - H * 0.4, H)], fill=55)
        card.paste((255, 255, 255), (0, 0), m.filter(ImageFilter.GaussianBlur(40)))
    return zoomed(card, z)

# ---------- source video ----------
probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "csv=p=0", SRC], capture_output=True, text=True)
sw, sh_ = map(int, probe.stdout.strip().split(","))
def open_dec():
    return subprocess.Popen(["ffmpeg", "-v", "error", "-i", SRC, "-vf", f"fps={FPS},scale={W}:{H}:flags=lanczos",
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
dec = open_dec()
state = {"img": None, "mask": None, "small": None}
def next_src():
    b = dec.stdout.read(W * H * 3)
    if len(b) < W * H * 3: return state["img"], state["mask"]
    img = Image.frombytes("RGB", (W, H), b)
    m = person_mask(img)
    small = np.asarray(img.resize((64, 112)), np.float32)
    if state["mask"] is not None and np.abs(small - state["small"]).mean() < 18:  # same shot: smooth flicker
        m = 0.55 * m + 0.45 * state["mask_raw"]
    state.update(img=img, small=small, mask_raw=m)
    ml = Image.fromarray((m * 255).astype(np.uint8)).resize((W, H), Image.BILINEAR).filter(ImageFilter.GaussianBlur(2))
    state["mask"] = ml
    return img, ml

def video_frame(t, img, mask):
    canvas = img.copy()
    draw_word(canvas, t)
    canvas.paste(img, (0, 0), mask)  # people back on top -> text sits behind them
    return canvas

def flash(c, t):
    d = abs(t - VOICE_END)
    for k, s, dur in starts[1:]:
        d = min(d, abs(t - s) * 1.6)
    if d < 0.22:
        c.paste((255, 244, 230), (0, 0), Image.new("L", (W, H), int(255 * 0.8 * (1 - d / 0.22))))
    return c

def frame_at(i, img, mask):
    t = i / FPS
    if t < VOICE_END:
        c = video_frame(t, img, mask)
    else:
        for k, s, dur in starts:
            if s <= t < s + dur: break
        c = flyer_frame(k, t - s, dur)
    c = flash(c, t)
    if t > TOTAL - 0.5:
        c.paste((0, 0, 0), (0, 0), Image.new("L", (W, H), int(255 * (t - (TOTAL - 0.5)) / 0.5)))
    return c

if PREVIEW:
    for pt in PREVIEW:
        dec.kill(); dec = open_dec(); state.update(img=None, mask=None)
        fi = int(pt * FPS); img = mask = None
        for _ in range(min(fi, int(VOICE_END * FPS) - 1) + 1):
            b = dec.stdout.read(W * H * 3)
        if fi < VOICE_END * FPS:
            img = Image.frombytes("RGB", (W, H), b)
            m = person_mask(img)
            mask = Image.fromarray((m * 255).astype(np.uint8)).resize((W, H), Image.BILINEAR)
        frame_at(fi, img, mask).save(f"{OUT}_{pt:05.2f}.jpg", quality=85)
    dec.kill(); sys.exit()

enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                        "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                        "-pix_fmt", "yuv420p", OUT], stdin=subprocess.PIPE)
NF = int(TOTAL * FPS)
img = mask = None
for i in range(NF):
    if i / FPS < VOICE_END:
        img, mask = next_src()
    enc.stdin.write(frame_at(i, img, mask).tobytes())
    if i % 150 == 0: print(f"frame {i}/{NF}", flush=True)
enc.stdin.close(); enc.wait(); dec.kill()
print("done", TOTAL)
