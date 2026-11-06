"""Procedurally generated SYNTHETIC road photos for the guided demo and tests.
They are illustrations, not real data."""
import random

from PIL import Image, ImageDraw, ImageFilter


def _asphalt(w, h, seed):
    rnd = random.Random(seed)
    img = Image.new("RGB", (w, h), (108, 108, 112))
    px = img.load()
    for _ in range(w * h // 3):
        x, y = rnd.randrange(w), rnd.randrange(h)
        v = rnd.randint(80, 140)
        px[x, y] = (v, v, v + 3)
    d = ImageDraw.Draw(img)
    d.rectangle([0, int(h * 0.9), w, h], fill=(150, 150, 140))      # kerb
    d.line([(0, int(h * 0.12)), (w, int(h * 0.12))], fill=(200, 200, 190), width=4)  # lane line
    return img


def pothole(path, seed=1, repaired=False, w=640, h=480, shift=0):
    img = _asphalt(w, h, seed)
    d = ImageDraw.Draw(img)
    cx, cy = w // 2 + shift, h // 2 + 20
    if not repaired:
        d.ellipse([cx - 95, cy - 55, cx + 95, cy + 55], fill=(55, 52, 50))
        d.ellipse([cx - 70, cy - 38, cx + 70, cy + 38], fill=(28, 26, 25))
        for _ in range(14):
            a = random.Random(seed + _).random() * 6.28
            d.line([(cx, cy), (cx + 130 * __import__("math").cos(a), cy + 80 * __import__("math").sin(a))],
                   fill=(70, 68, 66), width=2)
    else:
        d.ellipse([cx - 100, cy - 60, cx + 100, cy + 60], fill=(92, 92, 96))   # fresh patch
        d.ellipse([cx - 92, cy - 52, cx + 92, cy + 52], fill=(86, 86, 90))
    return img.filter(ImageFilter.GaussianBlur(0.6)).save(path, "JPEG", quality=88)


def garbage(path, seed=3, w=640, h=480):
    rnd = random.Random(seed)
    img = Image.new("RGB", (w, h), (120, 118, 110))
    d = ImageDraw.Draw(img)
    for _ in range(260):
        x, y = rnd.randrange(w), rnd.randrange(h // 3, h)
        s = rnd.randint(8, 34)
        col = (rnd.randint(30, 255), rnd.randint(30, 255), rnd.randint(30, 255))
        d.rectangle([x, y, x + s, y + rnd.randint(6, 24)], fill=col)
    img.save(path, "JPEG", quality=88)


def crack(path, seed=5, w=640, h=480):
    img = _asphalt(w, h, seed)
    d = ImageDraw.Draw(img)
    rnd = random.Random(seed)
    x, y = 40, rnd.randint(150, 330)
    for _ in range(40):
        nx, ny = x + rnd.randint(8, 30), y + rnd.randint(-22, 22)
        d.line([(x, y), (nx, ny)], fill=(25, 25, 25), width=3)
        x, y = nx, ny
    img.save(path, "JPEG", quality=88)
