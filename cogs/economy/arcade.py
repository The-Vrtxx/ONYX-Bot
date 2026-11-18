
"""ONYX Arcade hub, player records, and game history."""

import discord
from discord.ext import commands

from cogs.economy._common import make_embed, money
from cogs.economy.games._stats import (
    get_player_arcade_stats,
    get_recent_arcade_rounds,
    get_arcade_leaderboard,
)


class ArcadeCommands(commands.Cog):
    """Arcade hub and player records."""

    def __init__(self, bot):
        self.bot = bot

    async def available(self, ctx):
        if self.bot.db.backend != "postgres":
            await ctx.send(
                "ONYX Arcade records require the PostgreSQL database."
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
                "🪙 `,betflip <amount>` — Heads or Tails\n"
                "💣 `,mines <amount> [mines]` — Mines\n"
                "🎡 `,roulette <amount>` — Roulette\n"
                "🚀 `,crash <amount>` — Live Crash\n\n"
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
        help="View your ONYX Arcade statistics.",
    )
    async def stats(self, ctx, member: discord.Member = None):
        if not await self.available(ctx):
            return

        member = member or ctx.author

        stats = await get_player_arcade_stats(
            self.bot.db.pool,
            member.id,
        )

        if not stats or not stats["games_played"]:
            return await ctx.send(
                f"{member.display_name} has no recorded arcade games yet."
            )

        embed = make_embed(
            f"📊 {member.display_name}'s Arcade Stats",
            (
                f"**Games Played:** {stats['games_played']:,}\n"
                f"**Wins:** {stats['wins']:,}\n"
                f"**Losses:** {stats['losses']:,}\n"
                f"**Pushes:** {stats['pushes']:,}\n"
                f"**Total Wagered:** {money(stats['total_wagered'])}\n"
                f"**Total Returned:** {money(stats['total_returned'])}\n"
                f"**Biggest Return:** {money(stats['biggest_return'])}"
            ),
        )

        await ctx.send(embed=embed)

    @arcade.command(
        name="history",
        help="View your recent ONYX Arcade games.",
    )
    async def history(self, ctx, member: discord.Member = None):
        if not await self.available(ctx):
            return

        member = member or ctx.author

        rows = await get_recent_arcade_rounds(
            self.bot.db.pool,
            member.id,
            limit=10,
        )

        if not rows:
            return await ctx.send(
                f"{member.display_name} has no arcade history yet."
            )

        lines = []

        for row in rows:
            game = str(row["game"]).title()
            outcome = str(row["outcome"]).title()
            wager = money(row["wager"])
            payout = money(row["payout"])

            lines.append(
                f"**{game}** — {outcome}\n"
                f"Wager: {wager} • Returned: {payout}"
            )

        await ctx.send(
            embed=make_embed(
                f"📜 {member.display_name}'s Recent Games",
                "\n\n".join(lines),
            )
        )

    @arcade.command(
        name="leaderboard",
        aliases=["top", "lb"],
        help="View the ONYX Arcade leaderboard.",
    )
    async def leaderboard(self, ctx):
        if not await self.available(ctx):
            return

        rows = await get_arcade_leaderboard(
            self.bot.db.pool,
            limit=10,
        )

        if not rows:
            return await ctx.send(
                "No arcade records have been recorded yet."
            )

        lines = []

        for index, row in enumerate(rows, 1):
            user = self.bot.get_user(int(row["user_id"]))

            name = (
                discord.utils.escape_markdown(user.display_name)
                if user
                else f"User {row['user_id']}"
            )

            lines.append(
                f"**{index}.** {name} — "
                f"{row['games_played']:,} games "
                f"({row['wins']:,} wins)"
            )

        await ctx.send(
            embed=make_embed(
                "🏆 ONYX Arcade Leaderboard",
                "\n".join(lines),
            )
        )


async def setup(bot):
    await bot.add_cog(ArcadeCommands(bot))
