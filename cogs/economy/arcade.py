
"""ONYX Arcade hub, player statistics, history, and leaderboard."""

import discord
from discord.ext import commands

from cogs.economy._common import make_embed, money
from cogs.economy.games._stats import (
    get_player_arcade_stats,
    get_recent_arcade_rounds,
    get_arcade_leaderboard,
)


class ArcadeCommands(commands.Cog):
    """Player-facing ONYX Arcade information commands."""

    def __init__(self, bot):
        self.bot = bot

    async def available(self, ctx):
        if self.bot.db.backend != "postgres":
            await ctx.send(
                "ONYX Arcade statistics require the PostgreSQL database."
            )
            return False

        return True

    @commands.group(
        name="arcade",
        invoke_without_command=True,
        help="View the ONYX Arcade hub and available games.",
    )
    async def arcade(self, ctx):
        if not await self.available(ctx):
            return

        embed = make_embed(
            "🎮 ONYX ARCADE",
            (
                "Welcome to the ONYX Arcade!\n\n"
                "**CASINO GAMES**\n"
                "🃏 `,blackjack <amount>` — Blackjack\n"
                "🎰 `,slots <amount>` — Slot machine\n"
                "🎲 `,dice <amount>` — High or Low\n"
                "🪙 `,betflip <amount>` — Heads or Tails\n\n"
                "**ARCADE PROGRESSION**\n"
                "🔥 `,streak` — Continue or cash out a streak\n\n"
                "**PLAYER RECORDS**\n"
                "📊 `,arcade stats` — View arcade statistics\n"
                "📜 `,arcade history` — Recent game results\n"
                "🏆 `,arcade leaderboard` — Arcade leaderboard\n\n"
                "Wagers accept a number, `half`, or `all`."
            ),
        )
        embed.set_footer(
            text="All games use your global ONYX Credits wallet."
        )
        await ctx.send(embed=embed)

    @arcade.command(
        name="stats",
        help="View your arcade statistics or another player's.",
    )
    async def arcade_stats(
        self,
        ctx,
        member: discord.User = None,
    ):
        if not await self.available(ctx):
            return

        member = member or ctx.author

        stats = await get_player_arcade_stats(
            self.bot.db.pool,
            member.id,
        )

        games = int(stats["games_played"])
        wins = int(stats["wins"])
        losses = int(stats["losses"])
        pushes = int(stats["pushes"])

        if games:
            win_rate = (wins / games) * 100
        else:
            win_rate = 0

        embed = make_embed(
            f"📊 {member.display_name}'s Arcade Stats",
            (
                f"**Games played:** {games:,}\n"
                f"**Wins:** {wins:,}\n"
                f"**Losses:** {losses:,}\n"
                f"**Pushes:** {pushes:,}\n"
                f"**Win rate:** {win_rate:.1f}%"
            ),
        )

        embed.add_field(
            name="Total wagered",
            value=money(stats["total_wagered"]),
            inline=True,
        )
        embed.add_field(
            name="Recorded returns",
            value=money(stats["total_returned"]),
            inline=True,
        )
        embed.add_field(
            name="Biggest recorded return",
            value=money(stats["biggest_return"]),
            inline=True,
        )

        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(
            text="Statistics count recorded arcade rounds."
        )

        await ctx.send(embed=embed)

    @arcade.command(
        name="history",
        aliases=["recent"],
        help="View your most recent arcade rounds.",
    )
    async def arcade_history(self, ctx):
        if not await self.available(ctx):
            return

        rows = await get_recent_arcade_rounds(
            self.bot.db.pool,
            ctx.author.id,
            limit=10,
        )

        if not rows:
            return await ctx.send(
                "📜 You don't have any recorded arcade rounds yet."
            )

        lines = []

        for row in rows:
            game = str(row["game"]).replace("_", " ").title()
            outcome = str(row["outcome"]).casefold()

            if outcome == "win":
                result = "🟢 Win"
            elif outcome == "loss":
                result = "🔴 Loss"
            elif outcome == "push":
                result = "🟡 Push"
            else:
                result = "🔵 Challenge"

            wager = money(row["wager"])
            payout = money(row["payout"])

            lines.append(
                f"**{game}** — {result}\n"
                f"Wager: {wager} • Recorded return: {payout}"
            )

        embed = make_embed(
            "📜 Your Recent Arcade History",
            "\n\n".join(lines),
        )
        embed.set_footer(
            text="Showing your 10 most recent recorded rounds."
        )

        await ctx.send(embed=embed)

    @arcade.command(
        name="leaderboard",
        aliases=["top", "lb"],
        help="View the ONYX Arcade leaderboard.",
    )
    async def arcade_leaderboard(self, ctx):
        if not await self.available(ctx):
            return

        rows = await get_arcade_leaderboard(
            self.bot.db.pool,
            limit=10,
        )

        if not rows:
            return await ctx.send(
                "🏆 The arcade leaderboard is waiting for its first players!"
            )

        lines = []

        medals = ["🥇", "🥈", "🥉"]

        for index, row in enumerate(rows):
            user_id = int(row["user_id"])
            member = self.bot.get_user(user_id)

            if member is None:
                try:
                    member = await self.bot.fetch_user(user_id)
                except discord.HTTPException:
                    member = None

            name = (
                discord.utils.escape_markdown(member.display_name)
                if member
                else f"Player {user_id}"
            )

            medal = (
                medals[index]
                if index < len(medals)
                else f"**{index + 1}.**"
            )

            lines.append(
                f"{medal} **{name}**\n"
                f"Games: {int(row['games_played']):,} "
                f"• Wins: {int(row['wins']):,} "
                f"• Recorded returns: {money(row['total_returned'])}"
            )

        embed = make_embed(
            "🏆 ONYX ARCADE LEADERBOARD",
            "\n\n".join(lines),
        )
        embed.set_footer(
            text="Ranked by recorded arcade returns, then wins."
        )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(ArcadeCommands(bot))
