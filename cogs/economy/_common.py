
"""Shared utilities for the ONYX global economy and arcade games."""

import uuid
from datetime import datetime, timezone

import discord

from currency_system import (
    MAX_CREDITS,
    get_credit_balance,
    grant_credits,
    spend_credits,
    update_discord_user_profile,
)

from cogs.economy.games._streaks import cancel_streak_round
from cogs.economy.games._controls import (
    get_arcade_config,
    game_is_enabled,
    validate_wager,
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
    """Validate and deduct a normal game wager."""

    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "error": "Enter a valid wager amount.",
        }

    if amount <= 0 or amount > MAX_CREDITS:
        return {
            "ok": False,
            "error": "Enter a valid positive wager.",
        }

    game = str(source).removesuffix("_wager").casefold()

    if game not in {
        "blackjack",
        "slots",
        "dice",
        "betflip",
        "mines",
        "roulette",
    }:
        return {
            "ok": False,
            "error": "This arcade game is not recognized.",
        }

    if not await game_is_enabled(bot, game):
        return {
            "ok": False,
            "error": f"ONYX {game.title()} is currently disabled.",
        }

    validation = await validate_wager(bot, amount)

    if not validation.get("ok"):
        return validation

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

            minimum = max(
                int(settings["min_bet"]),
                int(validation["config"]["minimum_wager"]),
            )

            maximum = min(
                int(settings["max_bet"]),
                int(validation["config"]["maximum_wager"]),
            )

            if amount < minimum or amount > maximum:
                return {
                    "ok": False,
                    "error": (
                        f"Bets must be between {minimum:,} and "
                        f"{maximum:,} Credits."
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
    display_name=None,
    username=None,
):
    """Pay winnings and record the member's latest known Discord identity."""

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

    source_name = str(source).casefold()
    is_return = (
        source_name.endswith("_refund")
        or source_name.endswith("_push")
    )

    if not is_return:
        config = await get_arcade_config(bot)
        maximum_payout = int(config["maximum_payout"])

        if amount > maximum_payout:
            return {
                "ok": False,
                "error": (
                    "This payout exceeds the current ONYX Arcade "
                    "maximum payout limit."
                ),
            }

    reference = str(reference or uuid.uuid4().hex)

    async with bot.db.pool.acquire() as conn:
        async with conn.transaction():
            try:
                await update_discord_user_profile(
                    conn,
                    int(user_id),
                    display_name=display_name,
                    username=username,
                )

                return await grant_credits(
                    conn,
                    user_id,
                    amount,
                    source=source,
                    description="ONYX Arcade payout",
                    reference_id=reference,
                )
            except ValueError as error:
                return {
                    "ok": False,
                    "error": str(error),
                }


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
        streak_id=None,
    ):
        super().__init__(timeout=timeout)

        self.bot = bot
        self.user_id = int(user_id)
        self.bet = int(bet)
        self.game = str(game)
        self.reference = str(reference)
        self.streak_id = (
            str(streak_id)
            if streak_id is not None
            else None
        )

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
        """Refund a normal wager or release an unfinished streak round."""

        if self.finished or self.settling:
            return

        self.settling = True

        try:
            if self.streak_id:
                await cancel_streak_round(
                    self.bot,
                    self.user_id,
                    self.streak_id,
                )

                self.finished = True
                self.disable_controls()
                return

            result = await pay_out(
                self.bot,
                self.user_id,
                self.bet,
                f"{self.game}_refund",
                f"{self.reference}:refund",
                display_name=getattr(
                    self,
                    "display_name",
                    None,
                ),
                username=getattr(
                    self,
                    "username",
                    None,
                ),
            )

            if result and result.get("ok"):
                self.finished = True
                self.disable_controls()

        finally:
            self.settling = False

    async def on_timeout(self):
        """Refund or release an unfinished game when the controls expire."""

        try:
            await self.refund()
        except Exception:
            pass
