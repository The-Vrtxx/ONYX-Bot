
"""Shared utilities for the ONYX global economy and arcade games."""

import uuid
from datetime import datetime, timezone

import discord

from currency_system import (
    MAX_CREDITS,
    get_credit_balance,
    grant_credits,
    spend_credits,
)


COLOR = discord.Color.from_rgb(25, 190, 190)


def money(amount):
    """Format an amount of Credits."""
    return f"{int(amount):,} Credits"


def make_embed(title, description, color=COLOR):
    """Create a consistent ONYX economy embed."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="ONYX • GLOBAL ECONOMY")
    return embed


async def get_balance(bot, user_id):
    """Get the current global Credits balance."""
    async with bot.db.pool.acquire() as conn:
        wallet = await get_credit_balance(conn, user_id)

    return int(wallet["credits"])


async def balance_line(bot, user_id):
    """Return a formatted current balance line."""
    balance = await get_balance(bot, user_id)
    return f"**Current Balance:** {money(balance)}"


async def place_wager(bot, user_id, amount, source):
    """Validate and deduct a game wager."""
    amount = int(amount)

    if amount <= 0 or amount > MAX_CREDITS:
        return {
            "ok": False,
            "error": "Enter a valid positive wager.",
        }

    async with bot.db.pool.acquire() as conn:
        async with conn.transaction():
            settings = await conn.fetchrow("""
                SELECT min_bet, max_bet, enabled
                FROM onyx_economy_settings
                WHERE id=1
            """)

            if not settings or not settings["enabled"]:
                return {
                    "ok": False,
                    "error": "The ONYX economy is disabled.",
                }

            if (
                amount < settings["min_bet"]
                or amount > settings["max_bet"]
            ):
                return {
                    "ok": False,
                    "error": (
                        f"Bets must be between "
                        f"{settings['min_bet']:,} and "
                        f"{settings['max_bet']:,} Credits."
                    ),
                }

            return await spend_credits(
                conn,
                user_id,
                amount,
                source,
                "ONYX Arcade wager",
            )


async def pay_out(
    bot,
    user_id,
    amount,
    source,
    reference=None,
):
    """Pay winnings using an idempotent transaction reference."""
    amount = int(amount)

    if amount <= 0:
        return {
            "ok": False,
            "error": "Payout must be positive.",
        }

    if amount > MAX_CREDITS:
        return {
            "ok": False,
            "error": "Payout exceeds the maximum Credits limit.",
        }

    reference = str(reference or uuid.uuid4().hex)

    async with bot.db.pool.acquire() as conn:
        async with conn.transaction():
            return await grant_credits(
                conn,
                user_id,
                amount,
                source=source,
                description="ONYX Arcade payout",
                reference_id=reference,
            )


class PlayerView(discord.ui.View):
    """Base view that restricts game controls to one player."""

    def __init__(
        self,
        bot,
        user_id,
        bet,
        game,
        reference,
        timeout=90,
    ):
        super().__init__(timeout=timeout)

        self.bot = bot
        self.user_id = int(user_id)
        self.bet = int(bet)
        self.game = str(game)
        self.reference = str(reference)
        self.finished = False
        self.settling = False

    async def interaction_check(self, interaction):
        """Prevent other members from using another player's game."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This game belongs to another player.",
                ephemeral=True,
            )
            return False

        if self.finished or self.settling:
            await interaction.response.send_message(
                "This game has already ended or is being settled.",
                ephemeral=True,
            )
            return False

        return True

    async def current_balance_text(self):
        return await balance_line(
            self.bot,
            self.user_id,
        )

    def disable_controls(self):
        """Disable every button in this game."""
        for child in self.children:
            child.disabled = True

    async def refund(self):
        """Return the original wager if a game expires unfinished."""
        if self.finished or self.settling:
            return

        self.settling = True

        try:
            result = await pay_out(
                self.bot,
                self.user_id,
                self.bet,
                f"{self.game}_refund",
                f"{self.reference}:refund",
            )

            if result and result.get("ok"):
                self.finished = True
                self.disable_controls()

        finally:
            self.settling = False

    async def on_timeout(self):
        """Refund an unfinished game when its controls expire."""
        try:
            await self.refund()
        except Exception:
            pass
