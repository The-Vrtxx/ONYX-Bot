
"""Pillow-based card table artwork for the ONYX blackjack game."""

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont


WIDTH, HEIGHT = 1500, 900
BG = (7, 14, 23)
FELT = (8, 67, 61)
GOLD = (216, 179, 94)
WHITE = (247, 246, 239)
RED = (190, 55, 63)
INK = (25, 31, 39)


def _font(size, bold=False):
    paths = (
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        )
        if bold
        else ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",)
    )

    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue

    return ImageFont.load_default()


def _centered(draw, xy, text, font, fill):
    box = draw.textbbox((0, 0), text, font=font)

    draw.text(
        (
            xy[0] - (box[2] - box[0]) / 2,
            xy[1] - (box[3] - box[1]) / 2,
        ),
        text,
        font=font,
        fill=fill,
    )


def _card(draw, x, y, card, hidden=False):
    width, height = 142, 208

    draw.rounded_rectangle(
        (x + 5, y + 7, x + width + 5, y + height + 7),
        radius=15,
        fill=(0, 0, 0),
    )

    if hidden:
        draw.rounded_rectangle(
            (x, y, x + width, y + height),
            radius=15,
            fill=(19, 45, 79),
            outline=GOLD,
            width=4,
        )

        draw.rounded_rectangle(
            (x + 11, y + 11, x + width - 11, y + height - 11),
            radius=10,
            outline=(111, 153, 184),
            width=3,
        )

        for offset in range(-120, 180, 22):
            draw.line(
                (
                    x + 12 + max(0, offset),
                    y + 12 + max(0, -offset),
                    x + width - 12 - max(0, -offset),
                    y + height - 12 - max(0, offset),
                ),
                fill=(75, 112, 150),
                width=2,
            )

        _centered(
            draw,
            (x + width / 2, y + height / 2),
            "ONYX",
            _font(24, True),
            WHITE,
        )
        return

    rank, _value, suit = card
    color = RED if suit in ("♥", "♦") else INK

    draw.rounded_rectangle(
        (x, y, x + width, y + height),
        radius=15,
        fill=WHITE,
        outline=(215, 215, 207),
        width=2,
    )

    draw.text(
        (x + 13, y + 8),
        str(rank),
        font=_font(31, True),
        fill=color,
    )

    draw.text(
        (x + 14, y + 43),
        suit,
        font=_font(25),
        fill=color,
    )

    _centered(
        draw,
        (x + width / 2, y + height / 2 + 9),
        suit,
        _font(78),
        color,
    )

    draw.text(
        (x + width - 34, y + height - 45),
        str(rank),
        font=_font(25, True),
        fill=color,
    )


def render_blackjack_png(
    player,
    dealer,
    reveal,
    player_total,
    dealer_total,
):
    """Return a PNG byte string showing both blackjack hands."""

    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        (35, 35, WIDTH - 35, HEIGHT - 35),
        radius=36,
        fill=FELT,
        outline=GOLD,
        width=5,
    )

    draw.rounded_rectangle(
        (57, 57, WIDTH - 57, HEIGHT - 57),
        radius=28,
        outline=(28, 112, 98),
        width=3,
    )

    _centered(
        draw,
        (WIDTH / 2, 105),
        "ONYX BLACKJACK",
        _font(48, True),
        WHITE,
    )

    _centered(
        draw,
        (WIDTH / 2, 165),
        "DEALER",
        _font(25, True),
        GOLD,
    )

    def draw_hand(cards, y, hidden_index=None):
        count = len(cards)
        card_width = 142
        gap = 22

        total_width = count * card_width + max(0, count - 1) * gap
        start_x = (WIDTH - total_width) // 2

        for index, card in enumerate(cards):
            _card(
                draw,
                start_x + index * (card_width + gap),
                y,
                card,
                hidden=(index == hidden_index),
            )

    hidden_index = (
        1 if not reveal and len(dealer) > 1 else None
    )

    draw_hand(dealer, 205, hidden_index)

    dealer_label = (
        f"Dealer total: {dealer_total}"
        if reveal
        else "Dealer total: ?"
    )

    _centered(
        draw,
        (WIDTH / 2, 445),
        dealer_label,
        _font(27, True),
        WHITE,
    )

    draw.line(
        (180, 495, WIDTH - 180, 495),
        fill=GOLD,
        width=2,
    )

    _centered(
        draw,
        (WIDTH / 2, 555),
        "YOUR HAND",
        _font(25, True),
        GOLD,
    )

    draw_hand(player, 590)

    _centered(
        draw,
        (WIDTH / 2, 830),
        f"YOUR TOTAL: {player_total}",
        _font(32, True),
        WHITE,
    )

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)

    return output.getvalue()
