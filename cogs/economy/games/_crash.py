
"""ONYX Crash game with a live multiplier and cash-out button."""

import asyncio
import math
import random
import time

import discord

from cogs.economy._common import PlayerView, make_embed, money
from cogs.economy.games._controls import get_arcade_config


GROWTH_RATE = 0.12
UPDATE_INTERVAL = 0.9
MAX_CRASH_MULTIPLIER = 50.0
MIN_CRASH_MULTIPLIER = 1.50


class _MessageResponse:
    """Small interaction-response adapter for automatic crash settlement."""

    def is_done(self):
        return True


class _MessageInteraction:
    """Allow the arcade manager to settle a result from a background task."""

    def __init__(self, user, message):
        self.user = user
        self.message = message
        self.response = _MessageResponse()

    async def edit_original_response(self, **kwargs):
        return await self.message.edit(**kwargs)


class CrashView(PlayerView):
    """Live Crash round for one Discord player."""

    def __init__(
        self,
        bot,
        user,
        bet,
        reference,
        result_handler=None,
        streak_id=None,
    ):
        super().__init__(
            bot,
            user.id,
            bet,
            "crash",
            reference,
            timeout=180,
            streak_id=streak_id,
        )

        self.player = user
        self.result_handler = result_handler

        # The crash point is selected before the round begins.
        random_value = random.random()
        crash_point = 0.99 / max(0.000001, 1 - random_value)

        self.crash_multiplier = min(
            MAX_CRASH_MULTIPLIER,
            max(
                MIN_CRASH_MULTIPLIER,
                math.floor(crash_point * 100) / 100,
            ),
        )

        self.started_at = None
        self.current_multiplier = 1.00
        self.current_payout = 0

        self.message = None
        self.animation_task = None

        self.cashout_button = discord.ui.Button(
            label="Cash Out",
            emoji="💰",
            style=discord.ButtonStyle.success,
            row=0,
        )
        self.cashout_button.callback = self.cash_out
        self.add_item(self.cashout_button)

    def start(self, message):
        """Start the live multiplier animation after sending the game message."""

        self.message = message
        self.started_at = time.monotonic()
        self.animation_task = asyncio.create_task(
            self.run_animation()
        )

    def calculate_multiplier(self):
        """Calculate the live multiplier from elapsed time."""

        if self.started_at is None:
            return 1.00

        elapsed = time.monotonic() - self.started_at

        return round(
            math.exp(GROWTH_RATE * elapsed),
            2,
        )

    async def update_payout(self):
        """Calculate the current return, respecting the arcade payout cap."""

        calculated = int(
            self.bet * self.current_multiplier
        )

        try:
            config = await get_arcade_config(self.bot)
            maximum = max(
                0,
                int(config["maximum_payout"]),
            )
        except Exception:
            maximum = 2_000_000

        self.current_payout = min(calculated, maximum)

    def current_embed(self, result=None):
        """Build the live Crash display."""

        if self.finished:
            multiplier_text = f"**{self.current_multiplier:.2f}x**"
        else:
            multiplier_text = (
                f"# 🚀 {self.current_multiplier:.2f}x"
            )

        description = (
            f"**Wager:** {money(self.bet)}\n"
            f"**Current Multiplier:** {multiplier_text}\n"
            f"**Cash-Out Value:** {money(self.current_payout)}\n\n"
            "The multiplier keeps climbing until the round crashes.\n"
            "**Cash out before it crashes to secure your payout!**"
        )

        if result:
            description += f"\n\n{result}"

        return make_embed(
            "🚀 ONYX CRASH",
            description,
        )

    async def run_animation(self):
        """Animate the multiplier and automatically settle a crash."""

        try:
            while not self.finished and not self.settling:
                self.current_multiplier = self.calculate_multiplier()

                if self.current_multiplier >= self.crash_multiplier:
                    self.current_multiplier = self.crash_multiplier
                    await self.crash_round()
                    return

                await self.update_payout()

                if self.message:
                    try:
                        await self.message.edit(
                            embed=self.current_embed(),
                            view=self,
                        )
                    except discord.NotFound:
                        await self.refund()
                        return
                    except discord.HTTPException:
                        pass

                await asyncio.sleep(UPDATE_INTERVAL)

        except asyncio.CancelledError:
            return
        except Exception:
            # Do not leave a wager locked if the animation unexpectedly fails.
            if not self.finished:
                try:
                    await self.refund()
                except Exception:
                    pass

    async def crash_round(self):
        """Settle automatically when the multiplier reaches the crash point."""

        if self.finished or self.settling:
            return

        self.settling = True

        try:
            self.finished = True
            self.disable_controls()

            result = (
                f"💥 **CRASH!** The round ended at "
                f"**{self.crash_multiplier:.2f}x**.\n"
                f"You lost your wager of **{money(self.bet)}**."
            )

            if self.result_handler and self.message:
                interaction = _MessageInteraction(
                    self.player,
                    self.message,
                )

                await self.result_handler(
                    interaction,
                    self,
                    "loss",
                    0,
                    result,
                )
            elif self.message:
                await self.message.edit(
                    embed=self.current_embed(result),
                    view=self,
                )

        finally:
            self.settling = False

    async def cash_out(self, interaction):
        """Secure the current payout before the crash occurs."""

        if self.finished or self.settling:
            return await interaction.response.send_message(
                "This Crash round has already ended.",
                ephemeral=True,
            )

        self.settling = True

        try:
            # Recalculate at the moment the button interaction is received.
            self.current_multiplier = self.calculate_multiplier()

            if self.current_multiplier >= self.crash_multiplier:
                self.current_multiplier = self.crash_multiplier
                self.finished = True
                self.disable_controls()

                result = (
                    f"💥 **CRASH!** The round ended at "
                    f"**{self.crash_multiplier:.2f}x**.\n"
                    f"You lost **{money(self.bet)}**."
                )

                if self.result_handler:
                    await self.result_handler(
                        interaction,
                        self,
                        "loss",
                        0,
                        result,
                    )
                else:
                    await interaction.response.edit_message(
                        embed=self.current_embed(result),
                        view=self,
                    )

                return

            await self.update_payout()

            payout = int(self.current_payout)
            self.finished = True
            self.disable_controls()

            if self.animation_task:
                self.animation_task.cancel()

            result = (
                f"💰 **CASHED OUT!**\n"
                f"Multiplier: **{self.current_multiplier:.2f}x**\n"
                f"Payout: **{money(payout)}**"
            )

            if self.result_handler:
                await self.result_handler(
                    interaction,
                    self,
                    "win",
                    payout,
                    result,
                )
            else:
                await interaction.response.edit_message(
                    embed=self.current_embed(result),
                    view=self,
                )

        finally:
            self.settling = False

    async def on_timeout(self):
        """Stop the animation and use the shared refund behavior."""

        if self.animation_task:
            self.animation_task.cancel()

        await super().on_timeout()


