
"""Shared ONYX profile-card renderer for Discord and the website."""

from io import BytesIO
import json
import re
import threading
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont, ImageFilter

# Prestige artwork comes exclusively from the website Asset Library.
PRESTIGE_ASSET_API = "https://api.onyxdiscord.com/api/assets/prestige-emblems"
PRESTIGE_ASSET_BASE = "https://api.onyxdiscord.com"
PRESTIGE_CACHE_SECONDS = 60

_remote_prestige_badges = {}
_prestige_cache_lock = threading.Lock()
_prestige_refresh_started = False
_prestige_last_refresh = 0.0

# General cosmetic asset image cache.
COSMETIC_ASSET_BASE = "https://api.onyxdiscord.com/api/assets/media/"
COSMETIC_CACHE_SECONDS = 300
_cosmetic_asset_cache = {}
_cosmetic_cache_lock = threading.Lock()


def _fetch_remote_prestige_badge(item_id):
    """Fetch one requested prestige emblem from the website Asset Library."""
    valid_ids = {f"prestige_{i}" for i in range(11)} | {"prestige_master"}
    if item_id not in valid_ids:
        return None

    try:
        request = Request(
            PRESTIGE_ASSET_API,
            headers={"User-Agent": "ONYX-Discord-Bot/1.0"}
        )
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))

        if not isinstance(payload, dict) or not isinstance(payload.get("emblems"), list):
            return None

        image_url = None
        for emblem in payload["emblems"]:
            if not isinstance(emblem, dict):
                continue
            if str(emblem.get("item_id", "")).strip().lower() == item_id:
                image_url = str(emblem.get("image_url", "")).strip()
                break

        if not image_url:
            return None

        if image_url.startswith("/"):
            image_url = PRESTIGE_ASSET_BASE + image_url

        # Only fetch images hosted by the official ONYX API.
        if not image_url.startswith(PRESTIGE_ASSET_BASE + "/"):
            return None

        image_request = Request(
            image_url,
            headers={"User-Agent": "ONYX-Discord-Bot/1.0"}
        )
        with urlopen(image_request, timeout=8) as response:
            image_data = response.read()

        with Image.open(BytesIO(image_data)) as source:
            source.load()
            badge = source.convert("RGBA").copy()

        with _prestige_cache_lock:
            _remote_prestige_badges[item_id] = badge.copy()

        return badge

    except Exception:
        return None


def _get_prestige_badge(badge_key):
    """Return the requested website-uploaded emblem, fetching it on cache miss."""
    item_id = (
        "prestige_master"
        if badge_key == "master"
        else f"prestige_{badge_key}"
    )

    with _prestige_cache_lock:
        cached = _remote_prestige_badges.get(item_id)
        if cached is not None:
            return cached.copy()

    # Fetch the required badge before drawing so the first card isn't blank.
    return _fetch_remote_prestige_badge(item_id)


def _get_cosmetic_asset(category, item_id):
    """Load an Asset Library image, using a short-lived in-memory cache."""
    if not item_id:
        return None

    category = str(category or "").strip().lower()
    item_id = str(item_id or "").strip().lower()

    if category not in {
        "background",
        "emblem",
        "badge",
        "frame",
        "border",
    }:
        return None

    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", item_id):
        return None

    asset_id = f"{category}:{item_id}"
    now = time.time()

    with _cosmetic_cache_lock:
        cached = _cosmetic_asset_cache.get(asset_id)

        if cached:
            cached_time, cached_image = cached

            if now - cached_time < COSMETIC_CACHE_SECONDS:
                return cached_image.copy() if cached_image else None

    image = None

    try:
        image_url = COSMETIC_ASSET_BASE + quote(asset_id, safe=":")
        request = Request(
            image_url,
            headers={"User-Agent": "ONYX-Discord-Bot/1.0"}
        )

        with urlopen(request, timeout=3) as response:
            image_data = response.read()

        with Image.open(BytesIO(image_data)) as source:
            source.load()
            image = source.convert("RGBA").copy()

    except Exception:
        image = None

    with _cosmetic_cache_lock:
        _cosmetic_asset_cache[asset_id] = (
            now,
            image.copy() if image else None,
        )

    return image.copy() if image else None


BASE_XP = 100
LINEAR_XP = 50
QUADRATIC_XP = 5

