"""ONYX global leveling, Prestige progression, and Prestige Master titles."""
import random
import re
import time
import asyncio
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from profile_card_renderer import render_onyx_profile_card as render_shared_profile_card

import discord
from discord.ext import commands

COLOR = discord.Color.from_rgb(25, 190, 190)
ASSET_DIR = Path(__file__).resolve().parents[2] / "assets" / "onyx_prestige"
PRESTIGE_EMBLEMS = {
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
BASE_XP = 100
LINEAR_XP = 50
QUADRATIC_XP = 5
MAX_LEVEL = 60
MAX_PRESTIGE = 10
MAX_MASTER_LEVEL = 1000
PRESTIGE_TOKEN_REWARD = 10

MASTER_TITLES = {
    25: "Veteran",
    50: "Elite",
    100: "Specialist",
    200: "Champion",
    300: "Warlord",
    500: "Legend",
    750: "Mythic",
    1000: "ONYX Master",
}


# Profile-card cosmetics are stored now; the Prestige Shop will add ownership
# and equip commands in Step 3. These defaults keep every card renderable today.
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


def _card_font(size: int, bold: bool = False):
    candidates = (
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"]
        if bold else
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]
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


def render_onyx_profile_card(display_name: str, row, unlocked_titles: list[str],
                             tokens: int, cosmetics=None) -> BytesIO:
    """Render the ONYX profile card using the equipped or previewed cosmetics."""
    cosmetics = cosmetics or {}
    theme_key = str(cosmetics.get("theme_id") or "onyx").lower()
    frame_key = str(cosmetics.get("frame_id") or "default").lower()
    effect_key = str(cosmetics.get("effect_id") or "none").lower()
    emblem_key = str(cosmetics.get("emblem_id") or "default").lower()
    theme = CARD_THEMES.get(theme_key, CARD_THEMES["onyx"])
    frame_color = CARD_FRAMES.get(frame_key, CARD_FRAMES["default"])
    accent = theme[2]
    width, height = 1100, 360

    image = Image.new("RGB", (width, height), theme[0])
    pixels = image.load()
    for x in range(width):
        ratio_x = x / max(1, width - 1)
        color = tuple(
            int(theme[0][i] * (1 - ratio_x) + theme[1][i] * ratio_x)
            for i in range(3)
        )
        for y in range(height):
            pixels[x, y] = color

    draw = ImageDraw.Draw(image)
    draw.ellipse((790, -210, 1240, 240),
                 fill=tuple(max(0, c - 5) for c in theme[1]))
    draw.ellipse((900, 190, 1220, 510),
                 fill=tuple(max(0, c - 8) for c in theme[1]))

    # Distinct, visible effect treatments around the card perimeter.
    effect_color = CARD_EFFECTS.get(effect_key)
    if effect_color:
        fx = Image.new("RGBA", image.size, (0, 0, 0, 0))
        fd = ImageDraw.Draw(fx)
        if effect_key == "teal_glow":
            fd.rounded_rectangle((20, 20, width - 20, height - 20),
                                 radius=30, outline=(*effect_color, 230), width=9)
            fx = fx.filter(ImageFilter.GaussianBlur(9))
        elif effect_key == "silver_shine":
            # Diagonal metallic sheen across the upper-right corner.
            fd.polygon([(690, 20), (850, 20), (1090, 260), (1090, 325)],
                       fill=(*effect_color, 48))
            fd.line((760, 25, 1080, 345), fill=(*effect_color, 210), width=5)
            fd.line((805, 25, 1090, 310), fill=(255, 255, 255, 125), width=2)
        elif effect_key == "electric_pulse":
            fd.rounded_rectangle((23, 23, width - 23, height - 23),
                                 radius=30, outline=(*effect_color, 230), width=5)
            # Angular lightning accents at all four corners.
            for points in (
                [(35, 95), (65, 70), (54, 112), (86, 91)],
                [(1010, 70), (1040, 48), (1028, 91), (1065, 72)],
                [(35, 270), (66, 245), (54, 288), (88, 267)],
                [(1010, 290), (1040, 265), (1028, 308), (1065, 285)],
            ):
                fd.line(points, fill=(*effect_color, 255), width=6, joint="curve")
            fx = fx.filter(ImageFilter.GaussianBlur(2))
        elif effect_key == "cosmic_aura":
            for inset, alpha, line_width in ((8, 45, 18), (18, 100, 8), (27, 220, 3)):
                fd.rounded_rectangle((inset, inset, width-inset, height-inset),
                                     radius=34, outline=(*effect_color, alpha),
                                     width=line_width)
            # Small starbursts make the aura visibly different from a glow.
            for sx, sy in ((80, 42), (1015, 55), (1040, 300), (75, 315), (550, 28)):
                fd.line((sx-10, sy, sx+10, sy), fill=(235, 220, 255, 230), width=3)
                fd.line((sx, sy-10, sx, sy+10), fill=(235, 220, 255, 230), width=3)
        image = Image.alpha_composite(image.convert("RGBA"), fx).convert("RGB")
        draw = ImageDraw.Draw(image)

    # Main card frame; frame cosmetics change both color and visual treatment.
    draw.rounded_rectangle((18, 18, width - 18, height - 18), radius=28,
                           outline=frame_color, width=5)
    inner_frame = tuple(min(255, int(c * 0.55 + 40)) for c in frame_color)
    draw.rounded_rectangle((31, 31, width - 31, height - 31), radius=22,
                           outline=inner_frame, width=1)
    if frame_key in ("neon", "legendary"):
        draw.rounded_rectangle((24, 24, width - 24, height - 24), radius=30,
                               outline=tuple(min(255, c) for c in frame_color), width=2)
    elif frame_key == "steel":
        draw.line((55, 23, width - 55, 23), fill=(220, 230, 240), width=2)
    elif frame_key == "obsidian":
        draw.rounded_rectangle((26, 26, width - 26, height - 26), radius=26,
                               outline=(75, 65, 105), width=2)

    font_brand = _card_font(25, True)
    font_name = _card_font(43, True)
    font_stage = _card_font(25, True)
    font_label = _card_font(16, True)
    font_emblem = _card_font(20, True)

    draw.text((58, 48), "ONYX", font=font_brand, fill=accent)
    draw.text((155, 55), "GLOBAL PROFILE", font=font_label,
              fill=(165, 185, 202))
    draw.line((58, 98, width - 58, 98),
              fill=tuple(int(c * 0.7) for c in accent), width=2)
    draw.text((58, 125), _fit_text(draw, display_name, font_name, 650),
              font=font_name, fill=(245, 249, 252))

    if row["master_mode"]:
        stage = f"PRESTIGE MASTER  •  LEVEL {int(row['master_level']):,} / 1,000"
        active_level = int(row["master_level"])
        rank_emblem_key = "master"
    else:
        prestige = int(row["prestige"])
        stage = (
            f"PRESTIGE {prestige}  •  LEVEL {int(row['level']):,} / 60"
            if prestige else f"LEVEL {int(row['level']):,} / 60"
        )
        active_level = int(row["level"])
        rank_emblem_key = prestige
    draw.text((60, 190), stage, font=font_stage, fill=accent)

    # Shop emblem overrides the progression emblem. Draw a custom badge so each
    # purchased emblem is visible even when no separate PNG asset is installed.
    shop_emblems = {
        "veteran": ("VETERAN", (145, 185, 220)),
        "elite": ("ELITE", (90, 205, 255)),
        "champion": ("CHAMPION", (255, 205, 75)),
        "warlord": ("WARLORD", (235, 85, 90)),
        "mythic": ("MYTHIC", (205, 110, 255)),
    }
    if emblem_key in shop_emblems:
        label, badge_color = shop_emblems[emblem_key]
        badge = Image.new("RGBA", (190, 190), (0, 0, 0, 0))
        bd = ImageDraw.Draw(badge)
        bd.ellipse((18, 18, 172, 172), fill=(8, 12, 23, 245),
                   outline=(*badge_color, 255), width=7)
        bd.ellipse((29, 29, 161, 161), outline=(235, 242, 250, 180), width=2)
        bd.polygon([(95, 42), (137, 78), (125, 132), (95, 153),
                    (65, 132), (53, 78)],
                   fill=(*badge_color, 65), outline=(*badge_color, 255))
        bd.text((95, 96), "ONYX", anchor="mm", font=_card_font(22, True),
                fill=(250, 252, 255))
        bd.text((95, 124), label, anchor="mm", font=_card_font(12, True),
                fill=(250, 252, 255))
        image_rgba = image.convert("RGBA")
        image_rgba.alpha_composite(badge, (795, 105))
        image = image_rgba.convert("RGB")
        draw = ImageDraw.Draw(image)
    else:
        emblem_path = ASSET_DIR / PRESTIGE_EMBLEMS[rank_emblem_key]
        if emblem_path.is_file():
            with Image.open(emblem_path) as source_emblem:
                insignia = source_emblem.convert("RGBA")
                insignia.thumbnail((170, 170), Image.Resampling.LANCZOS)
            image_rgba = image.convert("RGBA")
            emblem_x = 890 - insignia.width // 2
            emblem_y = 185 - insignia.height // 2
            image_rgba.alpha_composite(insignia, (emblem_x, emblem_y))
            image = image_rgba.convert("RGB")
            draw = ImageDraw.Draw(image)

    needed = xp_needed(active_level)
    current_xp = int(row["xp"])
    ratio = min(1.0, max(0.0, current_xp / needed)) if needed else 1.0
    draw.text((60, 275), f"XP  {current_xp:,} / {needed:,}",
              font=font_label, fill=(205, 220, 230))
    draw.rounded_rectangle((260, 278, 900, 298), radius=10, fill=(5, 10, 18))
    if ratio > 0:
        draw.rounded_rectangle(
            (260, 278, 260 + int(640 * ratio), 298),
            radius=10, fill=accent
        )
    draw.text((920, 275), f"{ratio * 100:.1f}%",
              font=font_label, fill=(235, 242, 248))

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    return output

def xp_needed(level: int) -> int:
    return max(1, int(BASE_XP + LINEAR_XP * level + QUADRATIC_XP * level * level))


def progress_bar(current: int, required: int, size: int = 14) -> str:
    ratio = min(1.0, max(0.0, current / required)) if required else 1.0
    filled = int(ratio * size)
    return "▰" * filled + "▱" * (size - filled)


def stage_label(row) -> str:
    if row["master_mode"]:
        return f"Prestige Master • Level {row['master_level']:,}/{MAX_MASTER_LEVEL:,}"
    if row["prestige"]:
        return f"Prestige {row['prestige']} • Level {row['level']:,}/{MAX_LEVEL}"
    return f"Level {row['level']:,}/{MAX_LEVEL}"


class PrestigeChoiceView(discord.ui.View):
    def __init__(self, cog, user_id: int):
        super().__init__(timeout=90)
        self.cog = cog
        self.user_id = user_id
        self.finished = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This Prestige choice belongs to another user.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Prestige", style=discord.ButtonStyle.primary, emoji="⬆️")
    async def prestige(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.finished:
            return await interaction.response.send_message(
                "This choice has already been handled.", ephemeral=True
            )

        applied = await self.cog.apply_prestige(self.user_id)
        self.finished = True
        for item in self.children:
            item.disabled = True

        if not applied:
            return await interaction.response.edit_message(
                content="Your Prestige eligibility has changed. Run `,prestige` again.",
                view=None,
            )

        updated = await self.cog.profile(self.user_id)
        if updated["master_mode"]:
            message = (
                f"🏆 **Prestige Master unlocked!** Your profile is now "
                f"**{stage_label(updated)}**."
            )
        else:
            message = (
                f"🏆 **Prestige unlocked!** Your profile is now "
                f"**{stage_label(updated)}**.\n"
                f"🪙 You earned **{PRESTIGE_TOKEN_REWARD} Prestige Tokens**!"
            )

        await interaction.response.edit_message(
            content=message + "\nYour lifetime XP has been preserved.",
            view=self,
        )

    @discord.ui.button(label="Stay at Level 60", style=discord.ButtonStyle.secondary, emoji="🛡️")
    async def stay(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.finished = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=(
                "You chose to keep your current rank. Your XP and Level 60 progress "
                "are safe. Run `,prestige` whenever you're ready."
            ),
            view=self,
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cooldowns = {}
        self._xp_lock = asyncio.Lock()
        self._prestige_lock = asyncio.Lock()

    async def cog_load(self):
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_global_levels (
                user_id BIGINT PRIMARY KEY,
                xp BIGINT NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 0,
                prestige INTEGER NOT NULL DEFAULT 0,
                master_mode INTEGER NOT NULL DEFAULT 0,
                master_level INTEGER NOT NULL DEFAULT 0,
                lifetime_xp BIGINT NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_prestige_wallet (
                user_id BIGINT PRIMARY KEY,
                tokens INTEGER NOT NULL DEFAULT 0
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_profile_equipped (
                user_id BIGINT PRIMARY KEY,
                frame_id TEXT NOT NULL DEFAULT 'default',
                theme_id TEXT NOT NULL DEFAULT 'onyx',
                emblem_id TEXT NOT NULL DEFAULT 'default',
                effect_id TEXT NOT NULL DEFAULT 'none',
                title_id TEXT
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_level_settings (
                guild_id BIGINT PRIMARY KEY,
                min_xp INTEGER NOT NULL DEFAULT 15,
                max_xp INTEGER NOT NULL DEFAULT 25,
                cooldown_seconds INTEGER NOT NULL DEFAULT 60,
                announcement_message TEXT NOT NULL DEFAULT '🎉 {mention} reached **{level}**!'
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_level_ignored_channels (
                guild_id BIGINT NOT NULL,
                channel_id BIGINT NOT NULL,
                PRIMARY KEY (guild_id, channel_id)
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_level_announcement_settings (
                guild_id BIGINT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS level_rewards (
                guild_id BIGINT NOT NULL,
                level INTEGER NOT NULL,
                role_id BIGINT NOT NULL,
                PRIMARY KEY (guild_id, level)
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_level_migrations (
                migration_key TEXT PRIMARY KEY,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self.bot.db.execute(
            "INSERT INTO onyx_level_migrations (migration_key) VALUES (?) "
            "ON CONFLICT(migration_key) DO NOTHING",
            ("global_levels_reset_v1",),
        )

    async def settings_for(self, guild_id):
        row = await self.bot.db.fetchone(
            "SELECT * FROM onyx_level_settings WHERE guild_id=?", (guild_id,)
        )
        if row is None:
            await self.bot.db.execute(
                "INSERT INTO onyx_level_settings (guild_id) VALUES (?) "
                "ON CONFLICT(guild_id) DO NOTHING",
                (guild_id,),
            )
            row = await self.bot.db.fetchone(
                "SELECT * FROM onyx_level_settings WHERE guild_id=?", (guild_id,)
            )
        return row

    async def profile(self, user_id: int):
        row = await self.bot.db.fetchone(
            "SELECT * FROM onyx_global_levels WHERE user_id=?", (user_id,)
        )
        if row is None:
            await self.bot.db.execute(
                "INSERT INTO onyx_global_levels (user_id) VALUES (?) "
                "ON CONFLICT(user_id) DO NOTHING",
                (user_id,),
            )
            row = await self.bot.db.fetchone(
                "SELECT * FROM onyx_global_levels WHERE user_id=?", (user_id,)
            )
        return row

    def eligible(self, row) -> bool:
        if row["master_mode"]:
            return int(row["master_level"]) >= MAX_MASTER_LEVEL
        return int(row["level"]) >= MAX_LEVEL

    def unlocked_titles(self, row) -> list[str]:
        if not row["master_mode"]:
            return []
        level = int(row["master_level"])
        return [
            title for threshold, title in MASTER_TITLES.items()
            if level >= threshold
        ]

    def current_master_title(self, row):
        titles = self.unlocked_titles(row)
        return titles[-1] if titles else None

    async def prestige_tokens(self, user_id: int) -> int:
        wallet = await self.bot.db.fetchone(
            "SELECT tokens FROM onyx_prestige_wallet WHERE user_id=?", (user_id,)
        )
        return int(wallet["tokens"]) if wallet else 0

    async def equipped_cosmetics(self, user_id: int):
        await self.bot.db.execute(
            "INSERT INTO onyx_profile_equipped (user_id) VALUES (?) "
            "ON CONFLICT(user_id) DO NOTHING",
            (user_id,),
        )
        row = await self.bot.db.fetchone(
            "SELECT * FROM onyx_profile_equipped WHERE user_id=?", (user_id,)
        )
        return dict(row) if row is not None else {}

    async def apply_prestige(self, user_id: int) -> bool:
        """Apply one valid transition; award tokens only for Prestige I through X."""
        async with self._prestige_lock:
            row = await self.profile(user_id)
            if not self.eligible(row) or row["master_mode"]:
                return False

            prestige = int(row["prestige"])
            if prestige < MAX_PRESTIGE:
                await self.bot.db.execute(
                    """
                    UPDATE onyx_global_levels
                    SET prestige=prestige+1, level=0, xp=0,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE user_id=?
                    """,
                    (user_id,),
                )
                await self.bot.db.execute(
                    """
                    INSERT INTO onyx_prestige_wallet (user_id, tokens)
                    VALUES (?, ?)
                    ON CONFLICT(user_id)
                    DO UPDATE SET tokens =
                        onyx_prestige_wallet.tokens + excluded.tokens
                    """,
                    (user_id, PRESTIGE_TOKEN_REWARD),
                )
            else:
                await self.bot.db.execute(
                    """
                    UPDATE onyx_global_levels
                    SET master_mode=1, master_level=0, level=0, xp=0,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE user_id=?
                    """,
                    (user_id,),
                )
            return True

    async def give_rewards(self, member: discord.Member, level: int):
        rows = await self.bot.db.fetchall(
            "SELECT role_id FROM level_rewards WHERE guild_id=? AND level<=? ORDER BY level",
            (member.guild.id, level),
        )
        added = []
        me = member.guild.me
        if me is None:
            return added

        for item in rows:
            role = member.guild.get_role(item["role_id"])
            if (
                not role or role in member.roles or role.is_default()
                or role.managed or role >= me.top_role
            ):
                continue
            try:
                await member.add_roles(
                    role, reason=f"ONYX global level reward at level {level}"
                )
                added.append(role)
            except (discord.Forbidden, discord.HTTPException):
                pass
        return added

    async def add_xp(self, user_id: int, amount: int):
        async with self._xp_lock:
            old = await self.profile(user_id)
            xp = int(old["xp"]) + amount
            level = int(old["level"])
            master_level = int(old["master_level"])
            gained_levels = 0

            if not old["master_mode"]:
                while level < MAX_LEVEL and xp >= xp_needed(level):
                    xp -= xp_needed(level)
                    level += 1
                    gained_levels += 1
                if level >= MAX_LEVEL:
                    xp = 0
            else:
                while master_level < MAX_MASTER_LEVEL and xp >= xp_needed(master_level):
                    xp -= xp_needed(master_level)
                    master_level += 1
                    gained_levels += 1
                if master_level >= MAX_MASTER_LEVEL:
                    xp = 0

            await self.bot.db.execute(
                """
                UPDATE onyx_global_levels
                SET xp=?, level=?, master_level=?,
                    lifetime_xp=lifetime_xp+?, updated_at=CURRENT_TIMESTAMP
                WHERE user_id=?
                """,
                (xp, level, master_level, amount, user_id),
            )
            new = await self.profile(user_id)
            return old, new, gained_levels

    async def announce_level_up(self, message, settings, new_row, rewards):
        gid = message.guild.id
        pref = await self.bot.db.fetchone(
            "SELECT enabled FROM onyx_level_announcement_settings WHERE guild_id=?",
            (gid,),
        )
        if pref and not pref["enabled"]:
            return

        cfg = await self.bot.db.fetchone(
            "SELECT levelup_channel_id FROM guild_settings WHERE guild_id=?", (gid,)
        )
        channel_id = cfg["levelup_channel_id"] if cfg else None
        channel = message.guild.get_channel(channel_id) if channel_id else message.channel
        if not channel:
            return

        announcement = settings["announcement_message"]
        replacements = {
            "{mention}": message.author.mention,
            "{user}": discord.utils.escape_markdown(message.author.display_name),
            "{level}": stage_label(new_row),
            "{server}": discord.utils.escape_markdown(message.guild.name),
        }
        for token, value in replacements.items():
            announcement = announcement.replace(token, value)

        if rewards:
            announcement += "\n🎁 Reward unlocked: " + ", ".join(
                role.mention for role in rewards
            )
        if self.eligible(new_row) and not new_row["master_mode"]:
            announcement += (
                f"\n🏆 You've reached Level {MAX_LEVEL}! "
                "Use `,prestige` when you're ready to choose your next step."
            )
        try:
            await channel.send(
                announcement,
                allowed_mentions=discord.AllowedMentions(users=True, roles=True),
            )
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if (
            not message.guild or message.author.bot or message.webhook_id
            or len(message.content.strip()) < 3
        ):
            return
        try:
            if (await self.bot.get_context(message)).valid:
                return
        except Exception:
            pass

        gid = message.guild.id
        settings = await self.settings_for(gid)
        enabled = await self.bot.db.fetchone(
            "SELECT xp_enabled FROM guild_settings WHERE guild_id=?", (gid,)
        )
        if enabled and not enabled["xp_enabled"]:
            return

        ignored = await self.bot.db.fetchone(
            "SELECT 1 FROM onyx_level_ignored_channels "
            "WHERE guild_id=? AND channel_id=?",
            (gid, message.channel.id),
        )
        if ignored:
            return

        now = time.monotonic()
        user_id = message.author.id
        if now - self.cooldowns.get(user_id, 0) < settings["cooldown_seconds"]:
            return
        self.cooldowns[user_id] = now

        gained = random.randint(settings["min_xp"], settings["max_xp"])
        _, new, gained_levels = await self.add_xp(user_id, gained)
        if gained_levels:
            reward_level = (
                new["master_level"] if new["master_mode"] else new["level"]
            )
            rewards = await self.give_rewards(message.author, reward_level)
            await self.announce_level_up(message, settings, new, rewards)

    
    @commands.command(name="rank", aliases=["level"], help="View your ONYX profile card.")
    @commands.guild_only()
    async def rank(self, ctx, member: discord.Member = None):
        member = member or ctx.author

        row = await self.profile(member.id)
        unlocked = self.unlocked_titles(row)
        tokens = await self.prestige_tokens(member.id)
        cosmetics = await self.equipped_cosmetics(member.id)

        card = render_shared_profile_card(
            display_name=member.display_name,
            row=row,
            unlocked_titles=unlocked,
            tokens=tokens,
            cosmetics=cosmetics,
        )

        filename = f"onyx-profile-{member.id}.png"

        await ctx.send(
            file=discord.File(card, filename=filename)
        )


    @commands.command(name="leaderboard", aliases=["levels_top"])
    @commands.guild_only()
    async def leaderboard(self, ctx):
        rows = await self.bot.db.fetchall(
            """
            SELECT user_id,prestige,level,master_level,xp,lifetime_xp
            FROM onyx_global_levels
            ORDER BY master_mode DESC,prestige DESC,master_level DESC,level DESC,xp DESC
            LIMIT 10
            """
        )
        if not rows:
            return await ctx.send("No global level data yet. Start chatting to earn XP!")
        lines = []
        for i, row in enumerate(rows, 1):
            user = self.bot.get_user(row["user_id"])
            name = (
                discord.utils.escape_markdown(user.display_name)
                if user else f"User {row['user_id']}"
            )
            lines.append(
                f"**{i}.** {name} — {stage_label(row)} • "
                f"{row['lifetime_xp']:,} lifetime XP"
            )
        embed = discord.Embed(
            title="🏆 ONYX • Global Leaderboard",
            description="\n".join(lines),
            color=COLOR,
        )
        embed.set_footer(text="Rankings are shared across all ONYX servers")
        await ctx.send(embed=embed)

    @commands.group(name="prestige", invoke_without_command=True)
    @commands.guild_only()
    async def prestige(self, ctx):
        row = await self.profile(ctx.author.id)
        if row["master_mode"] and row["master_level"] >= MAX_MASTER_LEVEL:
            return await ctx.send(
                f"🏆 You have completed the ONYX Prestige track at "
                f"**Prestige Master Level {MAX_MASTER_LEVEL:,}**!"
            )
        if not self.eligible(row):
            return await ctx.send(
                f"You are **{stage_label(row)}**. Reach Level 60 to unlock "
                "your next Prestige choice."
            )

        if not row["master_mode"] and row["prestige"] < MAX_PRESTIGE:
            description = (
                f"You've reached **Level {MAX_LEVEL}**. Choose whether to reset "
                f"to Level 0 and unlock Prestige **{row['prestige'] + 1}**, or "
                "keep your current rank. Each Prestige from I–X awards 10 "
                "Prestige Tokens. Lifetime XP and previously earned server "
                "roles stay intact."
            )
        else:
            description = (
                f"You've completed **Prestige {MAX_PRESTIGE} Level {MAX_LEVEL}**. "
                "Confirm to enter the **Prestige Master** track (1,000 levels)."
            )

        embed = discord.Embed(
            title="🏆 ONYX • Prestige Available",
            description=description,
            color=COLOR,
        )
        await ctx.send(embed=embed, view=PrestigeChoiceView(self, ctx.author.id))

    @prestige.command(name="leaderboard")
    async def prestige_leaderboard(self, ctx):
        rows = await self.bot.db.fetchall(
            """
            SELECT user_id,prestige,level,master_level,lifetime_xp
            FROM onyx_global_levels WHERE prestige>0
            ORDER BY master_mode DESC,prestige DESC,master_level DESC,
                     level DESC,lifetime_xp DESC
            LIMIT 10
            """
        )
        if not rows:
            return await ctx.send("No one has earned Prestige yet.")
        lines = []
        for i, row in enumerate(rows, 1):
            user = self.bot.get_user(row["user_id"])
            name = (
                discord.utils.escape_markdown(user.display_name)
                if user else f"User {row['user_id']}"
            )
            lines.append(f"**{i}.** {name} — {stage_label(row)}")
        await ctx.send(
            embed=discord.Embed(
                title="🏅 ONYX • Prestige Leaderboard",
                description="\n".join(lines),
                color=COLOR,
            )
        )

    @commands.group(name="levels", invoke_without_command=True)
    @commands.guild_only()
    async def levels(self, ctx):
        settings = await self.settings_for(ctx.guild.id)
        enabled = await self.bot.db.fetchone(
            "SELECT xp_enabled FROM guild_settings WHERE guild_id=?",
            (ctx.guild.id,),
        )
        active = enabled["xp_enabled"] if enabled else 1
        embed = discord.Embed(title="ONYX • Global Leveling Settings", color=COLOR)
        embed.add_field(name="Server XP status", value="Enabled" if active else "Disabled")
        embed.add_field(
            name="XP per message",
            value=f"{settings['min_xp']}–{settings['max_xp']}",
        )
        embed.add_field(
            name="Global cooldown",
            value=f"{settings['cooldown_seconds']} seconds",
        )
        embed.add_field(
            name="Progression",
            value="10 Prestiges • Level 1–60 each • Prestige Master 1–1,000",
            inline=False,
        )
        embed.add_field(
            name="Commands",
            value=(
                "`,rank [member]` • `,leaderboard` • `,prestige`\n"
                "`,levels enable/disable` • `,levels rate <min> <max>`\n"
                "`,levels cooldown <seconds>` • `,levels channel #channel`\n"
                "`,levels announcements on/off` • `,levels message <text>`\n"
                "`,levels ignore add/remove/list #channel`\n"
                "`,levels reward add/remove/list ...`\n"
                "Owner: `,levels xp add/set/remove @member <amount>` and "
                "`,levels reset @member/all`"
            ),
            inline=False,
        )
        await ctx.send(embed=embed)

    @levels.command(name="announcements")
    @commands.has_guild_permissions(manage_guild=True)
    async def announcements(self, ctx, setting: str):
        setting = setting.casefold()
        if setting not in ("on", "off", "enable", "disable"):
            return await ctx.send(
                f"Use `{ctx.prefix}levels announcements on` or "
                "` ,levels announcements off`."
            )
        enabled = setting in ("on", "enable")
        await self.bot.db.execute(
            """
            INSERT INTO onyx_level_announcement_settings (guild_id,enabled)
            VALUES (?,?)
            ON CONFLICT(guild_id)
            DO UPDATE SET enabled=excluded.enabled
            """,
            (ctx.guild.id, int(enabled)),
        )
        await ctx.send(
            "✅ Level-up announcements enabled."
            if enabled else
            "🔕 Level-up announcements disabled. XP still accumulates globally."
        )

    @commands.command(name="levelmessages")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def levelmessages(self, ctx, setting: str):
        setting = setting.casefold()
        if setting not in ("on", "off"):
            return await ctx.send(f"Use `{ctx.prefix}levelmessages on` or `,levelmessages off`.")
        enabled = int(setting == "on")
        await self.bot.db.execute(
            """
            INSERT INTO onyx_level_announcement_settings (guild_id,enabled)
            VALUES (?,?)
            ON CONFLICT(guild_id)
            DO UPDATE SET enabled=excluded.enabled
            """,
            (ctx.guild.id, enabled),
        )
        await ctx.send(
            "✅ Level-up messages enabled in this server."
            if enabled else
            "🔕 Level-up messages disabled in this server. Global XP will continue."
        )

    @levels.command(name="enable")
    @commands.has_guild_permissions(manage_guild=True)
    async def enable(self, ctx):
        await self.bot.db.execute(
            "INSERT INTO guild_settings (guild_id,xp_enabled) VALUES (?,1) "
            "ON CONFLICT(guild_id) DO UPDATE SET xp_enabled=1",
            (ctx.guild.id,),
        )
        await ctx.send("✅ XP earning enabled in this server.")

    @levels.command(name="disable")
    @commands.has_guild_permissions(manage_guild=True)
    async def disable(self, ctx):
        await self.bot.db.execute(
            "INSERT INTO guild_settings (guild_id,xp_enabled) VALUES (?,0) "
            "ON CONFLICT(guild_id) DO UPDATE SET xp_enabled=0",
            (ctx.guild.id,),
        )
        await ctx.send("⏸️ XP earning disabled in this server. Global profiles remain intact.")

    @levels.command(name="rate")
    @commands.has_guild_permissions(manage_guild=True)
    async def rate(self, ctx, minimum: int, maximum: int):
        if not 1 <= minimum <= maximum <= 1000:
            return await ctx.send("Use values from 1–1,000, with minimum no higher than maximum.")
        await self.bot.db.execute(
            """
            INSERT INTO onyx_level_settings (guild_id,min_xp,max_xp)
            VALUES (?,?,?)
            ON CONFLICT(guild_id)
            DO UPDATE SET min_xp=excluded.min_xp,max_xp=excluded.max_xp
            """,
            (ctx.guild.id, minimum, maximum),
        )
        await ctx.send(
            f"✅ This server now awards **{minimum}–{maximum} XP** per eligible message."
        )

    @levels.command(name="cooldown")
    @commands.has_guild_permissions(manage_guild=True)
    async def cooldown(self, ctx, seconds: int):
        if not 5 <= seconds <= 3600:
            return await ctx.send("Cooldown must be between 5 and 3,600 seconds.")
        await self.bot.db.execute(
            """
            INSERT INTO onyx_level_settings (guild_id,cooldown_seconds)
            VALUES (?,?)
            ON CONFLICT(guild_id)
            DO UPDATE SET cooldown_seconds=excluded.cooldown_seconds
            """,
            (ctx.guild.id, seconds),
        )
        await ctx.send(
            f"✅ Global user cooldown set to **{seconds} seconds** when earning XP in this server."
        )

    @levels.command(name="channel")
    @commands.has_guild_permissions(manage_guild=True)
    async def channel(self, ctx, channel: discord.TextChannel = None):
        await self.bot.db.execute(
            """
            INSERT INTO guild_settings (guild_id,levelup_channel_id)
            VALUES (?,?)
            ON CONFLICT(guild_id)
            DO UPDATE SET levelup_channel_id=excluded.levelup_channel_id
            """,
            (ctx.guild.id, channel.id if channel else None),
        )
        await ctx.send(
            f"✅ Level-up announcements set to {channel.mention}."
            if channel else
            "✅ Announcements will appear in the channel where XP was earned."
        )

    @levels.command(name="message")
    @commands.has_guild_permissions(manage_guild=True)
    async def message(self, ctx, *, text: str):
        allowed = {"{mention}", "{user}", "{level}", "{server}"}
        tokens = set(re.findall(r"\{[^{}]+\}", text))
        if len(text) > 1000 or tokens - allowed:
            return await ctx.send(
                "Message must be 1,000 characters or fewer. Placeholders: "
                "`{mention}`, `{user}`, `{level}`, `{server}`."
            )
        await self.bot.db.execute(
            """
            INSERT INTO onyx_level_settings (guild_id,announcement_message)
            VALUES (?,?)
            ON CONFLICT(guild_id)
            DO UPDATE SET announcement_message=excluded.announcement_message
            """,
            (ctx.guild.id, text),
        )
        await ctx.send("✅ Level-up announcement updated.")

    @levels.group(name="ignore", invoke_without_command=True)
    @commands.has_guild_permissions(manage_guild=True)
    async def ignore(self, ctx):
        await ctx.send(f"Use `{ctx.prefix}levels ignore add/remove/list #channel`.")

    @ignore.command(name="add")
    @commands.has_guild_permissions(manage_guild=True)
    async def ignore_add(self, ctx, channel: discord.TextChannel):
        await self.bot.db.execute(
            "INSERT INTO onyx_level_ignored_channels (guild_id,channel_id) "
            "VALUES (?,?) ON CONFLICT DO NOTHING",
            (ctx.guild.id, channel.id),
        )
        await ctx.send(f"🚫 {channel.mention} will not award XP.")

    @ignore.command(name="remove")
    @commands.has_guild_permissions(manage_guild=True)
    async def ignore_remove(self, ctx, channel: discord.TextChannel):
        await self.bot.db.execute(
            "DELETE FROM onyx_level_ignored_channels WHERE guild_id=? AND channel_id=?",
            (ctx.guild.id, channel.id),
        )
        await ctx.send(f"✅ XP earning restored in {channel.mention}.")

    @ignore.command(name="list")
    @commands.has_guild_permissions(manage_guild=True)
    async def ignore_list(self, ctx):
        rows = await self.bot.db.fetchall(
            "SELECT channel_id FROM onyx_level_ignored_channels WHERE guild_id=?",
            (ctx.guild.id,),
        )
        description = "\n".join(f"• <#{row['channel_id']}>" for row in rows)
        await ctx.send(
            embed=discord.Embed(
                title="ONYX • Ignored XP Channels",
                description=description or "No ignored channels.",
                color=COLOR,
            )
        )

    @levels.group(name="reward", invoke_without_command=True)
    @commands.has_guild_permissions(manage_guild=True)
    async def reward(self, ctx):
        await ctx.send(
            f"Use `{ctx.prefix}levels reward add <level> @role`, "
            "`remove <level>`, or `list`."
        )

    @reward.command(name="add")
    @commands.has_guild_permissions(manage_guild=True)
    async def reward_add(self, ctx, level: int, role: discord.Role):
        me = ctx.guild.me
        if (
            not 1 <= level <= 1000 or role.is_default() or role.managed
            or not me or role >= me.top_role
        ):
            return await ctx.send(
                "Choose a level from 1–1,000 and a role ONYX can assign "
                "(check role hierarchy)."
            )
        await self.bot.db.execute(
            """
            INSERT INTO level_rewards (guild_id,level,role_id)
            VALUES (?,?,?)
            ON CONFLICT(guild_id,level) DO UPDATE SET role_id=excluded.role_id
            """,
            (ctx.guild.id, level, role.id),
        )
        await ctx.send(
            f"🎁 {role.mention} will be awarded at global level **{level}** in this server."
        )

    @reward.command(name="remove")
    @commands.has_guild_permissions(manage_guild=True)
    async def reward_remove(self, ctx, level: int):
        await self.bot.db.execute(
            "DELETE FROM level_rewards WHERE guild_id=? AND level=?",
            (ctx.guild.id, level),
        )
        await ctx.send(f"Removed the level **{level}** reward, if one existed.")

    @reward.command(name="list")
    @commands.has_guild_permissions(manage_guild=True)
    async def reward_list(self, ctx):
        rows = await self.bot.db.fetchall(
            "SELECT level,role_id FROM level_rewards WHERE guild_id=? ORDER BY level",
            (ctx.guild.id,),
        )
        description = "\n".join(
            f"Level **{row['level']}** → <@&{row['role_id']}>"
            for row in rows
        )
        await ctx.send(
            embed=discord.Embed(
                title="ONYX • Server Role Rewards",
                description=description or "No rewards configured.",
                color=COLOR,
            )
        )

    @levels.group(name="xp", invoke_without_command=True)
    @commands.is_owner()
    async def xp(self, ctx):
        await ctx.send(
            f"Owner-only global XP tools: `{ctx.prefix}levels xp add/set/remove @member <amount>`."
        )

    async def change_xp(self, ctx, member, amount, mode):
        if not 1 <= amount <= 10_000_000:
            return await ctx.send("Amount must be between 1 and 10,000,000 XP.")
        row = await self.profile(member.id)
        if mode == "add":
            _, new, _ = await self.add_xp(member.id, amount)
        else:
            current = int(row["xp"])
            value = amount if mode == "set" else max(0, current - amount)
            await self.bot.db.execute(
                "UPDATE onyx_global_levels SET xp=?,updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
                (value, member.id),
            )
            new = await self.profile(member.id)
        verb = {
            "add": "Added",
            "set": "Set current-level XP for",
            "remove": "Removed current-level XP from",
        }[mode]
        await ctx.send(
            f"✅ {verb} {member.mention}. Current rank: **{stage_label(new)}** "
            f"• XP: **{new['xp']:,}** • Lifetime XP: **{new['lifetime_xp']:,}**."
        )

    @xp.command(name="add")
    @commands.is_owner()
    async def xp_add(self, ctx, member: discord.User, amount: int):
        await self.change_xp(ctx, member, amount, "add")

    @xp.command(name="set")
    @commands.is_owner()
    async def xp_set(self, ctx, member: discord.User, amount: int):
        await self.change_xp(ctx, member, amount, "set")

    @xp.command(name="remove")
    @commands.is_owner()
    async def xp_remove(self, ctx, member: discord.User, amount: int):
        await self.change_xp(ctx, member, amount, "remove")

    @levels.command(name="reset")
    @commands.is_owner()
    async def reset(self, ctx, target: str = None):
        if not target:
            return await ctx.send(
                f"Use `{ctx.prefix}levels reset @user` or "
                f"`{ctx.prefix}levels reset all`. This affects global profiles."
            )
        if target.casefold() == "all":
            await self.bot.db.execute("DELETE FROM onyx_global_levels")
            await ctx.send(
                "✅ All ONYX global leveling profiles have been reset to Level 0. "
                "Server settings and rewards were preserved."
            )
            return
        try:
            user = await commands.UserConverter().convert(ctx, target)
        except commands.BadArgument:
            return await ctx.send("Mention a Discord user or use `all`.")
        await self.bot.db.execute(
            "DELETE FROM onyx_global_levels WHERE user_id=?", (user.id,)
        )
        await ctx.send(
            f"✅ Global leveling profile for {user.mention} has been reset."
        )


async def setup(bot):
    await bot.add_cog(Levels(bot))
