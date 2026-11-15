"""ONYX global leveling, Prestige progression, and Prestige Master titles.

Progression is global by Discord user ID. XP earning has one shared rate and
cooldown across every server where ONYX is installed. Legacy server-level
settings tables are intentionally left untouched for backwards compatibility.
"""

import asyncio
import random
import time

import discord
from discord.ext import commands

from profile_card_renderer import render_onyx_profile_card as render_shared_profile_card

COLOR = discord.Color.from_rgb(25, 190, 190)

BASE_XP = 100
LINEAR_XP = 50
QUADRATIC_XP = 5
MAX_LEVEL = 60
MAX_PRESTIGE = 10
MAX_MASTER_LEVEL = 1000
PRESTIGE_TOKEN_REWARD = 10

# One global earning policy. These values are not configurable per server.
GLOBAL_MIN_XP = 15
GLOBAL_MAX_XP = 25
GLOBAL_XP_COOLDOWN = 60

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


def xp_needed(level: int) -> int:
    """Return XP required to advance from the supplied level."""
    return max(1, int(BASE_XP + LINEAR_XP * level + QUADRATIC_XP * level * level))


def progress_bar(current: int, required: int, size: int = 14) -> str:
    ratio = min(1.0, max(0.0, current / required)) if required else 1.0
    filled = int(ratio * size)
    return "▰" * filled + "▱" * (size - filled)


def stage_label(row) -> str:
    if row["master_mode"]:
        return (
            f"Prestige Master • Level "
            f"{int(row['master_level']):,}/{MAX_MASTER_LEVEL:,}"
        )
    if row["prestige"]:
        return (
            f"Prestige {int(row['prestige'])} • "
            f"Level {int(row['level']):,}/{MAX_LEVEL}"
        )
    return f"Level {int(row['level']):,}/{MAX_LEVEL}"


