
"""ONYX arcade streak decision and game-selection views."""

import discord

from currency_system import MAX_CREDITS
from cogs.economy._common import make_embed, money
from cogs.economy.games._streaks import cash_out_streak


class StreakDecisionView(discord.ui.View):
    """Let a player cash out or continue an arcade streak."""

    def __init__(
        self,
        bot,
        user_id,
        streak,
        launch_game,
        timeout=180,
    ):
        super().__init__(timeout=timeout)

        self.bot = bot
        self.user_id = int(user_id)
        self.streak = dict(streak)
        self.launch_game = launch_game
        self.finished = False
        self.processing = False

        pot = int(self.streak["pot"])
        multiplier = int(self.streak["next_multiplier"])

        # Prevent a continuation that could exceed the Credits cap.
        if pot * multiplier > MAX_CREDITS:
            self.continue_streak.disabled = True

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This streak belongs to another player.",
                ephemeral=True,
            )
            return False

        if self.finished or self.processing:
            await interaction.response.send_message(
                "This streak decision has already been handled.",
                ephemeral=True,
            )
            return False

        return True

    def decision_embed(self):
        pot = int(self.streak["pot"])
        wins = int(self.streak["streak_wins"])
        multiplier = int(self.streak["next_multiplier"])

        can_continue = pot * multiplier <= MAX_CREDITS

        description = (
            f"**Current Streak:** {wins} win(s)\n"
            f"**Streak Pot:** {money(pot)}\n"
            f"**Next Win Multiplier:** {multiplier}x\n\n"
            "Your winnings are waiting.\n"
            "Cash out to keep them, or risk the entire pot "
            "on another game."
        )

        if not can_continue:
            description += (
                "\n\n⚠️ **Maximum payout reached.** "
                "The next possible win would exceed the "
                "Credits limit. Cash out to collect your pot."
            )

        return make_embed(
            "🔥 ONYX STREAK",
            description,
        )

    @discord.ui.button(
        label="Cash Out",
        emoji="💰",
        style=discord.ButtonStyle.success,
    )
    async def cash_out(self, interaction, button):
        if self.processing or self.finished:
            return

        self.processing = True

        try:
            result = await cash_out_streak(
                self.bot,
                self.user_id,
            )

            if not result.get("ok"):
                self.processing = False

                return await interaction.response.send_message(
                    result.get(
                        "error",
                        "Unable to cash out this streak.",
                    ),
                    ephemeral=True,
                )

            self.finished = True

            for child in self.children:
                child.disabled = True

            await interaction.response.edit_message(
                embed=make_embed(
                    "💰 STREAK CASHED OUT",
                    (
                        f"🎉 You secured **{money(result['amount'])}**!\n\n"
                        f"**Streak Wins:** {result['streak_wins']}\n"
                        f"**New Balance:** {money(result['credits'])}\n\n"
                        "Your ONYX streak is complete."
                    ),
                ),
                view=self,
            )

        except Exception:
            self.processing = False
            raise

    @discord.ui.button(
        label="Continue Streak",
        emoji="🔥",
        style=discord.ButtonStyle.primary,
    )
    async def continue_streak(self, interaction, button):
        if self.processing or self.finished:
            return

        pot = int(self.streak["pot"])
        multiplier = int(self.streak["next_multiplier"])

        if pot * multiplier > MAX_CREDITS:
            button.disabled = True

            return await interaction.response.send_message(
                "The next streak payout would exceed the "
                "maximum Credits limit. Please cash out.",
                ephemeral=True,
            )

        self.processing = True

        view = StreakGameSelectView(
            bot=self.bot,
            user_id=self.user_id,
            streak=self.streak,
            launch_game=self.launch_game,
        )

        await interaction.response.edit_message(
            embed=make_embed(
                "🔥 CONTINUE YOUR STREAK",
                (
                    f"**Pot at Risk:** {money(pot)}\n"
                    f"**Next Win:** {multiplier}x the pot\n\n"
                    "Choose which game you want to play."
                ),
            ),
            view=view,
        )

        self.finished = True


class StreakGameSelectView(discord.ui.View):
    """Choose which arcade game to use for the next streak round."""

    def __init__(
        self,
        bot,
        user_id,
        streak,
        launch_game,
        timeout=120,
    ):
        super().__init__(timeout=timeout)

        self.bot = bot
        self.user_id = int(user_id)
        self.streak = dict(streak)
        self.launch_game = launch_game
        self.finished = False
        self.processing = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This streak belongs to another player.",
                ephemeral=True,
            )
            return False

        if self.finished or self.processing:
            await interaction.response.send_message(
                "This game selection has already been handled.",
                ephemeral=True,
            )
            return False

        return True

    async def choose(self, interaction, game):
        if self.finished or self.processing:
            return

        self.processing = True

        try:
            await self.launch_game(
                interaction,
                game,
            )
            self.finished = True

        except Exception:
            self.processing = False

            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "I couldn't start that game. "
                    "Your streak should remain available.",
                    ephemeral=True,
                )

            raise

    @discord.ui.button(
        label="Blackjack",
        emoji="🃏",
        style=discord.ButtonStyle.primary,
    )
    async def blackjack(self, interaction, button):
        await self.choose(interaction, "blackjack")

    @discord.ui.button(
        label="Slots",
        emoji="🎰",
        style=discord.ButtonStyle.primary,
    )
    async def slots(self, interaction, button):
        await self.choose(interaction, "slots")

    @discord.ui.button(
        label="Dice",
        emoji="🎲",
        style=discord.ButtonStyle.primary,
        row=1,
    )
    async def dice(self, interaction, button):
        await self.choose(interaction, "dice")

    @discord.ui.button(
        label="Betflip",
        emoji="🪙",
        style=discord.ButtonStyle.primary,
        row=1,
    )
    async def betflip(self, interaction, button):
        await self.choose(interaction, "betflip")
