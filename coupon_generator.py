import io
import os
import math
import logging
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import treepoem
import requests
import pytz

logger = logging.getLogger(__name__)

EST = pytz.timezone("US/Eastern")

COUPON_WIDTH = 1050
COUPON_HEIGHT = 520
BG_COLOR = (248, 250, 252)
BORDER_COLOR = (0, 71, 171)
TEXT_COLOR = (0, 32, 96)
FINE_PRINT_COLOR = (100, 100, 100)

FONT_DIR = "/usr/share/fonts/truetype"


def _load_font(bold=False, size=20):
    paths = []
    if bold:
        paths = [
            f"{FONT_DIR}/liberation/LiberationSans-Bold.ttf",
            f"{FONT_DIR}/freefont/FreeSansBold.ttf",
        ]
    else:
        paths = [
            f"{FONT_DIR}/liberation/LiberationSans-Regular.ttf",
            f"{FONT_DIR}/freefont/FreeSans.ttf",
        ]
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _draw_walmart_spark(draw, cx, cy, size=28):
    """Draw the Walmart spark/asterisk logo."""
    color = (0, 71, 171)
    r_inner = size * 0.2
    r_outer = size * 0.85
    petal_width = size * 0.22

    for i in range(6):
        angle = math.radians(i * 60 - 90)
        # Petal body
        perp_angle = angle + math.pi / 2
        x_base1 = cx + r_inner * math.cos(angle) + petal_width * math.cos(perp_angle)
        y_base1 = cy + r_inner * math.sin(angle) + petal_width * math.sin(perp_angle)
        x_base2 = cx + r_inner * math.cos(angle) - petal_width * math.cos(perp_angle)
        y_base2 = cy + r_inner * math.sin(angle) - petal_width * math.sin(perp_angle)
        x_tip = cx + r_outer * math.cos(angle)
        y_tip = cy + r_outer * math.sin(angle)
        draw.polygon([(x_base1, y_base1), (x_tip, y_tip), (x_base2, y_base2)], fill=color)
        # Rounded tip
        tip_r = petal_width * 0.7
        draw.ellipse([x_tip - tip_r, y_tip - tip_r, x_tip + tip_r, y_tip + tip_r], fill=color)


def _generate_barcode_image(barcode_data):
    """Generate GS1 DataBar Expanded barcode image (no fallback).

    Uses GS1 Application Identifier (8110) for North American Coupon Code
    per the algorithm:
        (8110) 0 AAAAAA 0BB 0004BB 001 1 00003 CCDDEE
    where AAAAAA = first 6 digits of UPC, BB = discount, CC/DD/EE = YY/MM/DD (EST).

    Requires Ghostscript to be installed (treepoem dependency).

    NOTE: scale=2 is chosen because it produces a barcode (~594px wide) that
    fits the coupon without any horizontal shrinkage. Shrinking GS1 DataBar
    Expanded breaks scanability because the narrowest bars get sub-pixel.
    """
    img = treepoem.generate_barcode(
        barcode_type="databarexpanded",
        data=f"(8110){barcode_data}",
        scale=2,
        options={"includetext": False, "height": 0.6},
    )
    return img.convert("RGB")


def _fetch_product_image(url):
    """Download product image from URL."""
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0"
        })
        if resp.status_code == 200:
            return Image.open(io.BytesIO(resp.content)).convert("RGBA")
    except Exception as e:
        logger.warning(f"Failed to fetch product image: {e}")
    return None


def build_barcode_data(upc_first6, discount, date=None):
    """
    Build barcode data string from template:
    0AAAAAA0BB0004BB001100003CCDDEE
    (Prefix 8110 added when generating barcode)
    """
    if date is None:
        date = datetime.now(EST)

    aa = upc_first6[:6].ljust(6, "0")
    bb = f"{int(discount):02d}"
    cc = f"{date.year % 100:02d}"
    dd = f"{date.month:02d}"
    ee = f"{date.day:02d}"

    data = f"0{aa}0{bb}0004{bb}001100003{cc}{dd}{ee}"
    return data


