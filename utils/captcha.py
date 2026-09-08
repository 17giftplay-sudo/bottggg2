import io
import secrets
import random
from PIL import Image, ImageDraw, ImageFont

from config import CAPTCHA_LENGTH

# مسارات الخط — يجرب بالترتيب حتى يجد واحداً متاحاً
_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",  # macOS
    "C:/Windows/Fonts/arialbd.ttf",          # Windows
]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    # آخر ملاذ: الخط الافتراضي مع حجم كبير (Pillow >= 10)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def generate_captcha() -> tuple[str, io.BytesIO]:
    code = "".join([str(secrets.randbelow(10)) for _ in range(CAPTCHA_LENGTH)])

    width, height = 360, 110
    bg_color = (248, 249, 252)

    img  = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)

    # إطار أنيق
    draw.rounded_rectangle(
        [(2, 2), (width - 3, height - 3)],
        radius=12,
        outline=(180, 195, 215),
        width=2,
    )

    # خطوط خلفية خفيفة جداً (لا تعيق القراءة)
    for _ in range(4):
        x1, x2 = random.randint(0, width), random.randint(0, width)
        shade = random.randint(210, 230)
        draw.line([(x1, 0), (x2, height)], fill=(shade, shade, shade + 10), width=1)

    # ألوان واضحة لكل رقم
    digit_colors = [
        (200, 30,  30),   # أحمر
        (20,  100, 200),  # أزرق
        (20,  150, 60),   # أخضر
        (190, 80,  10),   # برتقالي
        (110, 30,  190),  # بنفسجي
    ]

    font_size  = 58
    char_width = width // (CAPTCHA_LENGTH + 1)

    for i, char in enumerate(code):
        font  = _load_font(font_size)
        color = digit_colors[i % len(digit_colors)]

        # ارسم كل رقم في طبقة شفافة منفصلة للدوران
        char_img  = Image.new("RGBA", (char_width, height), (0, 0, 0, 0))
        char_draw = ImageDraw.Draw(char_img)

        bbox = char_draw.textbbox((0, 0), char, font=font)
        cw   = bbox[2] - bbox[0]
        ch   = bbox[3] - bbox[1]
        cx   = (char_width - cw) // 2
        cy   = (height    - ch) // 2 - 4

        char_draw.text((cx, cy), char, font=font, fill=color)

        # دوران خفيف جداً للمصداقية
        angle    = random.randint(-6, 6)
        char_img = char_img.rotate(angle, expand=False)

        x_offset = char_width * i + char_width // 4
        y_offset = random.randint(-3, 3)
        img.paste(char_img, (x_offset, y_offset), char_img)

    # نقاط ضوضاء خفيفة
    for _ in range(20):
        x = random.randint(0, width)
        y = random.randint(0, height)
        r = random.randint(1, 2)
        shade = random.randint(185, 210)
        draw.ellipse([(x - r, y - r), (x + r, y + r)], fill=(shade, shade, shade))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return code, buf
