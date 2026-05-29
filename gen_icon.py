"""Генератор значка лаунчера: буква V на тёмном фоне."""
from PIL import Image, ImageDraw, ImageFont

BG1 = (26, 26, 46)      # #1a1a2e
BG2 = (42, 42, 78)      # #2a2a4e
FG  = (235, 235, 248)   # почти белый

BASE = 256
img = Image.new("RGBA", (BASE, BASE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# Скруглённый квадрат с вертикальным градиентом
radius = 56
mask = Image.new("L", (BASE, BASE), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, BASE - 1, BASE - 1], radius=radius, fill=255)
grad = Image.new("RGBA", (BASE, BASE))
for y in range(BASE):
    t = y / (BASE - 1)
    r = int(BG1[0] + (BG2[0] - BG1[0]) * t)
    g = int(BG1[1] + (BG2[1] - BG1[1]) * t)
    b = int(BG1[2] + (BG2[2] - BG1[2]) * t)
    for x in range(BASE):
        grad.putpixel((x, y), (r, g, b, 255))
img.paste(grad, (0, 0), mask)
d = ImageDraw.Draw(img)

# Буква V по центру
try:
    font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 190)
except Exception:
    font = ImageFont.load_default()
text = "V"
bbox = d.textbbox((0, 0), text, font=font)
tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
x = (BASE - tw) / 2 - bbox[0]
y = (BASE - th) / 2 - bbox[1] - 6
d.text((x, y), text, font=font, fill=FG)

sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save("icon.ico", format="ICO", sizes=sizes)
print("icon.ico saved")
