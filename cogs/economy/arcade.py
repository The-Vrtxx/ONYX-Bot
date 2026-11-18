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
                "🎡 `,roulette <amount>` — Roulette\n\n"
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
