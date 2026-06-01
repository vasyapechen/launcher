# -*- coding: utf-8 -*-
"""Генерация icon.ico для VasyaLauncher — взлетающая ракета с пламенем."""
from PIL import Image, ImageDraw

S = 1024  # суперсэмплинг для гладких краёв
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

def sc(*v):
    return [x * S / 1024 for x in v]

# Фон — скруглённый квадрат, тёмный, неоновая рамка
d.rounded_rectangle(sc(36, 36, 988, 988), radius=int(160*S/1024),
                    fill=(13, 16, 24, 255), outline=(255, 106, 0, 255), width=int(14*S/1024))
# Лёгкое свечение под ракетой (тёплое)
glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
gd.ellipse(sc(330, 700, 694, 980), fill=(255, 140, 0, 70))
from PIL import ImageFilter
glow = glow.filter(ImageFilter.GaussianBlur(40))
img.alpha_composite(glow)
d = ImageDraw.Draw(img)

cx = 512
# Пламя (3 слоя)
d.polygon(sc(440, 700, 584, 700, cx, 952), fill=(255, 68, 0, 255))
d.polygon(sc(464, 700, 560, 700, cx, 880), fill=(255, 174, 0, 255))
d.polygon(sc(486, 700, 538, 700, cx, 812), fill=(255, 242, 122, 255))

# Крылья
d.polygon(sc(430, 600, 326, 770, 430, 712), fill=(255, 42, 42, 255))
d.polygon(sc(594, 600, 698, 770, 594, 712), fill=(255, 42, 42, 255))

# Корпус (скруглённый вертикальный)
d.rounded_rectangle(sc(424, 300, 600, 720), radius=int(88*S/1024), fill=(238, 243, 255, 255))
# Левый блик
d.rounded_rectangle(sc(440, 330, 486, 690), radius=int(30*S/1024), fill=(255, 255, 255, 230))

# Нос (красный конус)
d.polygon(sc(424, 360, 600, 360, cx, 150), fill=(255, 42, 42, 255))

# Иллюминатор
d.ellipse(sc(454, 392, 570, 508), fill=(51, 194, 255, 255), outline=(13, 16, 24, 255), width=int(14*S/1024))
d.ellipse(sc(474, 408, 522, 456), fill=(190, 235, 255, 255))

# Звёздочки
for (x, y, r) in [(220, 250, 12), (820, 320, 16), (770, 640, 10), (250, 560, 9)]:
    d.ellipse(sc(x-r, y-r, x+r, y+r), fill=(255, 255, 255, 220))

# Финал: уменьшаем и сохраняем многоразмерный .ico
base = img.resize((256, 256), Image.LANCZOS)
base.save("icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
base.save("icon_preview.png")
print("icon.ico готов")
