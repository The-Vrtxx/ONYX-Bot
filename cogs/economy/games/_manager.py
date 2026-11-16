
"""ONYX arcade manager.

Connects game results, Credits payouts, and cross-game streaks.
"""

import uuid

from cogs.economy._common import make_embed, money, pay_out
from cogs.economy.games._blackjack import BlackjackView
from cogs.economy.games._quick_games import QuickGameView
from cogs.economy.games._slots import SlotsView
from cogs.economy.games._streak_views import StreakDecisionView
from cogs.economy.games._streaks import (
    begin_streak_round,
    cancel_streak_round,
    create_streak,
    get_streak,
    lose_streak,
    record_streak_win,
)


GAME_NAMES = {
    "blackjack": "🃏 ONYX BLACKJACK",
    "slots": "🎰 ONYX SLOTS",
    "dice": "🎲 ONYX DICE",
    "betflip": "🪙 ONYX BETFLIP",
}


class ArcadeManager:
    """Owns the shared settlement and streak flow."""

    def __init__(self, bot):
        self.bot = bot

    async def result_handler(
        self,
        interaction,
        game_view,
        outcome,
        payout,
        result_text,
    ):
        """Settle a game result and show the correct next screen."""

        user_id = int(game_view.user_id)
        streak_id = getattr(game_view, "streak_id", None)

        # A push does not advance or destroy an existing streak.
        if outcome == "push":
            if streak_id:
                await cancel_streak_round(
                    self.bot,
                    user_id,
                    streak_id,
                )

                streak = await get_streak(
                    self.bot,
                    user_id,
                )

                if streak:
                    return await self.show_decision(
                        interaction,
                        streak,
                        game_view.game,
                        prefix=(
                            f"{result_text}\n\n"
                            "Your streak pot is unchanged."
                        ),
                    )

                return await interaction.response.edit_message(
                    embed=make_embed(
                        "ONYX ARCADE",
                        result_text,
                    ),
                    view=None,
                )

            paid = await pay_out(
                self.bot,
                user_id,
                int(payout),
                f"{game_view.game}_push",
                game_view.reference,
            )

            if not paid.get("ok"):
                result_text += (
                    "\n\n⚠️ The wager return could not be processed. "
                    "Please contact an ONYX administrator."
                )

            return await interaction.response.edit_message(
                embed=make_embed(
                    GAME_NAMES.get(game_view.game, "ONYX ARCADE"),
                    result_text,
                ),
                view=None,
            )

        # A loss ends a continued streak, but does not create a payout.
        if outcome == "loss":
            if streak_id:
                lost = await lose_streak(
                    self.bot,
                    user_id,
                    streak_id,
                )

                if not lost.get("ok"):
                    result_text += (
                        "\n\n⚠️ Streak settlement needs administrator review."
                    )
                else:
                    result_text += (
                        "\n\n🔥 **Your streak has ended.** "
                        f"You lost the {money(lost['lost_amount'])} streak pot."
                    )

            return await interaction.response.edit_message(
                embed=make_embed(
                    GAME_NAMES.get(game_view.game, "ONYX ARCADE"),
                    result_text,
                ),
                view=None,
            )

        # A win during a continued streak multiplies the existing pot.
        if streak_id:
            updated = await record_streak_win(
                self.bot,
                user_id,
                streak_id,
            )

            if not updated.get("ok"):
                result_text += (
                    "\n\n⚠️ The streak could not be advanced. "
                    "Your current pot has not been paid out. "
                    "Please use `,streak` or contact an ONYX administrator."
                )

                return await interaction.response.edit_message(
                    embed=make_embed(
                        "ONYX STREAK REVIEW",
                        result_text,
                    ),
                    view=None,
                )

            streak = updated["streak"]

            return await self.show_decision(
                interaction,
                streak,
                game_view.game,
                prefix=(
                    f"{result_text}\n\n"
                    f"🔥 Streak multiplier: "
                    f"**{updated['multiplier_used']}x**\n"
                    f"New streak pot: **{money(updated['new_pot'])}**"
                ),
            )

        # First win: place the full game payout into streak escrow.
        created = await create_streak(
            self.bot,
            user_id,
            int(payout),
            game_view.game,
            reference=game_view.reference,
        )

        if not created.get("ok"):
            # Do not leave a normal win unpaid if a streak cannot be opened.
            paid = await pay_out(
                self.bot,
                user_id,
                int(payout),
                f"{game_view.game}_payout",
                game_view.reference,
            )

            if paid.get("ok"):
                result_text += (
                    "\n\nYour winnings have been added to your wallet. "
                    "A streak could not be opened."
                )
            else:
                result_text += (
                    "\n\n⚠️ Your winnings need administrator review."
                )

            return await interaction.response.edit_message(
                embed=make_embed(
                    GAME_NAMES.get(game_view.game, "ONYX ARCADE"),
                    result_text,
                ),
                view=None,
            )

        return await self.show_decision(
            interaction,
            created["streak"],
            game_view.game,
            prefix=result_text,
        )

    async def show_decision(
        self,
        interaction,
        streak,
        previous_game,
        prefix="",
    ):
        """Show cash-out and continue options."""

        from cogs.economy.games._streak_views import StreakDecisionView

        view = StreakDecisionView(
            bot=self.bot,
            user_id=interaction.user.id,
            streak=streak,
            launch_game=self.launch_streak_game,
        )

        embed = view.decision_embed()

        if prefix:
            embed.description = (
                f"{prefix}\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{embed.description}"
            )

        await interaction.response.edit_message(
            embed=embed,
            view=view,
        )

    async def launch_streak_game(self, interaction, game):
        """Start the selected game using the existing streak pot."""

        game = str(game).casefold()

        if game not in GAME_NAMES:
            raise ValueError("Unsupported ONYX arcade game.")

        started = await begin_streak_round(
            self.bot,
            interaction.user.id,
            game,
        )

        if not started.get("ok"):
            return await interaction.response.send_message(
                started.get(
                    "error",
                    "Unable to continue this streak.",
                ),
                ephemeral=True,
            )

        wager = int(started["wager"])
        streak_id = started["streak_id"]
        reference = f"{streak_id}:{uuid.uuid4().hex}"

        result_handler = self.result_handler

        if game == "blackjack":
            player = [
                BlackjackView.draw(),
                BlackjackView.draw(),
            ]

            dealer = [
                BlackjackView.draw(),
                BlackjackView.draw(),
            ]

            view = BlackjackView(
                self.bot,
                interaction.user.id,
                wager,
                reference,
                player,
                dealer,
                result_handler=result_handler,
                streak_id=streak_id,
            )

            view.disable_double_down()

            await interaction.response.edit_message(
                embed=view.display(),
                view=view,
            )

            return

        if game == "slots":
            view = SlotsView(
                self.bot,
                interaction.user.id,
                wager,
                reference,
                result_handler=result_handler,
                streak_id=streak_id,
            )

            await interaction.response.edit_message(
                embed=view.slot_embed(
                    ["❔", "❔", "❔"],
                    "Press Spin to risk your streak pot.",
                ),
                view=view,
            )

            return

        view = QuickGameView(
            self.bot,
            interaction.user.id,
            wager,
            game,
            reference,
            result_handler=result_handler,
            streak_id=streak_id,
        )

        if game == "dice":
            description = (
                f"**Streak Pot at Risk:** {money(wager)}\n\n"
                "Choose Low (1–3) or High (4–6)."
            )
        else:
            description = (
                f"**Streak Pot at Risk:** {money(wager)}\n\n"
                "Choose Heads or Tails."
            )

        await interaction.response.edit_message(
            embed=make_embed(
                GAME_NAMES[game],
                description,
            ),
            view=view,
        )

    async def get_player_streak(self, user_id):
        """Return the player's current streak."""
        return await get_streak(
            self.bot,
            user_id,
        )