CARD_THEMES = {
    "onyx": ((12, 18, 31), (22, 39, 55), (35, 210, 200)),
    "frost": ((13, 25, 42), (34, 66, 91), (135, 220, 255)),
    "inferno": ((36, 15, 19), (76, 28, 25), (255, 125, 65)),
    "toxic": ((12, 30, 25), (24, 62, 46), (125, 235, 105)),
    "eclipse": ((20, 17, 39), (48, 34, 72), (181, 135, 255)),
    "void": ((8, 8, 18), (27, 25, 49), (160, 145, 255)),
}

CARD_FRAMES = {
    "default": (55, 190, 190),
    "steel": (145, 165, 180),
    "neon": (45, 235, 220),
    "elite": (190, 165, 95),
    "obsidian": (115, 105, 150),
    "legendary": (255, 190, 90),
}

CARD_EFFECTS = {
    "none": None,
    "teal_glow": (40, 220, 210),
    "silver_shine": (205, 220, 235),
    "electric_pulse": (100, 150, 255),
    "cosmic_aura": (175, 115, 255),
}


def xp_needed(level: int) -> int:
    """Return the XP required for the specified level."""
    return max(
        1,
        int(BASE_XP + LINEAR_XP * level + QUADRATIC_XP * level * level),
    )


def _card_font(size: int, bold: bool = False):
    candidates = (
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        ]
        if bold
        else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ]
    )

    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue

    return ImageFont.load_default()


def _fit_text(draw, text, font, max_width):
    text = str(text)

    while text and draw.textbbox((0, 0), text, font=font)[2] > max_width:
        text = text[:-2] + "…" if len(text) > 2 else text[:-1]

    return text


def _draw_background_asset(image, background):
    """Draw an equipped background image beneath the card content."""
    if background is None:
        return image

    try:
        background = background.convert("RGBA")
        background = background.resize(
            image.size,
            Image.Resampling.LANCZOS,
        )

        # Keep the background visible without sacrificing text readability.
        overlay = Image.new(
            "RGBA",
            image.size,
            (5, 10, 18, 155),
        )

        background = Image.alpha_composite(background, overlay)
        return Image.alpha_composite(image.convert("RGBA"), background)

    except Exception:
        return image.convert("RGBA")


def _draw_small_cosmetic(image, asset, position, max_size):
    """Draw a transparent cosmetic emblem or badge without distortion."""
    if asset is None:
        return image

    try:
        asset = asset.copy().convert("RGBA")
        asset.thumbnail(max_size, Image.Resampling.LANCZOS)

        image = image.convert("RGBA")
        image.alpha_composite(asset, position)

    except Exception:
        pass

    return image


def _draw_frame_asset(image, frame_asset):
    """Overlay a transparent Asset Library frame or border over the card."""
    if frame_asset is None:
        return image

    try:
        image = image.convert("RGBA")
        overlay = frame_asset.copy().convert("RGBA")
        overlay = overlay.resize(
            image.size,
            Image.Resampling.LANCZOS,
        )
        image.alpha_composite(overlay)
        return image
    except Exception:
        return image.convert("RGBA")


