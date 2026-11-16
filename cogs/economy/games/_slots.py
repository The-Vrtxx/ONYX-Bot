
"""ONYX animated Slots game."""

import asyncio
import random

import discord

from cogs.economy._common import (
    PlayerView,
    make_embed,
    money,
    pay_out,
)
from cogs.economy.games._streaks import cancel_streak_round


SLOT_SYMBOLS = ("🍒", "🍋", "🍇", "🔔", "💎", "7️⃣")


class SlotsView(PlayerView):
    """Animated ONYX slot machine."""

    SPIN_FRAMES = 5
    FRAME_DELAY = 0.45
    STOP_DELAY = 0.55

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
            "slots",
            reference,
            timeout=90,
            streak_id=streak_id,
        )

        self.spinning = False
        self.result_handler = result_handler
        self.settlement_started = False

    def slot_embed(self, reels, status=""):
        display = "　|　".join(
            f"**{symbol}**" for symbol in reels
        )

        embed = make_embed(
            "🎰 ONYX ARCADE SLOTS",
            (
                f"**Wager:** {money(self.bet)}\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"# {display}\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{status}"
            ),
        )

        embed.set_footer(text="ONYX Arcade • Slot Machine")
        return embed

    @staticmethod
    def calculate_multiplier(reels):
        """Calculate the original ONYX slot payout multiplier."""

        if reels == ["7️⃣", "7️⃣", "7️⃣"]:
            return 10

        if len(set(reels)) == 1:
            return 5

        if len(set(reels)) == 2:
            return 2

        return 0

    async def finish_result(self, interaction, reels, multiplier):
        """Settle a completed spin exactly once."""

        if multiplier:
            winnings = self.bet * multiplier

            result = (
                f"🎉 **YOU WON!**\n\n"
                f"Multiplier: **{multiplier}x**\n"
                f"Payout: **{money(winnings)}**"
            )

            if self.result_handler:
                self.settlement_started = True
                await self.result_handler(
                    interaction,
                    self,
                    "win",
                    winnings,
                    result,
                )
                return

            self.settlement_started = True

            paid = await pay_out(
                self.bot,
                self.user_id,
                winnings,
                "slots_payout",
                self.reference,
            )

            if not paid or not paid.get("ok"):
                result += (
                    "\n\n⚠️ Your payout needs administrator review."
                )

            color = discord.Color.gold()

        else:
            result = (
                f"❌ **No win this time.**\n\n"
                f"You lost **{money(self.bet)}**."
            )

            if self.result_handler:
                self.settlement_started = True
                await self.result_handler(
                    interaction,
                    self,
                    "loss",
                    0,
                    result,
                )
                return

            self.settlement_started = True
            color = discord.Color.red()

        final_embed = self.slot_embed(reels, result)
        final_embed.color = color

        await interaction.edit_original_response(
            embed=final_embed,
            view=self,
        )

    async def recover_failed_spin(self):
        """Refund or release a spin that failed before settlement began."""

        if self.streak_id:
            await cancel_streak_round(
                self.bot,
                self.user_id,
                self.streak_id,
            )
            return

        await pay_out(
            self.bot,
            self.user_id,
            self.bet,
            "slots_refund",
            f"{self.reference}:refund",
        )

    @discord.ui.button(
        label="Spin",
        emoji="🎰",
        style=discord.ButtonStyle.success,
    )
    async def spin(self, interaction, button):
        if self.spinning or self.finished or self.settling:
            return await interaction.response.send_message(
                "This slot machine is already spinning or finished.",
                ephemeral=True,
            )

        self.spinning = True
        self.settling = True
        self.finished = True
        button.disabled = True

        final_reels = [
            random.choice(SLOT_SYMBOLS)
            for _ in range(3)
        ]

        multiplier = self.calculate_multiplier(final_reels)

        try:
            await interaction.response.edit_message(
                embed=self.slot_embed(
                    ["❔", "❔", "❔"],
                    "🎰 **Spinning...**",
                ),
                view=self,
            )

            for _ in range(self.SPIN_FRAMES):
                animated_reels = [
                    random.choice(SLOT_SYMBOLS)
                    for _ in range(3)
                ]

                await interaction.edit_original_response(
                    embed=self.slot_embed(
                        animated_reels,
                        "🎰 **Reels spinning...**",
                    ),
                    view=self,
                )

                await asyncio.sleep(self.FRAME_DELAY)

            displayed_reels = [
                random.choice(SLOT_SYMBOLS)
                for _ in range(3)
            ]

            for stopped in range(1, 4):
                displayed_reels[stopped - 1] = final_reels[stopped - 1]

                status = (
                    f"🎰 **Reel {stopped} stopped!**"
                    if stopped < 3
                    else "🎰 **All reels stopped!**"
                )

                await interaction.edit_original_response(
                    embed=self.slot_embed(
                        displayed_reels,
                        status,
                    ),
                    view=self,
                )

                await asyncio.sleep(self.STOP_DELAY)

            await self.finish_result(
                interaction,
                final_reels,
                multiplier,
            )

        except Exception:
            # Only refund if the result handler has not started.
            # Once settlement starts, an automatic refund could duplicate
            # a payout that was already committed to the database.
            if not self.settlement_started:
                try:
                    await self.recover_failed_spin()
                except Exception:
                    pass

            raise

        finally:
            self.settling = False
