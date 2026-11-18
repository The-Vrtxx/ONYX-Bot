"""ONYX European Roulette game view."""

import random

import discord

from cogs.economy._common import PlayerView, make_embed, money
from cogs.economy.games._controls import get_arcade_config


RED_NUMBERS = {
    1, 3, 5, 7, 9, 12, 14, 16, 18,
    19, 21, 23, 25, 27, 30, 32, 34, 36,
}

BET_OPTIONS = {
    "red": ("Red", 2),
    "black": ("Black", 2),
    "odd": ("Odd", 2),
    "even": ("Even", 2),
    "low": ("1–18", 2),
    "high": ("19–36", 2),
    "dozen1": ("1st Dozen", 3),
    "dozen2": ("2nd Dozen", 3),
    "dozen3": ("3rd Dozen", 3),
}


def number_color(number):
    if number == 0:
        return "🟢 Green"

    return "🔴 Red" if number in RED_NUMBERS else "⚫ Black"


def bet_wins(bet_type, number):
    if number == 0:
        return False

    if bet_type == "red":
        return number in RED_NUMBERS

    if bet_type == "black":
        return number not in RED_NUMBERS

    if bet_type == "odd":
        return number % 2 == 1

    if bet_type == "even":
        return number % 2 == 0

    if bet_type == "low":
        return 1 <= number <= 18

    if bet_type == "high":
        return 19 <= number <= 36

    if bet_type == "dozen1":
        return 1 <= number <= 12

    if bet_type == "dozen2":
        return 13 <= number <= 24

    if bet_type == "dozen3":
        return 25 <= number <= 36

    return False


class RouletteView(PlayerView):
    """Button-based European Roulette for one Discord player."""

    def __init__(
        self,
        bot,
        user_id,
        bet,
        reference,
        result_handler=None,
        streak_id=None,
    ):
        super().__init__(
            bot,
            user_id,
            bet,
            "roulette",
            reference,
            timeout=90,
            streak_id=streak_id,
        )

        self.result_handler = result_handler
        self.selected_bet = None
        self.selection_buttons = {}

        options = [
            ("Red", "red", 0),
            ("Black", "black", 0),
            ("Odd", "odd", 1),
            ("Even", "even", 1),
            ("1–18", "low", 1),
            ("19–36", "high", 1),
            ("1st Dozen", "dozen1", 2),
            ("2nd Dozen", "dozen2", 2),
            ("3rd Dozen", "dozen3", 2),
        ]

        for label, bet_type, row in options:
            button = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.danger,
                row=row,
                custom_id=f"onyx_roulette_{bet_type}",
            )

            button.callback = self.make_selection_callback(bet_type)

            self.selection_buttons[bet_type] = button
            self.add_item(button)

        self.spin_button = discord.ui.Button(
            label="Spin Wheel",
            emoji="🎡",
            style=discord.ButtonStyle.success,
            row=3,
            custom_id="onyx_roulette_spin",
        )

        self.spin_button.callback = self.spin
        self.add_item(self.spin_button)

    def make_selection_callback(self, bet_type):
        async def callback(interaction):
            if self.finished or self.settling:
                return await interaction.response.send_message(
                    "This Roulette game has already ended.",
                    ephemeral=True,
                )

            self.selected_bet = bet_type

            # All unselected bets are red.
            # The selected bet is green.
            for key, button in self.selection_buttons.items():
                button.disabled = False

                if key == bet_type:
                    button.style = discord.ButtonStyle.success
                else:
                    button.style = discord.ButtonStyle.danger

            await interaction.response.edit_message(
                embed=self.current_embed(
                    f"Selected bet: **{BET_OPTIONS[bet_type][0]}**. "
                    "Press Spin Wheel when you're ready."
                ),
                view=self,
            )

        return callback

    def current_embed(self, message=None):
        selected = (
            BET_OPTIONS[self.selected_bet][0]
            if self.selected_bet
            else "None"
        )

        description = (
            f"**Wager:** {money(self.bet)}\n"
            f"**Selected bet:** {selected}\n\n"
            "**Choose your bet:**\n"
            "🔴 Red / ⚫ Black — 2× total return\n"
            "Odd / Even — 2× total return\n"
            "1–18 / 19–36 — 2× total return\n"
            "Each Dozen — 3× total return\n\n"
            "🟢 Zero wins against every outside bet.\n\n"
            "🔴 Unselected buttons\n"
            "🟢 Selected button"
        )

        if message:
            description += f"\n\n{message}"

        return make_embed("🎡 ONYX ROULETTE", description)

    async def spin(self, interaction):
        if self.finished or self.settling:
            return await interaction.response.send_message(
                "This Roulette game has already ended.",
                ephemeral=True,
            )

        if not self.selected_bet:
            return await interaction.response.send_message(
                "Choose a bet before spinning the wheel.",
                ephemeral=True,
            )

        self.settling = True

        try:
            number = random.randint(0, 36)
            won = bet_wins(self.selected_bet, number)

            label, multiplier = BET_OPTIONS[self.selected_bet]

            payout = 0

            if won:
                config = await get_arcade_config(self.bot)

                maximum_payout = max(
                    0,
                    int(config["maximum_payout"]),
                )

                payout = min(
                    self.bet * multiplier,
                    maximum_payout,
                )

            self.finished = True
            self.disable_controls()

            if won:
                result_text = (
                    f"🎉 **You won!**\n"
                    f"The wheel landed on **{number}** "
                    f"({number_color(number)}).\n"
                    f"Your bet: **{label}**\n"
                    f"Multiplier: **{multiplier}x**\n"
                    f"**Total return: {money(payout)}**"
                )

                if payout < self.bet * multiplier:
                    result_text += (
                        "\n\n⚠️ The configured maximum payout "
                        "limited this return."
                    )

                if self.result_handler:
                    await self.result_handler(
                        interaction,
                        self,
                        "win",
                        payout,
                        result_text,
                    )
                    return

            else:
                result_text = (
                    f"❌ **You lost {money(self.bet)}.**\n"
                    f"The wheel landed on **{number}** "
                    f"({number_color(number)}).\n"
                    f"Your bet: **{label}**"
                )

                if self.result_handler:
                    await self.result_handler(
                        interaction,
                        self,
                        "loss",
                        0,
                        result_text,
                    )
                    return

            await interaction.response.edit_message(
                embed=make_embed(
                    "🎡 ONYX ROULETTE",
                    result_text,
                ),
                view=self,
            )

        finally:
            self.settling = False