def render_onyx_profile_card(
    display_name: str,
    row,
    unlocked_titles=None,
    tokens: int = 0,
    cosmetics=None,
) -> BytesIO:
    """
    Render an ONYX profile card.

    The prestige badge is always determined by the member's current
    progression. Equipped shop emblems cannot override the prestige badge.
    """

    cosmetics = cosmetics or {}

    theme_key = str(cosmetics.get("theme_id") or "onyx").lower()
    frame_category = str(
        cosmetics.get("frame_category") or "frame"
    ).strip().lower()

    if frame_category not in {"frame", "border"}:
        frame_category = "frame"

    frame_key = str(cosmetics.get("frame_id") or "default").lower()
    effect_key = str(cosmetics.get("effect_id") or "none").lower()

    background_id = cosmetics.get("background_id")
    frame_asset = (
        _get_cosmetic_asset(frame_category, frame_key)
        if frame_key != "default"
        else None
    )
    cosmetic_emblem_id = cosmetics.get("emblem_id")
    cosmetic_badge_id = cosmetics.get("badge_id")
    cosmetic_title_id = cosmetics.get("title_id")

    theme = CARD_THEMES.get(theme_key, CARD_THEMES["onyx"])
    frame_color = CARD_FRAMES.get(frame_key, CARD_FRAMES["default"])
    accent = theme[2]

    width, height = 1100, 360

    image = Image.new("RGB", (width, height), theme[0])
    pixels = image.load()

    # Background gradient.
    for x in range(width):
        ratio_x = x / max(1, width - 1)

        color = tuple(
            int(theme[0][i] * (1 - ratio_x) + theme[1][i] * ratio_x)
            for i in range(3)
        )

        for y in range(height):
            pixels[x, y] = color

    # Optional Asset Library background.
    background_asset = _get_cosmetic_asset(
        "background",
        background_id,
    )

    image = _draw_background_asset(image, background_asset)
    draw = ImageDraw.Draw(image)

    draw.ellipse(
        (790, -210, 1240, 240),
        fill=tuple(max(0, c - 5) for c in theme[1]),
    )

    draw.ellipse(
        (900, 190, 1220, 510),
        fill=tuple(max(0, c - 8) for c in theme[1]),
    )

    # Card effects.
    effect_color = CARD_EFFECTS.get(effect_key)

    if effect_color:
        fx = Image.new("RGBA", image.size, (0, 0, 0, 0))
        fd = ImageDraw.Draw(fx)

        if effect_key == "teal_glow":
            fd.rounded_rectangle(
                (20, 20, width - 20, height - 20),
                radius=30,
                outline=(*effect_color, 230),
                width=9,
            )
            fx = fx.filter(ImageFilter.GaussianBlur(9))

        elif effect_key == "silver_shine":
            fd.polygon(
                [(690, 20), (850, 20), (1090, 260), (1090, 325)],
                fill=(*effect_color, 48),
            )
            fd.line(
                (760, 25, 1080, 345),
                fill=(*effect_color, 210),
                width=5,
            )
            fd.line(
                (805, 25, 1090, 310),
                fill=(255, 255, 255, 125),
                width=2,
            )

        elif effect_key == "electric_pulse":
            fd.rounded_rectangle(
                (23, 23, width - 23, height - 23),
                radius=30,
                outline=(*effect_color, 230),
                width=5,
            )

            for points in (
                [(35, 95), (65, 70), (54, 112), (86, 91)],
                [(1010, 70), (1040, 48), (1028, 91), (1065, 72)],
                [(35, 270), (66, 245), (54, 288), (88, 267)],
                [(1010, 290), (1040, 265), (1028, 308), (1065, 285)],
            ):
                fd.line(
                    points,
                    fill=(*effect_color, 255),
                    width=6,
                    joint="curve",
                )

            fx = fx.filter(ImageFilter.GaussianBlur(2))

        elif effect_key == "cosmic_aura":
            for inset, alpha, line_width in (
                (8, 45, 18),
                (18, 100, 8),
                (27, 220, 3),
            ):
                fd.rounded_rectangle(
                    (inset, inset, width - inset, height - inset),
                    radius=34,
                    outline=(*effect_color, alpha),
                    width=line_width,
                )

            for sx, sy in (
                (80, 42),
                (1015, 55),
                (1040, 300),
                (75, 315),
                (550, 28),
            ):
                fd.line(
                    (sx - 10, sy, sx + 10, sy),
                    fill=(235, 220, 255, 230),
                    width=3,
                )
                fd.line(
                    (sx, sy - 10, sx, sy + 10),
                    fill=(235, 220, 255, 230),
                    width=3,
                )

        image = Image.alpha_composite(
            image.convert("RGBA"),
            fx,
        ).convert("RGB")

        draw = ImageDraw.Draw(image)

    # Main card frame.
    draw.rounded_rectangle(
        (18, 18, width - 18, height - 18),
        radius=28,
        outline=frame_color,
        width=5,
    )

    inner_frame = tuple(
        min(255, int(c * 0.55 + 40))
        for c in frame_color
    )

    draw.rounded_rectangle(
        (31, 31, width - 31, height - 31),
        radius=22,
        outline=inner_frame,
        width=1,
    )

    if frame_key in ("neon", "legendary"):
        draw.rounded_rectangle(
            (24, 24, width - 24, height - 24),
            radius=30,
            outline=tuple(min(255, c) for c in frame_color),
            width=2,
        )

    elif frame_key == "steel":
        draw.line(
            (55, 23, width - 55, 23),
            fill=(220, 230, 240),
            width=2,
        )

    elif frame_key == "obsidian":
        draw.rounded_rectangle(
            (26, 26, width - 26, height - 26),
            radius=26,
            outline=(75, 65, 105),
            width=2,
        )

    # Fonts.
    font_brand = _card_font(25, True)
    font_name = _card_font(43, True)
    font_stage = _card_font(25, True)
    font_label = _card_font(16, True)
    font_cosmetic_title = _card_font(23, True)

    # Branding and member name.
    draw.text(
        (58, 48),
        "ONYX",
        font=font_brand,
        fill=accent,
    )

    draw.text(
        (155, 55),
        "GLOBAL PROFILE",
        font=font_label,
        fill=(165, 185, 202),
    )

    draw.line(
        (58, 98, width - 58, 98),
        fill=tuple(int(c * 0.7) for c in accent),
        width=2,
    )

    # Draw the cosmetic title immediately beside the username.
    # Keep both on one line and render the equipped title in white quotation marks.
    name_text = _fit_text(draw, display_name, font_name, 500)
    draw.text(
        (58, 125),
        name_text,
        font=font_name,
        fill=(245, 249, 252),
    )

    if cosmetic_title_id:
        cosmetic_title = str(cosmetic_title_id).replace("_", " ").replace("-", " ")
        cosmetic_title = cosmetic_title.title()
        cosmetic_title = f'"{cosmetic_title}"'

        name_bbox = draw.textbbox((58, 125), name_text, font=font_name)
        title_x = name_bbox[2] + 18
        remaining_width = max(80, 820 - title_x)
        cosmetic_title = _fit_text(
            draw,
            cosmetic_title,
            font_cosmetic_title,
            remaining_width,
        )

        draw.text(
            (title_x, 137),
            cosmetic_title,
            font=font_cosmetic_title,
            fill=(255, 255, 255),
        )

    # Determine progression stage and current prestige badge.
    if row["master_mode"]:
        stage = (
            f"PRESTIGE MASTER  •  "
            f"LEVEL {int(row['master_level']):,} / 1,000"
        )
        active_level = int(row["master_level"])
        badge_key = "master"

    else:
        prestige = int(row["prestige"])

        if prestige:
            stage = (
                f"PRESTIGE {prestige}  •  "
                f"LEVEL {int(row['level']):,} / 60"
            )
        else:
            stage = f"LEVEL {int(row['level']):,} / 60"

        active_level = int(row["level"])
        badge_key = prestige

    draw.text(
        (60, 215),
        stage,
        font=font_stage,
        fill=accent,
    )

    # Always show the current progression badge.
    # Shop emblem cosmetics intentionally do not override this badge.
    insignia = _get_prestige_badge(badge_key)

    if insignia is not None:
        insignia.thumbnail(
            (170, 170),
            Image.Resampling.LANCZOS,
        )

        image_rgba = image.convert("RGBA")

        badge_x = 890 - insignia.width // 2
        badge_y = 185 - insignia.height // 2

        image_rgba.alpha_composite(
            insignia,
            (badge_x, badge_y),
        )

        image = image_rgba.convert("RGB")
        draw = ImageDraw.Draw(image)

    # Cosmetic emblem is displayed separately from the prestige insignia.
    cosmetic_emblem = _get_cosmetic_asset(
        "emblem",
        cosmetic_emblem_id,
    )

    if cosmetic_emblem is not None:
        image = _draw_small_cosmetic(
            image,
            cosmetic_emblem,
            (1010, 48),
            (55, 55),
        )
        draw = ImageDraw.Draw(image)

    # Cosmetic badge is also separate from the progression insignia.
    cosmetic_badge = _get_cosmetic_asset(
        "badge",
        cosmetic_badge_id,
    )

    if cosmetic_badge is not None:
        image = _draw_small_cosmetic(
            image,
            cosmetic_badge,
            (970, 235),
            (65, 65),
        )
        draw = ImageDraw.Draw(image)

    # XP progress.
    needed = xp_needed(active_level)
    current_xp = int(row["xp"])

    ratio = (
        min(1.0, max(0.0, current_xp / needed))
        if needed
        else 1.0
    )

    draw.text(
        (60, 275),
        f"XP  {current_xp:,} / {needed:,}",
        font=font_label,
        fill=(205, 220, 230),
    )

    draw.rounded_rectangle(
        (260, 278, 900, 298),
        radius=10,
        fill=(5, 10, 18),
    )

    if ratio > 0:
        draw.rounded_rectangle(
            (260, 278, 260 + int(640 * ratio), 298),
            radius=10,
            fill=accent,
        )

    draw.text(
        (920, 275),
        f"{ratio * 100:.1f}%",
        font=font_label,
        fill=(235, 242, 248),
    )

    # Transparent Asset Library frame/border artwork sits above card content.
    # If no uploaded artwork is available, the legacy drawn frame remains.
    image = _draw_frame_asset(image, frame_asset)

    # Return a PNG in memory.
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)

    return output
