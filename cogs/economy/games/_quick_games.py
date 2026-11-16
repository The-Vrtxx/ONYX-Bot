
"""ONYX Dice and Betflip game views."""

import random

import discord

from cogs.economy._common import (
    PlayerView,
    make_embed,
    money,
    pay_out,
)


class QuickGameView(PlayerView):
    """Shared button-based view for Dice and Betflip."""

    def __init__(
        self,
        bot,
        user_id,
        bet,
        game,
        reference,
        result_handler=None,
        streak_id=None,
    ):
        game = str(game).casefold()

        if game not in {"dice", "betflip"}:
            raise ValueError(
                "QuickGameView only supports Dice and Betflip."
            )

        super().__init__(
            bot,
            user_id,
            bet,
            game,
            reference,
            timeout=90,
            streak_id=streak_id,
        )

        self.result_handler = result_handler

        # Only show the buttons belonging to this game.
        for child in self.children:
            if child.custom_id == "onyx_quick_heads":
                child.disabled = game != "betflip"

            elif child.custom_id == "onyx_quick_tails":
                child.disabled = game != "betflip"

            elif child.custom_id == "onyx_quick_high":
                child.disabled = game != "dice"

            elif child.custom_id == "onyx_quick_low":
                child.disabled = game != "dice"

    async def settle(self, interaction, choice):
        """Resolve the game and hand the result to the economy manager."""

        if self.finished or self.settling:
            return await interaction.response.send_message(
                "This game has already ended.",
                ephemeral=True,
            )

        self.settling = True

        try:
            if self.game == "betflip":
                result = random.choice(("heads", "tails"))
                won = choice == result
                result_text = result.title()
                title = "🪙 ONYX BETFLIP"

            else:
                result = random.randint(1, 6)
                won = (
                    result >= 4
                    if choice == "high"
                    else result <= 3
                )
                result_text = str(result)
                title = "🎲 ONYX DICE"

            self.finished = True
            self.disable_controls()

            if won:
                payout = self.bet * 2

                message = (
                    f"🎉 **You won {money(payout)}!**\n"
                    f"Result: **{result_text}**"
                )

                if self.result_handler:
                    await self.result_handler(
                        interaction,
                        self,
                        "win",
                        payout,
                        message,
                    )
                    return

                paid = await pay_out(
                    self.bot,
                    self.user_id,
                    payout,
                    f"{self.game}_payout",
                    self.reference,
                )

                if not paid or not paid.get("ok"):
                    message += (
                        "\n\n⚠️ Your payout needs administrator review."
                    )

            else:
                message = (
                    f"❌ You lost **{money(self.bet)}**.\n"
                    f"Result: **{result_text}**"
                )

                if self.result_handler:
                    await self.result_handler(
                        interaction,
                        self,
                        "loss",
                        0,
                        message,
                    )
                    return

            await interaction.response.edit_message(
                embed=make_embed(
                    title,
                    message,
                ),
                view=self,
            )

        finally:
            self.settling = False

    @discord.ui.button(
        label="Heads",
        custom_id="onyx_quick_heads",
        style=discord.ButtonStyle.primary,
    )
    async def heads(self, interaction, button):
        if self.game != "betflip":
            return await interaction.response.send_message(
                "That choice isn't available in this game.",
                ephemeral=True,
            )

        await self.settle(interaction, "heads")

    @discord.ui.button(
        label="Tails",
        custom_id="onyx_quick_tails",
        style=discord.ButtonStyle.primary,
    )
    async def tails(self, interaction, button):
        if self.game != "betflip":
            return await interaction.response.send_message(
                "That choice isn't available in this game.",
                ephemeral=True,
            )

        await self.settle(interaction, "tails")

    @discord.ui.button(
        label="High (4–6)",
        custom_id="onyx_quick_high",
        style=discord.ButtonStyle.success,
        row=1,
    )
    async def high(self, interaction, button):
        if self.game != "dice":
            return await interaction.response.send_message(
                "That choice isn't available in this game.",
                ephemeral=True,
            )

        await self.settle(interaction, "high")

    @discord.ui.button(
        label="Low (1–3)",
        custom_id="onyx_quick_low",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def low(self, interaction, button):
        if self.game != "dice":
            return await interaction.response.send_message(
                "That choice isn't available in this game.",
                ephemeral=True,
            )

        await self.settle(interaction, "low")
