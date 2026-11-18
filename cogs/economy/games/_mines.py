
"""ONYX Mines game view."""

import math
import random

import discord

from cogs.economy._common import PlayerView, make_embed, money
from cogs.economy.games._controls import get_arcade_config


GRID_SIZE = 20
GRID_COLUMNS = 5
DEFAULT_MINES = 3
RETURN_FACTOR = 0.97


def calculate_multiplier(mines, safe_picks):
    """Calculate a fair-odds multiplier with a small house edge."""

    mines = int(mines)
    safe_picks = int(safe_picks)

    if safe_picks <= 0:
        return 1.0

    if not 1 <= mines < GRID_SIZE:
        raise ValueError("Invalid mine count.")

    if not 1 <= safe_picks <= GRID_SIZE - mines:
        raise ValueError("Invalid number of safe picks.")

    probability = 1.0

    for index in range(safe_picks):
        probability *= (
            (GRID_SIZE - mines - index)
            / (GRID_SIZE - index)
        )

    if probability <= 0:
        return 0.0

    return round(RETURN_FACTOR / probability, 4)


class MinesView(PlayerView):
    """Button-based Mines game for one Discord player."""

    def __init__(
        self,
        bot,
        user_id,
        bet,
        reference,
        mines=DEFAULT_MINES,
        result_handler=None,
        streak_id=None,
    ):
        mines = int(mines)

        if not 1 <= mines <= 19:
            raise ValueError("Mine count must be between 1 and 19.")

        super().__init__(
            bot,
            user_id,
            bet,
            "mines",
            reference,
            timeout=120,
            streak_id=streak_id,
        )

        self.mine_count = mines
        self.result_handler = result_handler

        self.mine_positions = set(
            random.sample(range(GRID_SIZE), mines)
        )

        self.revealed = set()
        self.safe_picks = 0
        self.current_multiplier = 1.0
        self.current_payout = 0

        self.tile_buttons = []

        for index in range(GRID_SIZE):
            button = discord.ui.Button(
                label="❔",
                style=discord.ButtonStyle.secondary,
                row=index // GRID_COLUMNS,
                custom_id=f"onyx_mines_{index}",
            )

            button.callback = self.make_tile_callback(index)

            self.tile_buttons.append(button)
            self.add_item(button)

        self.cashout_button = discord.ui.Button(
            label="Cash Out",
            emoji="💰",
            style=discord.ButtonStyle.success,
            row=4,
        )

        self.cashout_button.callback = self.cash_out
        self.add_item(self.cashout_button)

    def make_tile_callback(self, index):
        async def callback(interaction):
            await self.reveal_tile(interaction, index)

        return callback

    def current_embed(self, result=None):
        """Build the current Mines game display."""

        description = (
            f"**Wager:** {money(self.bet)}\n"
            f"**Mines:** {self.mine_count}\n"
            f"**Safe tiles:** {self.safe_picks}\n"
            f"**Multiplier:** {self.current_multiplier:.2f}x\n"
            f"**Cash-out value:** {money(self.current_payout)}\n\n"
            "Reveal safe tiles and cash out before hitting a mine!"
        )

        if result:
            description += f"\n\n{result}"

        return make_embed("💣 ONYX MINES", description)

    async def update_multiplier(self):
        """Refresh the multiplier and apply the configured payout cap."""

        self.current_multiplier = calculate_multiplier(
            self.mine_count,
            self.safe_picks,
        )

        calculated_payout = int(
            math.floor(self.bet * self.current_multiplier)
        )

        try:
            config = await get_arcade_config(self.bot)
            maximum_payout = max(
                0,
                int(config["maximum_payout"]),
            )
        except Exception:
            maximum_payout = 2_000_000

        self.current_payout = min(
            calculated_payout,
            maximum_payout,
        )

    def disable_game(self):
        """Disable all tiles and cash-out controls."""

        for item in self.children:
            item.disabled = True

    def reveal_all_mines(self):
        """Show every mine after the game ends."""

        for index in self.mine_positions:
            button = self.tile_buttons[index]
            button.label = "💣"
            button.style = discord.ButtonStyle.danger
            button.disabled = True

    async def settle_cashout(self, interaction):
        """Settle a cash-out when the caller already owns the lock."""

        self.finished = True
        self.disable_game()
        self.reveal_all_mines()

        payout = int(self.current_payout)

        result = (
            f"💰 You cashed out after **{self.safe_picks}** "
            f"safe picks!\n"
            f"**Multiplier:** {self.current_multiplier:.2f}x\n"
            f"**Payout:** {money(payout)}"
        )

        if self.result_handler:
            await self.result_handler(
                interaction,
                self,
                "win",
                payout,
                result,
            )
            return

        await interaction.response.edit_message(
            embed=self.current_embed(result),
            view=self,
        )

    async def reveal_tile(self, interaction, index):
        """Reveal one tile and settle immediately if it is a mine."""

        if self.finished or self.settling:
            return await interaction.response.send_message(
                "This Mines game has already ended.",
                ephemeral=True,
            )

        if index in self.revealed:
            return await interaction.response.send_message(
                "You already revealed that tile.",
                ephemeral=True,
            )

        self.settling = True

        try:
            self.revealed.add(index)
            button = self.tile_buttons[index]

            if index in self.mine_positions:
                button.label = "💣"
                button.style = discord.ButtonStyle.danger
                button.disabled = True

                self.finished = True
                self.disable_game()
                self.reveal_all_mines()

                result = (
                    f"💥 You hit a mine and lost "
                    f"**{money(self.bet)}**."
                )

                if self.result_handler:
                    await self.result_handler(
                        interaction,
                        self,
                        "loss",
                        0,
                        result,
                    )
                    return

                return await interaction.response.edit_message(
                    embed=self.current_embed(result),
                    view=self,
                )

            button.label = "💎"
            button.style = discord.ButtonStyle.success
            button.disabled = True

            self.safe_picks += 1
            await self.update_multiplier()

            if self.safe_picks >= GRID_SIZE - self.mine_count:
                await self.settle_cashout(interaction)
                return

            await interaction.response.edit_message(
                embed=self.current_embed(
                    "💎 Safe tile! Your potential payout increased."
                ),
                view=self,
            )

        finally:
            self.settling = False

    async def cash_out(self, interaction):
        """Settle the current potential payout."""

        if self.finished or self.settling:
            return await interaction.response.send_message(
                "This Mines game has already ended.",
                ephemeral=True,
            )

        if self.safe_picks < 1:
            return await interaction.response.send_message(
                "Reveal at least one safe tile before cashing out.",
                ephemeral=True,
            )

        self.settling = True

        try:
            await self.settle_cashout(interaction)
        finally:
            self.settling = False

    async def on_timeout(self):
        """Use the shared refund behavior if the game expires."""

        await super().on_timeout()