def render_onyx_profile_card(
    display_name: str,
    row,
    unlocked_titles: list[str],
    tokens: int,
    cosmetics=None,
):
    """Compatibility wrapper used by the Prestige Shop preview commands."""
    return render_shared_profile_card(
        display_name=display_name,
        row=row,
        unlocked_titles=unlocked_titles,
        tokens=tokens,
        cosmetics=cosmetics or {},
    )


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

    @discord.ui.button(
        label="Prestige", style=discord.ButtonStyle.primary, emoji="⬆️"
    )
    async def prestige(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
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

    @discord.ui.button(
        label="Stay at Level 60", style=discord.ButtonStyle.secondary, emoji="🛡️"
    )
    async def stay(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
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


class ConfirmGlobalResetView(discord.ui.View):
    """Require an explicit button press before resetting every global profile."""

    def __init__(self, owner_id: int, cog):
        super().__init__(timeout=60)
        self.owner_id = owner_id
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the bot owner can confirm this action.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(
        label="Confirm global reset",
        style=discord.ButtonStyle.danger,
        emoji="⚠️",
    )
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self.cog.bot.db.execute("DELETE FROM onyx_global_levels")
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=(
                "Global leveling profiles have been reset. "
                "Prestige token wallets and equipped cosmetics were not changed."
            ),
            view=self,
        )

    @discord.ui.button(
        label="Cancel", style=discord.ButtonStyle.secondary
    )
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="Global reset cancelled. No progression data was changed.",
            view=self,
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Keyed only by Discord user ID: the cooldown is shared across servers.
        self.cooldowns = {}
        self._xp_lock = asyncio.Lock()
        self._prestige_lock = asyncio.Lock()

    async def cog_load(self):
        # These are the established global tables used by the website and shop.
        # Their names and columns must remain compatible with existing services.
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

        # Keep the pre-existing migration marker behavior. No global progress
        # reset or destructive migration is performed by this cog.
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
        """Apply one valid Prestige transition and award its token reward."""
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
                while (
                    master_level < MAX_MASTER_LEVEL
                    and xp >= xp_needed(master_level)
                ):
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

    async def announce_level_up(self, message, new_row):
        """Announce in the channel where the globally-earned level was reached."""
        if not message.guild or not message.channel:
            return

        if new_row["master_mode"]:
            level_text = f"Prestige Master Level {int(new_row['master_level']):,}"
        else:
            level_text = stage_label(new_row)

        if self.eligible(new_row) and not new_row["master_mode"]:
            ending = (
                f"\n🏆 You've reached Level {MAX_LEVEL}! "
                "Use `,prestige` when you're ready to choose your next step."
            )
        else:
            ending = ""

        try:
            await message.channel.send(
                f"🎉 {message.author.mention} reached **{level_text}**!{ending}",
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if (
            not message.guild
            or message.author.bot
            or message.webhook_id
            or len(message.content.strip()) < 3
        ):
            return

        # Commands do not earn XP. The message still reaches the normal
        # command processor in main.py after this listener returns.
        try:
            if (await self.bot.get_context(message)).valid:
                return
        except Exception:
            pass

        user_id = message.author.id
        now = time.monotonic()
        if now - self.cooldowns.get(user_id, 0) < GLOBAL_XP_COOLDOWN:
            return

        # Reserve the cooldown before the database operation so simultaneous
        # messages from the same user cannot award XP in two servers at once.
        self.cooldowns[user_id] = now
        gained = random.randint(GLOBAL_MIN_XP, GLOBAL_MAX_XP)
        try:
            _, new, gained_levels = await self.add_xp(user_id, gained)
        except Exception:
            # Do not consume a cooldown if the database write failed.
            self.cooldowns.pop(user_id, None)
            raise

        if gained_levels:
            await self.announce_level_up(message, new)

    @commands.command(
        name="rank",
        aliases=["level"],
        help="View your global ONYX profile card.",
    )
    async def rank(self, ctx, member: discord.User = None):
        member = member or ctx.author
        row = await self.profile(member.id)
        unlocked = self.unlocked_titles(row)
        tokens = await self.prestige_tokens(member.id)
        cosmetics = await self.equipped_cosmetics(member.id)

        display_name = getattr(member, "display_name", None) or member.name
        card = render_shared_profile_card(
            display_name=display_name,
            row=row,
            unlocked_titles=unlocked,
            tokens=tokens,
            cosmetics=cosmetics,
        )
        await ctx.send(
            file=discord.File(card, filename=f"onyx-profile-{member.id}.png")
        )

    @commands.command(
        name="leaderboard",
        aliases=["levels_top"],
        help="View the global ONYX leveling leaderboard.",
    )
    async def leaderboard(self, ctx):
        rows = await self.bot.db.fetchall(
            """
            SELECT user_id,prestige,level,master_mode,master_level,xp,lifetime_xp
            FROM onyx_global_levels
            ORDER BY master_mode DESC,prestige DESC,master_level DESC,
                     level DESC,xp DESC
            LIMIT 10
            """
        )
        if not rows:
            return await ctx.send(
                "No global level data yet. Start chatting to earn XP!"
            )

        lines = []
        for index, row in enumerate(rows, 1):
            user = self.bot.get_user(row["user_id"])
            name = (
                discord.utils.escape_markdown(user.display_name)
                if user else f"User {row['user_id']}"
            )
            lines.append(
                f"**{index}.** {name} — {stage_label(row)} • "
                f"{int(row['lifetime_xp']):,} lifetime XP"
            )

        embed = discord.Embed(
            title="🏆 ONYX • Global Leaderboard",
            description="\n".join(lines),
            color=COLOR,
        )
        embed.set_footer(text="Rankings are shared across all ONYX servers")
        await ctx.send(embed=embed)

    @commands.group(
        name="prestige",
        invoke_without_command=True,
        help="View and claim your global Prestige progression.",
    )
    async def prestige(self, ctx):
        row = await self.profile(ctx.author.id)
        if row["master_mode"] and int(row["master_level"]) >= MAX_MASTER_LEVEL:
            return await ctx.send(
                f"🏆 You have completed the ONYX Prestige track at "
                f"**Prestige Master Level {MAX_MASTER_LEVEL:,}**!"
            )

        if not self.eligible(row):
            return await ctx.send(
                f"You are **{stage_label(row)}**. Reach Level 60 to unlock "
                "your next Prestige choice."
            )

        if not row["master_mode"] and int(row["prestige"]) < MAX_PRESTIGE:
            description = (
                f"You've reached **Level {MAX_LEVEL}**. Choose whether to reset "
                f"to Level 0 and unlock Prestige **{int(row['prestige']) + 1}**, or "
                "keep your current rank. Each Prestige from I–X awards 10 "
                "Prestige Tokens. Your lifetime XP is preserved."
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
        await ctx.send(
            embed=embed,
            view=PrestigeChoiceView(self, ctx.author.id),
        )

    @prestige.command(
        name="leaderboard",
        help="View the global Prestige leaderboard.",
    )
    async def prestige_leaderboard(self, ctx):
        rows = await self.bot.db.fetchall(
            """
            SELECT user_id,prestige,level,master_mode,master_level,lifetime_xp
            FROM onyx_global_levels
            WHERE prestige>0 OR master_mode=1
            ORDER BY master_mode DESC,prestige DESC,master_level DESC,
                     level DESC,lifetime_xp DESC
            LIMIT 10
            """
        )
        if not rows:
            return await ctx.send("No one has earned Prestige yet.")

        lines = []
        for index, row in enumerate(rows, 1):
            user = self.bot.get_user(row["user_id"])
            name = (
                discord.utils.escape_markdown(user.display_name)
                if user else f"User {row['user_id']}"
            )
            lines.append(f"**{index}.** {name} — {stage_label(row)}")

        await ctx.send(
            embed=discord.Embed(
                title="🏅 ONYX • Prestige Leaderboard",
                description="\n".join(lines),
                color=COLOR,
            )
        )

    async def change_xp(self, ctx, member, amount, mode):
        if not 1 <= amount <= 10_000_000:
            return await ctx.send(
                "Amount must be between 1 and 10,000,000 XP."
            )

        row = await self.profile(member.id)
        if mode == "add":
            _, new, _ = await self.add_xp(member.id, amount)
        else:
            current = int(row["xp"])
            value = amount if mode == "set" else max(0, current - amount)
            await self.bot.db.execute(
                """
                UPDATE onyx_global_levels
                SET xp=?,updated_at=CURRENT_TIMESTAMP
                WHERE user_id=?
                """,
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
            f"• XP: **{int(new['xp']):,}** "
            f"• Lifetime XP: **{int(new['lifetime_xp']):,}**."
        )

    @commands.group(
        name="leveladmin",
        invoke_without_command=True,
        hidden=True,
    )
    @commands.is_owner()
    async def leveladmin(self, ctx):
        await ctx.send(
            "Owner-only global leveling tools:\n"
            "`,leveladmin xp add @user <amount>`\n"
            "`,leveladmin xp set @user <amount>`\n"
            "`,leveladmin xp remove @user <amount>`\n"
            "`,leveladmin reset @user` or `,leveladmin reset all`"
        )

    @leveladmin.group(name="xp", invoke_without_command=True, hidden=True)
    @commands.is_owner()
    async def leveladmin_xp(self, ctx):
        await ctx.send(
            f"Use `{ctx.prefix}leveladmin xp add/set/remove @user <amount>`."
        )

    @leveladmin_xp.command(name="add", hidden=True)
    @commands.is_owner()
    async def xp_add(self, ctx, member: discord.User, amount: int):
        await self.change_xp(ctx, member, amount, "add")

    @leveladmin_xp.command(name="set", hidden=True)
    @commands.is_owner()
    async def xp_set(self, ctx, member: discord.User, amount: int):
        await self.change_xp(ctx, member, amount, "set")

    @leveladmin_xp.command(name="remove", hidden=True)
    @commands.is_owner()
    async def xp_remove(self, ctx, member: discord.User, amount: int):
        await self.change_xp(ctx, member, amount, "remove")

    @leveladmin.command(name="reset", hidden=True)
    @commands.is_owner()
    async def reset(self, ctx, target: str = None):
        if not target:
            return await ctx.send(
                f"Use `{ctx.prefix}leveladmin reset @user` or "
                f"`{ctx.prefix}leveladmin reset all`."
            )

        if target.casefold() == "all":
            return await ctx.send(
                "⚠️ This will reset every user's global XP, level, Prestige, "
                "and Prestige Master progression. Token wallets and equipped "
                "cosmetics will remain untouched.",
                view=ConfirmGlobalResetView(ctx.author.id, self),
            )

        try:
            user = await commands.UserConverter().convert(ctx, target)
        except commands.BadArgument:
            return await ctx.send("Mention a Discord user or provide their user ID.")

        await self.bot.db.execute(
            "DELETE FROM onyx_global_levels WHERE user_id=?", (user.id,)
        )
        await ctx.send(
            f"✅ Global leveling profile for {user.mention} has been reset. "
            "Their Prestige token wallet and equipped cosmetics were preserved."
        )


async def setup(bot):
    await bot.add_cog(Levels(bot))
