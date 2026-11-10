import random
import re
import time
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks


COLOR = discord.Color.from_rgb(44, 38, 67)
ACCENT = discord.Color.from_rgb(35, 190, 170)


def parse_duration(value: str) -> int:
    """Parse durations such as 30m, 2h, 1d, or 1d2h30m."""
    value = value.strip().lower().replace(" ", "")
    matches = list(re.finditer(r"(\d+)([smhd])", value))
    if not matches:
        raise ValueError("Use a duration such as `30m`, `2h`, or `1d`.")

    rebuilt = "".join(match.group(0) for match in matches)
    if rebuilt != value:
        raise ValueError("Use a duration such as `30m`, `2h`, or `1d`.")

    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    seconds = sum(int(match.group(1)) * multipliers[match.group(2)] for match in matches)

    if seconds < 60:
        raise ValueError("Giveaways must last at least 1 minute.")
    if seconds > 30 * 86400:
        raise ValueError("Giveaways can last up to 30 days.")
    return seconds


def giveaway_embed(prize, winner_count, host_id, ends_at, entries=0, ended=False, winners=None):
    embed = discord.Embed(
        title="🎉 ONYX GIVEAWAY",
        description=f"**Prize**\n{prize}",
        color=ACCENT if ended else COLOR,
        timestamp=datetime.fromtimestamp(ends_at, tz=timezone.utc)
    )
    embed.add_field(name="🏆 Winners", value=str(winner_count), inline=True)
    embed.add_field(name="👥 Entries", value=f"{entries:,}", inline=True)
    embed.add_field(
        name="⏰ Ends",
        value=f"<t:{ends_at}:R>" if not ended else "Giveaway ended",
        inline=True
    )
    embed.add_field(name="Hosted by", value=f"<@{host_id}>", inline=False)

    if ended:
        if winners:
            embed.add_field(
                name="🎊 Winner(s)",
                value=", ".join(f"<@{user_id}>" for user_id in winners),
                inline=False
            )
        else:
            embed.add_field(
                name="🎊 Result",
                value="No valid entries were received.",
                inline=False
            )
        embed.set_footer(text="ONYX • Giveaway ended")
    else:
        embed.set_footer(text="Press Enter Giveaway below to participate • Good luck!")
    return embed


class GiveawayEntryView(discord.ui.View):
    """Persistent entry button for active giveaways."""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Enter Giveaway",
        emoji="🎉",
        style=discord.ButtonStyle.success,
        custom_id="onyx:giveaway:enter"
    )
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild_id is None or interaction.message is None:
            return await interaction.response.send_message(
                "Giveaways can only be entered inside a server.",
                ephemeral=True
            )

        row = await self.bot.db.fetchone(
            "SELECT guild_id, prize, winner_count, host_id, ends_at, ended "
            "FROM onyx_giveaways WHERE message_id=? AND guild_id=?",
            (interaction.message.id, interaction.guild_id)
        )
        if not row or row["ended"] or row["ends_at"] <= int(time.time()):
            return await interaction.response.send_message(
                "This giveaway has already ended.",
                ephemeral=True
            )

        await self.bot.db.execute(
            "INSERT INTO onyx_giveaway_entries (message_id, guild_id, user_id) "
            "VALUES (?,?,?) ON CONFLICT(message_id,user_id) DO NOTHING",
            (interaction.message.id, interaction.guild_id, interaction.user.id)
        )
        count_row = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS entry_count FROM onyx_giveaway_entries WHERE message_id=?",
            (interaction.message.id,)
        )
        count = count_row["entry_count"] if count_row else 0
        embed = giveaway_embed(
            row["prize"], row["winner_count"], row["host_id"],
            row["ends_at"], count
        )
        try:
            await interaction.message.edit(embed=embed, view=self)
        except discord.HTTPException:
            pass

        await interaction.response.send_message(
            "🎉 You're entered! Good luck.",
            ephemeral=True
        )


