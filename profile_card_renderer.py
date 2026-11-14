"""Shared ONYX profile-card renderer for Discord and the website."""

from io import BytesIO
from pathlib import Path
import json
import threading
import time
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont, ImageFilter


ASSET_DIR = Path(__file__).resolve().parent / "assets" / "onyx_prestige"

PRESTIGE_BADGES = {
    0: "prestige_0.PNG",
    1: "prestige_1.PNG",
    2: "prestige_2.PNG",
    3: "prestige_3.PNG",
    4: "prestige_4.PNG",
    5: "prestige_5.PNG",
    6: "prestige_6.PNG",
    7: "prestige_7.PNG",
    8: "prestige_8.PNG",
    9: "prestige_9.PNG",
    10: "prestige_10.PNG",
    "master": "prestige_master.PNG",
}

# Website Asset Library is the source of truth for prestige artwork.
PRESTIGE_ASSET_API = "https://api.onyxdiscord.com/api/assets/prestige-emblems"
PRESTIGE_ASSET_BASE = "https://api.onyxdiscord.com"
PRESTIGE_CACHE_SECONDS = 60

_remote_prestige_badges = {}
_prestige_cache_lock = threading.Lock()
_prestige_refresh_started = False
_prestige_last_refresh = 0.0


def _refresh_remote_prestige_badges():
    """Download current prestige emblems without blocking Discord commands."""
    global _remote_prestige_badges
    global _prestige_last_refresh
    global _prestige_refresh_started

    try:
        request = Request(
            PRESTIGE_ASSET_API,
            headers={"User-Agent": "ONYX-Discord-Bot/1.0"}
        )

        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        refreshed = {}

        for emblem in payload.get("emblems", []):
            item_id = str(emblem.get("item_id", "")).strip().lower()
            image_url = str(emblem.get("image_url", "")).strip()

            if not item_id.startswith("prestige_") or not image_url:
                continue

            if image_url.startswith("/"):
                image_url = PRESTIGE_ASSET_BASE + image_url

            if not image_url.startswith(("https://", "http://")):
                continue

            image_request = Request(
                image_url,
                headers={"User-Agent": "ONYX-Discord-Bot/1.0"}
            )

            with urlopen(image_request, timeout=5) as response:
                image_data = response.read()

            with Image.open(BytesIO(image_data)) as source:
                source.load()
                refreshed[item_id] = source.convert("RGBA").copy()

        if refreshed:
            with _prestige_cache_lock:
                _remote_prestige_badges = refreshed

    except Exception:
        # Local repository artwork remains the fallback if the API is offline.
        pass

    finally:
        with _prestige_cache_lock:
            _prestige_last_refresh = time.time()
            _prestige_refresh_started = False


def _request_prestige_refresh():
    """Refresh the remote cache in a daemon thread when stale."""
    global _prestige_refresh_started

    with _prestige_cache_lock:
        stale = time.time() - _prestige_last_refresh >= PRESTIGE_CACHE_SECONDS

        if not stale or _prestige_refresh_started:
            return

        _prestige_refresh_started = True

    threading.Thread(
        target=_refresh_remote_prestige_badges,
        name="onyx-prestige-assets",
        daemon=True,
    ).start()


def _get_prestige_badge(badge_key):
    """Return a copy of the latest remote badge, or the local fallback."""
    item_id = (
        "prestige_master"
        if badge_key == "master"
        else f"prestige_{badge_key}"
    )

    _request_prestige_refresh()

    with _prestige_cache_lock:
        remote_badge = _remote_prestige_badges.get(item_id)

        if remote_badge is not None:
            return remote_badge.copy()

    filename = PRESTIGE_BADGES.get(badge_key, PRESTIGE_BADGES[0])
    badge_path = ASSET_DIR / filename

    if badge_path.is_file():
        try:
            with Image.open(badge_path) as source_badge:
                source_badge.load()
                return source_badge.convert("RGBA").copy()
        except Exception:
            return None

    return None


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
    frame_key = str(cosmetics.get("frame_id") or "default").lower()
    effect_key = str(cosmetics.get("effect_id") or "none").lower()

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

    draw.text(
        (58, 125),
        _fit_text(draw, display_name, font_name, 650),
        font=font_name,
        fill=(245, 249, 252),
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
        (60, 190),
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

    # Return a PNG in memory.
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)

    return output
