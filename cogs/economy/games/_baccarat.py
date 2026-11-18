
"""ONYX Baccarat game with Player, Banker, and Tie bets."""

import random

import discord

from cogs.economy._common import PlayerView, make_embed, money


SUITS = ("♠️", "♥️", "♦️", "♣️")
RANKS = (
    "A", "2", "3", "4", "5", "6", "7",
    "8", "9", "10", "J", "Q", "K",
)

BET_OPTIONS = {
    "player": ("Player", 2.00),
    "banker": ("Banker", 1.95),
    "tie": ("Tie", 8.00),
}


def draw_card():
    """Draw one card from a freshly shuffled eight-deck shoe."""

    rank = random.choice(RANKS)
    suit = random.choice(SUITS)

    if rank == "A":
        value = 1
    elif rank in {"10", "J", "Q", "K"}:
        value = 0
    else:
        value = int(rank)

    return {
        "rank": rank,
        "suit": suit,
        "value": value,
    }


def hand_total(cards):
    """Return the Baccarat hand total, from zero through nine."""

    return sum(card["value"] for card in cards) % 10


def format_hand(cards):
    """Format a hand for the Discord result display."""

    return "  ".join(
        f"{card['rank']}{card['suit']}"
        for card in cards
    )


def banker_draws(banker_total, player_third):
    """Apply the standard Baccarat Banker third-card rules."""

    if player_third is None:
        return banker_total <= 5

    if banker_total <= 2:
        return True

    if banker_total == 3:
        return player_third != 8

    if banker_total == 4:
        return 2 <= player_third <= 7

    if banker_total == 5:
        return 4 <= player_third <= 7

    if banker_total == 6:
        return player_third in {6, 7}

    return False


def play_baccarat():
    """Deal and resolve one standard Baccarat round."""

    player = [draw_card(), draw_card()]
    banker = [draw_card(), draw_card()]

    player_total = hand_total(player)
    banker_total = hand_total(banker)

    # A natural 8 or 9 ends the round immediately.
    if player_total not in {8, 9} and banker_total not in {8, 9}:
        player_third = None

        # Player draws on 0–5 and stands on 6–7.
        if player_total <= 5:
            card = draw_card()
            player.append(card)
            player_third = card["value"]

        # Banker follows the standard third-card table.
        if banker_draws(banker_total, player_third):
            banker.append(draw_card())

    player_total = hand_total(player)
    banker_total = hand_total(banker)

    if player_total > banker_total:
        winner = "player"
    elif banker_total > player_total:
        winner = "banker"
    else:
        winner = "tie"

    return {
        "player": player,
        "banker": banker,
        "player_total": player_total,
        "banker_total": banker_total,
        "winner": winner,
    }


class BaccaratView(PlayerView):
    """Button-based Baccarat game for one ONYX player."""

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
            "baccarat",
            reference,
            timeout=90,
            streak_id=streak_id,
        )

        self.result_handler = result_handler
        self.selected_bet = None
        self.selection_buttons = {}

        options = [
            ("Player", "player", 0),
            ("Banker", "banker", 0),
            ("Tie", "tie", 0),
        ]

        for label, bet_type, row in options:
            button = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.danger,
                row=row,
                custom_id=f"onyx_baccarat_{bet_type}",
            )

            button.callback = self.make_selection_callback(bet_type)

            self.selection_buttons[bet_type] = button
            self.add_item(button)

        self.deal_button = discord.ui.Button(
            label="Deal Cards",
            emoji="🃏",
            style=discord.ButtonStyle.success,
            row=1,
            custom_id="onyx_baccarat_deal",
        )
        self.deal_button.callback = self.deal
        self.add_item(self.deal_button)

    def make_selection_callback(self, bet_type):
        async def callback(interaction):
            if self.finished or self.settling:
                return await interaction.response.send_message(
                    "This Baccarat game has already ended.",
                    ephemeral=True,
                )

            if interaction.user.id != self.user_id:
                return await interaction.response.send_message(
                    "This game belongs to another player.",
                    ephemeral=True,
                )

            self.selected_bet = bet_type

            for key, button in self.selection_buttons.items():
                button.style = (
                    discord.ButtonStyle.success
                    if key == bet_type
                    else discord.ButtonStyle.danger
                )

            await interaction.response.edit_message(
                embed=self.current_embed(
                    f"Selected bet: **{BET_OPTIONS[bet_type][0]}**. "
                    "Press Deal Cards when ready."
                ),
                view=self,
            )

        return callback

    def current_embed(self, message=None, result=None):
        selected = (
            BET_OPTIONS[self.selected_bet][0]
            if self.selected_bet
            else "None"
        )

        description = (
            f"**Wager:** {money(self.bet)}\n"
            f"**Selected Bet:** {selected}\n\n"
            "**Choose your winning hand:**\n"
            "🟦 Player — 2.00x total return\n"
            "🟥 Banker — 1.95x total return\n"
            "🟩 Tie — 8.00x total return\n\n"
            "The hand closest to 9 wins.\n"
            "Card values are added together; only the last digit counts."
        )

        if message:
            description += f"\n\n{message}"

        if result:
            description += f"\n\n{result}"

        return make_embed("🃏 ONYX BACCARAT", description)

    async def deal(self, interaction):
        if self.finished or self.settling:
            return await interaction.response.send_message(
                "This Baccarat game has already ended.",
                ephemeral=True,
            )

        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(
                "This game belongs to another player.",
                ephemeral=True,
            )

        if not self.selected_bet:
            return await interaction.response.send_message(
                "Choose Player, Banker, or Tie before dealing.",
                ephemeral=True,
            )

        self.settling = True

        try:
            round_result = play_baccarat()
            winner = round_result["winner"]

            player_cards = format_hand(round_result["player"])
            banker_cards = format_hand(round_result["banker"])

            player_total = round_result["player_total"]
            banker_total = round_result["banker_total"]

            result_text = (
                f"**PLAYER:** {player_cards}\n"
                f"Total: **{player_total}**\n\n"
                f"**BANKER:** {banker_cards}\n"
                f"Total: **{banker_total}**\n\n"
                f"🏆 Winning hand: **{winner.title()}**"
            )

            if self.selected_bet == winner:
                multiplier = BET_OPTIONS[self.selected_bet][1]
                payout = int(self.bet * multiplier)

                outcome = "win"
                result_text += (
                    f"\n\n🎉 **You won {money(payout)}!**\n"
                    f"Your total return: **{money(payout)}**"
                )

            elif winner == "tie" and self.selected_bet in {
                "player",
                "banker",
            }:
                payout = self.bet
                outcome = "push"

                result_text += (
                    f"\n\n🤝 **Tie!** Your wager was returned."
                )

            else:
                payout = 0
                outcome = "loss"

                result_text += (
                    f"\n\n❌ **You lost {money(self.bet)}.**"
                )

            self.finished = True
            self.disable_controls()

            if self.result_handler:
                await self.result_handler(
                    interaction,
                    self,
                    outcome,
                    payout,
                    result_text,
                )
            else:
                await interaction.response.edit_message(
                    embed=make_embed(
                        "🃏 ONYX BACCARAT",
                        result_text,
                    ),
                    view=self,
                )

        finally:
            self.settling = False