class GiveawayPreviewView(discord.ui.View):
    def __init__(self, bot, author_id, channel, prize, winner_count, duration):
        super().__init__(timeout=300)
        self.bot = bot
        self.author_id = author_id
        self.channel = channel
        self.prize = prize
        self.winner_count = winner_count
        self.duration = duration
        self.finished = False

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the person who created this giveaway can confirm it.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Start Giveaway", emoji="🚀", style=discord.ButtonStyle.success)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.finished:
            return await interaction.response.send_message(
                "This preview has already been used.",
                ephemeral=True
            )
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message(
                "You need Manage Server permission to start a giveaway.",
                ephemeral=True
            )

        self.finished = True
        for item in self.children:
            item.disabled = True

        ends_at = int(time.time()) + self.duration
        embed = giveaway_embed(
            self.prize, self.winner_count, self.author_id, ends_at, 0
        )

        try:
            message = await self.channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none()
            )
            await self.bot.db.execute(
                "INSERT INTO onyx_giveaways "
                "(guild_id, channel_id, message_id, host_id, prize, winner_count, ends_at, ended) "
                "VALUES (?,?,?,?,?,?,?,0)",
                (
                    interaction.guild_id, self.channel.id, message.id,
                    self.author_id, self.prize, self.winner_count, ends_at
                )
            )
            await message.edit(view=self.bot.giveaway_entry_view)
            await interaction.response.edit_message(
                content=f"✅ Giveaway started in {self.channel.mention}!",
                embed=None,
                view=self
            )
        except Exception:
            self.finished = False
            for item in self.children:
                item.disabled = False
            raise

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.finished = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="Giveaway creation cancelled.",
            embed=None,
            view=self
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class GiveawayModal(discord.ui.Modal, title="Create an ONYX Giveaway"):
    duration = discord.ui.TextInput(
        label="Time limit",
        placeholder="Examples: 30m, 2h, 1d, 1d2h",
        max_length=30
    )
    winner_count = discord.ui.TextInput(
        label="Number of winners",
        placeholder="Example: 1",
        max_length=2
    )
    prize = discord.ui.TextInput(
        label="What's being given away?",
        placeholder="Example: Discord Nitro",
        max_length=150
    )

    def __init__(self, bot, channel, author_id):
        super().__init__()
        self.bot = bot
        self.channel = channel
        self.author_id = author_id

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message(
                "You need Manage Server permission to create giveaways.",
                ephemeral=True
            )

        try:
            seconds = parse_duration(str(self.duration.value))
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)

        try:
            winners = int(str(self.winner_count.value).strip())
            if not 1 <= winners <= 50:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message(
                "The number of winners must be between 1 and 50.",
                ephemeral=True
            )

        prize = str(self.prize.value).strip()
        if not prize:
            return await interaction.response.send_message(
                "Please enter what is being given away.",
                ephemeral=True
            )

        ends_at = int(time.time()) + seconds
        embed = discord.Embed(
            title="✨ Giveaway Preview",
            description=f"**Prize**\n{prize}",
            color=COLOR
        )
        embed.add_field(name="🏆 Winners", value=str(winners), inline=True)
        embed.add_field(name="⏳ Duration", value=str(self.duration.value), inline=True)
        embed.add_field(name="📍 Channel", value=self.channel.mention, inline=True)
        embed.add_field(name="Ends", value=f"<t:{ends_at}:F> (<t:{ends_at}:R>)", inline=False)
        embed.set_footer(text="Review the details, then start or cancel the giveaway.")

        view = GiveawayPreviewView(
            self.bot, self.author_id, self.channel, prize, winners, seconds
        )
        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True
        )


class GiveawayCreatorView(discord.ui.View):
    def __init__(self, bot, channel):
        super().__init__(timeout=300)
        self.bot = bot
        self.channel = channel

    @discord.ui.button(
        label="Create Giveaway",
        emoji="🎁",
        style=discord.ButtonStyle.primary
    )
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message(
                "You need Manage Server permission to create giveaways.",
                ephemeral=True
            )
        await interaction.response.send_modal(
            GiveawayModal(self.bot, self.channel, interaction.user.id)
        )


