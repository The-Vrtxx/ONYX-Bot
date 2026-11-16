
"""ONYX Blackjack game view."""

import random

import discord

from cogs.economy._common import (
    PlayerView,
    make_embed,
    money,
    pay_out,
    place_wager,
)


class BlackjackView(PlayerView):
    """Native Discord embed Blackjack game."""

    SUITS = ("♠", "♥", "♦", "♣")

    RANKS = (
        ("2", 2),
        ("3", 3),
        ("4", 4),
        ("5", 5),
        ("6", 6),
        ("7", 7),
        ("8", 8),
        ("9", 9),
        ("10", 10),
        ("J", 10),
        ("Q", 10),
        ("K", 10),
        ("A", 11),
    )

    def __init__(
        self,
        bot,
        user_id,
        bet,
        reference,
        player,
        dealer,
        result_handler=None,
        streak_id=None,
    ):
        super().__init__(
            bot,
            user_id,
            bet,
            "blackjack",
            reference,
            timeout=90,
        )

        self.player = player
        self.dealer = dealer
        self.result_handler = result_handler
        self.streak_id = streak_id

    @classmethod
    def draw(cls):
        rank, value = random.choice(cls.RANKS)
        suit = random.choice(cls.SUITS)
        return (rank, value, suit)

    @staticmethod
    def total(hand):
        total = sum(card[1] for card in hand)

        aces = sum(
            1 for card in hand
            if card[0] == "A"
        )

        while total > 21 and aces:
            total -= 10
            aces -= 1

        return total

    @staticmethod
    def format_hand(hand, hide_second=False):
        tick = chr(96)
        displayed = []

        for index, card in enumerate(hand):
            if hide_second and index == 1:
                displayed.append(f"{tick}[ ?? ]{tick}")
            else:
                rank, _value, suit = card
                displayed.append(
                    f"{tick}[ {rank} {suit} ]{tick}"
                )

        return "　".join(displayed)

    def display(self, reveal=False, result=""):
        player_total = self.total(self.player)

        dealer_total = (
            self.total(self.dealer)
            if reveal
            else None
        )

        embed = make_embed(
            "🃏 ONYX BLACKJACK",
            (
                f"**Wager:** {money(self.bet)}\n"
                "━━━━━━━━━━━━━━━━━━━━"
            ),
        )

        embed.add_field(
            name=f"YOUR HAND — {player_total}",
            value=self.format_hand(self.player),
            inline=False,
        )

        embed.add_field(
            name=(
                f"DEALER'S HAND — {dealer_total}"
                if reveal
                else "DEALER'S HAND — Hidden"
            ),
            value=self.format_hand(
                self.dealer,
                hide_second=not reveal,
            ),
            inline=False,
        )

        if result:
            embed.add_field(
                name="ROUND RESULT",
                value=result,
                inline=False,
            )

        if not self.finished:
            embed.set_footer(
                text=(
                    "Hit to draw • Stand to hold • "
                    "Double Down to double your wager"
                )
            )
        else:
            embed.set_footer(
                text="ONYX Arcade • Blackjack"
            )

        return embed

    async def update_message(
        self,
        interaction,
        reveal=False,
        result="",
        view=None,
    ):
        await interaction.response.edit_message(
            embed=self.display(
                reveal=reveal,
                result=result,
            ),
            view=self if view is None else view,
            attachments=[],
        )

    async def handle_win(self, interaction, payout, result):
        """Send a win to the shared economy handler when provided."""

        if self.result_handler:
            await self.result_handler(
                interaction,
                self,
                "win",
                int(payout),
                result,
            )
            return

        await pay_out(
            self.bot,
            self.user_id,
            payout,
            "blackjack_payout",
            self.reference,
        )

        await self.update_message(
            interaction,
            reveal=True,
            result=result,
        )

    async def handle_loss(self, interaction, result):
        """Send a loss to the shared economy handler when provided."""

        if self.result_handler:
            await self.result_handler(
                interaction,
                self,
                "loss",
                0,
                result,
            )
            return

        await self.update_message(
            interaction,
            reveal=True,
            result=result,
        )

    async def finish(
        self,
        interaction,
        dealer_plays=True,
    ):
        if self.finished:
            return

        if dealer_plays:
            while self.total(self.dealer) < 17:
                self.dealer.append(self.draw())

        player_total = self.total(self.player)
        dealer_total = self.total(self.dealer)

        self.finished = True
        self.disable_controls()

        if player_total > 21:
            return await self.handle_loss(
                interaction,
                f"💥 Bust! You lost {money(self.bet)}.",
            )

        if dealer_total > 21 or player_total > dealer_total:
            returned = self.bet * 2

            return await self.handle_win(
                interaction,
                returned,
                f"🎉 You won! **{money(returned)}** returned.",
            )

        if player_total == dealer_total:
            if self.result_handler:
                await self.result_handler(
                    interaction,
                    self,
                    "push",
                    self.bet,
                    (
                        f"🤝 Push! Your **{money(self.bet)}** "
                        "wager was returned."
                    ),
                )
                return

            await pay_out(
                self.bot,
                self.user_id,
                self.bet,
                "blackjack_push",
                self.reference,
            )

            return await self.update_message(
                interaction,
                reveal=True,
                result=(
                    f"🤝 Push! Your **{money(self.bet)}** "
                    "wager was returned."
                ),
            )

        return await self.handle_loss(
            interaction,
            f"Dealer wins. You lost {money(self.bet)}.",
        )

    @discord.ui.button(
        label="Hit",
        emoji="🃏",
        style=discord.ButtonStyle.primary,
    )
    async def hit(self, interaction, button):
        self.player.append(self.draw())

        total = self.total(self.player)

        if total >= 21:
            await self.finish(
                interaction,
                dealer_plays=(total == 21),
            )
        else:
            await self.update_message(interaction)

    @discord.ui.button(
        label="Stand",
        emoji="✋",
        style=discord.ButtonStyle.secondary,
    )
    async def stand(self, interaction, button):
        await self.finish(interaction)

    @discord.ui.button(
        label="Double Down",
        emoji="💰",
        style=discord.ButtonStyle.success,
    )
    async def double_down(self, interaction, button):
        if len(self.player) != 2:
            return await interaction.response.send_message(
                "Double Down is only available on your first turn.",
                ephemeral=True,
            )

        result = await place_wager(
            self.bot,
            self.user_id,
            self.bet,
            "blackjack_double",
        )

        if not result.get("ok"):
            return await interaction.response.send_message(
                result.get(
                    "error",
                    "You cannot double down.",
                ),
                ephemeral=True,
            )

        self.bet *= 2
        self.player.append(self.draw())

        await self.finish(
            interaction,
            dealer_plays=(self.total(self.player) <= 21),
        )