def generate_coupon_image(upc_first6, discount, product_name, product_image_url=None, expiry_date=None):
    """
    Generate a manufacturer's coupon image matching the reference template.
    Returns bytes (PNG).
    """
    now_est = datetime.now(EST)
    if expiry_date is None:
        expiry_date = now_est.strftime("%m/%d/%Y")

    barcode_data = build_barcode_data(upc_first6, discount, now_est)

    img = Image.new("RGB", (COUPON_WIDTH, COUPON_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # --- Background fill: white with subtle frame ---
    draw.rectangle([(0, 0), (COUPON_WIDTH - 1, COUPON_HEIGHT - 1)], fill=(255, 255, 255))

    # Outer border
    draw.rectangle([(0, 0), (COUPON_WIDTH - 1, COUPON_HEIGHT - 1)], outline=(160, 195, 225), width=4)
    # Inner border
    draw.rectangle([(6, 6), (COUPON_WIDTH - 7, COUPON_HEIGHT - 7)], outline=BORDER_COLOR, width=2)

    # --- Fonts ---
    font_title = _load_font(bold=True, size=32)
    font_expires = _load_font(bold=True, size=15)
    font_discount_big = _load_font(bold=True, size=68)
    font_discount_off = _load_font(bold=True, size=38)
    font_any_one = _load_font(bold=True, size=22)
    font_qualifying = _load_font(bold=True, size=18)
    font_product = _load_font(bold=True, size=20)
    font_scan = _load_font(bold=True, size=13)
    font_limit = _load_font(bold=True, size=15)
    font_fine = _load_font(False, size=11)

    # --- Walmart spark logo + text (top-left) ---
    _draw_walmart_spark(draw, 45, 45, size=30)
    # Small TM text
    font_tm = _load_font(False, size=9)
    draw.text((70, 25), "TM", font=font_tm, fill=TEXT_COLOR)

    # --- "MANUFACTURER'S COUPON" (top center) ---
    title_x = COUPON_WIDTH // 2 + 20
    draw.text((title_x, 28), "MANUFACTURER'S COUPON", font=font_title, fill=TEXT_COLOR, anchor="mt")

    # --- Gradient bar with EXPIRES text ---
    bar_y = 62
    bar_h = 28
    bar_left = 220
    bar_right = 640
    for x in range(bar_left, bar_right):
        ratio = (x - bar_left) / (bar_right - bar_left)
        r = int(20 + ratio * 80)
        g = int(55 + ratio * 100)
        b = int(120 + ratio * 60)
        draw.line([(x, bar_y), (x, bar_y + bar_h)], fill=(r, g, b))
    draw.text(((bar_left + bar_right) // 2, bar_y + bar_h // 2),
              f"EXPIRES: {expiry_date}", font=font_expires, fill=(255, 255, 255), anchor="mm")

    # --- "LIMIT ONE COUPON PER PURCHASE" (right side, stacked) ---
    limit_x = COUPON_WIDTH - 75
    draw.text((limit_x, 28), "LIMIT ONE", font=font_limit, fill=TEXT_COLOR, anchor="mt")
    draw.text((limit_x, 48), "COUPON PER", font=font_limit, fill=TEXT_COLOR, anchor="mt")
    draw.text((limit_x, 68), "PURCHASE", font=font_limit, fill=TEXT_COLOR, anchor="mt")

    # --- Discount amount: "$XX.00 OFF" (center-left) ---
    discount_y = 225
    draw.text((200, discount_y), f"${int(discount)}.00", font=font_discount_big, fill=TEXT_COLOR, anchor="mm")
    draw.text((310, discount_y - 5), "OFF", font=font_discount_off, fill=TEXT_COLOR, anchor="lm")

    # --- "SCAN AT REGISTER" ---
    draw.text((130, 290), "SCAN AT REGISTER", font=font_scan, fill=TEXT_COLOR, anchor="mt")

    # --- "ANY ONE (1) QUALIFYING PRODUCT" (right-center) ---
    any_x = 560
    draw.text((any_x, 170), "ANY ONE (1)", font=font_any_one, fill=TEXT_COLOR, anchor="mm")
    draw.text((any_x, 198), "QUALIFYING PRODUCT", font=font_qualifying, fill=TEXT_COLOR, anchor="mm")

    # --- Product name (right column, below the product image, never over barcode) ---
    name_center_x = 700  # right of barcode area
    display_name = product_name or "QUALIFYING PRODUCT"
    display_name = display_name.upper()
    if len(display_name) > 55:
        # Word-wrap to two lines
        words = display_name.split()
        line1, line2 = "", ""
        for w in words:
            if len(line1) + len(w) + 1 <= 45:
                line1 = f"{line1} {w}".strip()
            else:
                line2 = f"{line2} {w}".strip()
        font_product_sm = _load_font(bold=True, size=17)
        draw.text((name_center_x, 360), line1, font=font_product_sm, fill=TEXT_COLOR, anchor="mt")
        draw.text((name_center_x, 384), line2, font=font_product_sm, fill=TEXT_COLOR, anchor="mt")
    else:
        draw.text((name_center_x, 370), display_name, font=font_product, fill=TEXT_COLOR, anchor="mt")

    # --- Product image (right side) ---
    product_img = _fetch_product_image(product_image_url)
    if product_img:
        max_w, max_h = 260, 260
        product_img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        # Right-align within the coupon: leave ~40px right margin
        paste_x = COUPON_WIDTH - product_img.size[0] - 40
        paste_y = 95
        if product_img.mode == "RGBA":
            # Create white background for RGBA images
            bg = Image.new("RGB", product_img.size, (255, 255, 255))
            bg.paste(product_img, mask=product_img.split()[3])
            img.paste(bg, (paste_x, paste_y))
        else:
            img.paste(product_img, (paste_x, paste_y))

    # --- GS1 Barcode (bottom-left) ---
    # IMPORTANT: do NOT downscale the barcode horizontally — it kills scan
    # reliability. We paste it at native width and only stretch height with
    # NEAREST so the bars stay 1:1 with the rendered modules.
    barcode_img = _generate_barcode_image(barcode_data)
    if barcode_img:
        # Crop to remove any text below the bars (just in case)
        w, h = barcode_img.size
        crop_bottom = h
        for y in range(h - 1, 0, -1):
            row_pixels = [barcode_img.getpixel((x, y)) for x in range(0, w, max(1, w // 20))]
            black_count = sum(1 for p in row_pixels if (p[0] if isinstance(p, tuple) else p) < 50)
            if black_count > len(row_pixels) * 0.1:
                crop_bottom = y + 5
                break
        barcode_cropped = barcode_img.crop((0, 0, w, min(crop_bottom, h)))

        # Stretch ONLY vertically (preserves bar widths) for a taller, easier
        # to scan barcode. Width stays at native scale=2 (~594 px).
        cw, ch = barcode_cropped.size
        target_h = 130
        barcode_resized = barcode_cropped.resize((cw, target_h), Image.Resampling.NEAREST)
        img.paste(barcode_resized, (25, 320))

    # --- Fine print (bottom) ---
    fine = "Not valid with any other offer. Consumer pays any sales tax. VOID if copied, transferred, or expired."
    draw.text((COUPON_WIDTH // 2, COUPON_HEIGHT - 20), fine, font=font_fine, fill=FINE_PRINT_COLOR, anchor="mm")

    # --- Output ---
    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    buf.seek(0)
    return buf.getvalue()