class Giveaways(commands.Cog):
    """Interactive giveaway creation and automatic winner selection."""

    def __init__(self, bot):
        self.bot = bot
        self.entry_view = GiveawayEntryView(bot)
        self.finish_due.start()

    async def cog_load(self):
        await self.bot.db.execute(
            "CREATE TABLE IF NOT EXISTS onyx_giveaways ("
            "guild_id BIGINT NOT NULL, channel_id BIGINT NOT NULL, "
            "message_id BIGINT PRIMARY KEY, host_id BIGINT NOT NULL, "
            "prize TEXT NOT NULL, winner_count INTEGER NOT NULL, "
            "ends_at BIGINT NOT NULL, ended INTEGER NOT NULL DEFAULT 0)"
        )
        await self.bot.db.execute(
            "CREATE TABLE IF NOT EXISTS onyx_giveaway_entries ("
            "message_id BIGINT NOT NULL, guild_id BIGINT NOT NULL, "
            "user_id BIGINT NOT NULL, PRIMARY KEY(message_id,user_id))"
        )
        await self.bot.db.execute(
            "CREATE TABLE IF NOT EXISTS onyx_giveaway_winners ("
            "message_id BIGINT NOT NULL, user_id BIGINT NOT NULL, "
            "selected_at BIGINT NOT NULL, PRIMARY KEY(message_id,user_id))"
        )
        self.bot.giveaway_entry_view = self.entry_view
        self.bot.add_view(self.entry_view)

    def cog_unload(self):
        self.finish_due.cancel()
        self.bot.remove_view(self.entry_view)

    @commands.command(
        name="giveaway",
        aliases=["gcreate"],
        help="Open the interactive ONYX giveaway creator."
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def giveaway(self, ctx):
        embed = discord.Embed(
            title="ONYX • Giveaway Creator",
            description=(
                "Ready to give something away?\n\n"
                "Press **Create Giveaway** to configure your prize, "
                "duration, and number of winners. ONYX will show you a "
                "preview before anything goes live."
            ),
            color=COLOR
        )
        embed.add_field(
            name="Included",
            value="🎁 Interactive entry button\n⏰ Automatic ending\n🏆 Random winner selection",
            inline=False
        )
        embed.set_footer(text="ONYX Community • Giveaways")
        await ctx.send(
            embed=embed,
            view=GiveawayCreatorView(self.bot, ctx.channel),
            allowed_mentions=discord.AllowedMentions.none()
        )

    @commands.command(
        name="reroll",
        help="Pick a new winner for an ended giveaway. Usage: ,reroll <message_id>"
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def reroll(self, ctx, message_id: int = None):
        if message_id is None and ctx.message.reference:
            message_id = ctx.message.reference.message_id
        if message_id is None:
            return await ctx.reply(
                "Give me the giveaway message ID: `,reroll <message_id>` "
                "or reply to the giveaway message with `,reroll`.",
                mention_author=False
            )

        row = await self.bot.db.fetchone(
            "SELECT guild_id, channel_id, message_id, prize, ended "
            "FROM onyx_giveaways WHERE message_id=? AND guild_id=?",
            (message_id, ctx.guild.id)
        )
        if not row:
            return await ctx.reply(
                "I couldn't find that giveaway in this server.",
                mention_author=False
            )
        if not row["ended"]:
            return await ctx.reply(
                "That giveaway is still running. You can reroll after it ends.",
                mention_author=False
            )

        entries = await self.bot.db.fetchall(
            "SELECT user_id FROM onyx_giveaway_entries WHERE message_id=?",
            (message_id,)
        )
        if not entries:
            return await ctx.reply(
                "That giveaway had no entries, so there's nobody to reroll.",
                mention_author=False
            )

        previous = await self.bot.db.fetchall(
            "SELECT user_id FROM onyx_giveaway_winners WHERE message_id=?",
            (message_id,)
        )
        previous_ids = {item["user_id"] for item in previous}
        eligible = [item["user_id"] for item in entries if item["user_id"] not in previous_ids]
        if not eligible:
            return await ctx.reply(
                "Everyone who entered has already been selected. There are no new entrants to reroll.",
                mention_author=False
            )

        winner_id = random.choice(eligible)
        await self.bot.db.execute(
            "INSERT INTO onyx_giveaway_winners (message_id, user_id, selected_at) "
            "VALUES (?,?,?) ON CONFLICT(message_id,user_id) DO NOTHING",
            (message_id, winner_id, int(time.time()))
        )

        channel = ctx.guild.get_channel(row["channel_id"])
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(row["channel_id"])
            except discord.HTTPException:
                channel = None
        if channel is None:
            return await ctx.reply(
                "I selected a new winner, but I couldn't access the original giveaway channel.",
                mention_author=False
            )

        try:
            giveaway_message = await channel.fetch_message(message_id)
            embed = giveaway_message.embeds[0].copy() if giveaway_message.embeds else discord.Embed(
                title="🎉 ONYX GIVEAWAY",
                description=f"**Prize**\\n{row['prize']}",
                color=ACCENT
            )
            embed.add_field(
                name="🔄 Reroll winner",
                value=f"<@{winner_id}>",
                inline=False
            )
            await giveaway_message.edit(embed=embed)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            # The winner is still recorded; announce them in the command channel.
            pass

        await channel.send(
            f"🔄 **Giveaway reroll!** Congratulations <@{winner_id}>! "
            f"You won **{row['prize']}**!",
            allowed_mentions=discord.AllowedMentions(users=True)
        )
        await ctx.reply(
            f"Picked a new winner: <@{winner_id}>",
            mention_author=False,
            allowed_mentions=discord.AllowedMentions(users=True)
        )

    @tasks.loop(seconds=15)
    async def finish_due(self):
        now = int(time.time())
        rows = await self.bot.db.fetchall(
            "SELECT guild_id, channel_id, message_id, host_id, prize, winner_count, ends_at "
            "FROM onyx_giveaways WHERE ended=0 AND ends_at<=?",
            (now,)
        )
        for row in rows:
            # Mark first so reconnects or concurrent loop ticks cannot award twice.
            await self.bot.db.execute(
                "UPDATE onyx_giveaways SET ended=1 WHERE message_id=? AND ended=0",
                (row["message_id"],)
            )
            entries = await self.bot.db.fetchall(
                "SELECT user_id FROM onyx_giveaway_entries WHERE message_id=?",
                (row["message_id"],)
            )
            entrants = [entry["user_id"] for entry in entries]
            winners = random.sample(entrants, min(row["winner_count"], len(entrants))) if entrants else []
            for winner_id in winners:
                await self.bot.db.execute(
                    "INSERT INTO onyx_giveaway_winners (message_id, user_id, selected_at) "
                    "VALUES (?,?,?) ON CONFLICT(message_id,user_id) DO NOTHING",
                    (row["message_id"], winner_id, now)
                )

            guild = self.bot.get_guild(row["guild_id"])
            channel = guild.get_channel(row["channel_id"]) if guild else None
            if channel is None:
                continue

            count = len(entrants)
            embed = giveaway_embed(
                row["prize"], row["winner_count"], row["host_id"],
                row["ends_at"], count, ended=True, winners=winners
            )
            try:
                message = await channel.fetch_message(row["message_id"])
                await message.edit(embed=embed, view=None)
                if winners:
                    mentions = ", ".join(f"<@{user_id}>" for user_id in winners)
                    await channel.send(
                        f"🎉 Congratulations {mentions}! You won **{row['prize']}**!",
                        allowed_mentions=discord.AllowedMentions(users=True)
                    )
                else:
                    await channel.send(
                        f"🎁 The giveaway for **{row['prize']}** ended with no entries."
                    )
            except discord.HTTPException:
                # The giveaway record remains ended even if its message was deleted.
                continue

    @finish_due.before_loop
    async def before_finish_due(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Giveaways(bot))
