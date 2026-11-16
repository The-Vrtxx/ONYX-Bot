
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


async def edit_game_message(interaction, **kwargs):
    """Edit the original game message, even after an interaction was used."""

    if interaction.response.is_done():
        return await interaction.edit_original_response(**kwargs)

    return await interaction.response.edit_message(**kwargs)


class ArcadeManager:
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
        user_id = int(game_view.user_id)
        game = str(game_view.game)
        streak_id = getattr(game_view, "streak_id", None)

        # A push leaves a continued streak pot unchanged.
        if outcome == "push":
            if streak_id:
                await cancel_streak_round(
                    self.bot,
                    user_id,
                    streak_id,
                )

                streak = await get_streak(self.bot, user_id)

                if streak:
                    return await self.show_decision(
                        interaction,
                        streak,
                        game,
                        prefix=(
                            f"{result_text}\n\n"
                            "Your streak pot is unchanged."
                        ),
                    )

                result_text += (
                    "\n\n⚠️ Your streak could not be recovered. "
                    "Please contact an ONYX administrator."
                )

                return await edit_game_message(
                    interaction,
                    embed=make_embed("ONYX STREAK REVIEW", result_text),
                    view=None,
                )

            paid = await pay_out(
                self.bot,
                user_id,
                int(payout),
                f"{game}_push",
                game_view.reference,
            )

            if not paid.get("ok"):
                result_text += (
                    "\n\n⚠️ The wager return could not be processed. "
                    "Please contact an ONYX administrator."
                )

            return await edit_game_message(
                interaction,
                embed=make_embed(
                    GAME_NAMES.get(game, "ONYX ARCADE"),
                    result_text,
                ),
                view=None,
            )

        # A loss ends a continued streak.
        if outcome == "loss":
            if streak_id:
                lost = await lose_streak(
                    self.bot,
                    user_id,
                    streak_id,
                )

                if lost.get("ok"):
                    result_text += (
                        "\n\n🔥 **Your streak has ended.**\n"
                        f"You lost the entire "
                        f"**{money(lost['lost_amount'])}** streak pot."
                    )
                else:
                    result_text += (
                        "\n\n⚠️ Streak settlement needs "
                        "administrator review."
                    )

            return await edit_game_message(
                interaction,
                embed=make_embed(
                    GAME_NAMES.get(game, "ONYX ARCADE"),
                    result_text,
                ),
                view=None,
            )

        # A continued streak win multiplies the entire current pot.
        if streak_id:
            updated = await record_streak_win(
                self.bot,
                user_id,
                streak_id,
            )

            if not updated.get("ok"):
                await cancel_streak_round(
                    self.bot,
                    user_id,
                    streak_id,
                )

                streak = await get_streak(self.bot, user_id)

                if streak:
                    return await self.show_decision(
                        interaction,
                        streak,
                        game,
                        prefix=(
                            f"{result_text}\n\n"
                            "⚠️ Your current streak pot has been preserved. "
                            "The next payout exceeds a configured arcade "
                            "limit, so you must cash out."
                        ),
                    )

                result_text += (
                    "\n\n⚠️ The streak could not be advanced. "
                    "Please contact an ONYX administrator."
                )

                return await edit_game_message(
                    interaction,
                    embed=make_embed("ONYX STREAK REVIEW", result_text),
                    view=None,
                )

            streak = updated["streak"]

            return await self.show_decision(
                interaction,
                streak,
                game,
                prefix=(
                    f"{result_text}\n\n"
                    f"🔥 Streak multiplier: "
                    f"**{updated['multiplier_used']}x**\n"
                    f"New streak pot: **{money(updated['new_pot'])}**"
                ),
            )

        # First win: hold the winnings in a new optional streak.
        created = await create_streak(
            self.bot,
            user_id,
            int(payout),
            game,
            reference=game_view.reference,
        )

        if not created.get("ok"):
            paid = await pay_out(
                self.bot,
                user_id,
                int(payout),
                f"{game}_payout",
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

            return await edit_game_message(
                interaction,
                embed=make_embed(
                    GAME_NAMES.get(game, "ONYX ARCADE"),
                    result_text,
                ),
                view=None,
            )

        return await self.show_decision(
            interaction,
            created["streak"],
            game,
            prefix=result_text,
        )

    async def show_decision(
        self,
        interaction,
        streak,
        previous_game=None,
        prefix="",
    ):
        view = StreakDecisionView(
            bot=self.bot,
            user_id=interaction.user.id,
            streak=streak,
            launch_game=self.launch_streak_game,
        )

        embed = await view.decision_embed()

        if prefix:
            embed.description = (
                f"{prefix}\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{embed.description}"
            )

        return await edit_game_message(
            interaction,
            embed=embed,
            view=view,
        )

    async def launch_streak_game(self, interaction, game):
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

        try:
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
                    result_handler=self.result_handler,
                    streak_id=streak_id,
                )

                player_total = view.total(player)
                dealer_total = view.total(dealer)

                # A natural in a streak round settles immediately.
                if player_total == 21 and dealer_total == 21:
                    view.finished = True
                    view.disable_controls()

                    await self.result_handler(
                        interaction,
                        view,
                        "push",
                        wager,
                        (
                            "🤝 Both you and the dealer have blackjack. "
                            "Your streak pot is unchanged."
                        ),
                    )

                    return

                if player_total == 21:
                    view.finished = True
                    view.disable_controls()

                    await self.result_handler(
                        interaction,
                        view,
                        "win",
                        wager * 2,
                        "🌟 **Natural Blackjack!** You won this streak round.",
                    )

                    return

                if dealer_total == 21:
                    view.finished = True
                    view.disable_controls()

                    await self.result_handler(
                        interaction,
                        view,
                        "loss",
                        0,
                        "Dealer has blackjack. You lost this streak round.",
                    )

                    return

                return await edit_game_message(
                    interaction,
                    embed=view.display(),
                    view=view,
                )

            if game == "slots":
                view = SlotsView(
                    self.bot,
                    interaction.user.id,
                    wager,
                    reference,
                    result_handler=self.result_handler,
                    streak_id=streak_id,
                )

                return await edit_game_message(
                    interaction,
                    embed=view.slot_embed(
                        ["❔", "❔", "❔"],
                        "Press Spin to risk your streak pot.",
                    ),
                    view=view,
                )

            view = QuickGameView(
                self.bot,
                interaction.user.id,
                wager,
                game,
                reference,
                result_handler=self.result_handler,
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

            return await edit_game_message(
                interaction,
                embed=make_embed(
                    GAME_NAMES[game],
                    description,
                ),
                view=view,
            )

        except Exception:
            # If the game could not be displayed, restore the streak.
            await cancel_streak_round(
                self.bot,
                interaction.user.id,
                streak_id,
            )
            raise

    async def get_player_streak(self, user_id):
        return await get_streak(self.bot, user_id)
