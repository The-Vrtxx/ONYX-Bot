"""ONYX global Credits economy.

PostgreSQL-backed global wallets shared by every ONYX server.
Prestige Tokens remain separate and are never modified here.
"""

import random
import uuid
from datetime import datetime, timezone

import discord
from discord.ext import commands

from currency_system import (
    MAX_CREDITS,
    ensure_currency_tables,
    get_credit_balance,
    grant_credits,
    spend_credits,
)

COLOR = discord.Color.from_rgb(25, 190, 190)
SLOT_SYMBOLS = ("🍒", "🍋", "🍇", "🔔", "💎", "7️⃣")


async def ensure_economy_tables(pool):
    await ensure_currency_tables(pool)
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS onyx_economy_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                daily_reward BIGINT NOT NULL DEFAULT 500,
                weekly_reward BIGINT NOT NULL DEFAULT 2500,
                work_min BIGINT NOT NULL DEFAULT 100,
                work_max BIGINT NOT NULL DEFAULT 300,
                beg_min BIGINT NOT NULL DEFAULT 10,
                beg_max BIGINT NOT NULL DEFAULT 100,
                daily_cooldown INTEGER NOT NULL DEFAULT 86400,
                weekly_cooldown INTEGER NOT NULL DEFAULT 604800,
                work_cooldown INTEGER NOT NULL DEFAULT 3600,
                beg_cooldown INTEGER NOT NULL DEFAULT 1800,
                min_bet BIGINT NOT NULL DEFAULT 10,
                max_bet BIGINT NOT NULL DEFAULT 100000,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                updated_by BIGINT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            INSERT INTO onyx_economy_settings (id)
            VALUES (1) ON CONFLICT (id) DO NOTHING
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS onyx_economy_cooldowns (
                user_id BIGINT NOT NULL,
                action TEXT NOT NULL,
                next_claim_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (user_id, action)
            )
        """)


def money(amount):
    return f"{int(amount):,} Credits"


def make_embed(title, description, color=COLOR):
    return discord.Embed(title=title, description=description, color=color)


async def settings_for(bot):
    async with bot.db.pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM onyx_economy_settings WHERE id=1"
        )


async def claim_reward(bot, user_id, action, amount, cooldown):
    """Claim cooldown and reward in one database transaction."""
    async with bot.db.pool.acquire() as conn:
        async with conn.transaction():
            claim = await conn.fetchrow("""
                INSERT INTO onyx_economy_cooldowns
                    (user_id, action, next_claim_at)
                VALUES (
                    $1, $2,
                    CURRENT_TIMESTAMP + ($3 * INTERVAL '1 second')
                )
                ON CONFLICT (user_id, action) DO UPDATE
                SET next_claim_at =
                    CURRENT_TIMESTAMP + ($3 * INTERVAL '1 second')
                WHERE onyx_economy_cooldowns.next_claim_at <= CURRENT_TIMESTAMP
                RETURNING next_claim_at
            """, user_id, action, int(cooldown))

            if claim is None:
                next_at = await conn.fetchval("""
                    SELECT next_claim_at
                    FROM onyx_economy_cooldowns
                    WHERE user_id=$1 AND action=$2
                """, user_id, action)
                return False, next_at

            if amount > 0:
                result = await grant_credits(
                    conn,
                    user_id,
                    amount,
                    source=f"reward_{action}",
                    description=f"ONYX {action} reward",
                    reference_id=f"{action}:{user_id}:{uuid.uuid4().hex}",
                )
                if not result.get("ok"):
                    raise RuntimeError("Reward could not be granted.")
            return True, amount


async def place_wager(bot, user_id, amount, source):
    if amount <= 0 or amount > MAX_CREDITS:
        return {"ok": False, "error": "Enter a valid positive wager."}

    async with bot.db.pool.acquire() as conn:
        async with conn.transaction():
            settings = await conn.fetchrow("""
                SELECT min_bet, max_bet, enabled
                FROM onyx_economy_settings WHERE id=1
            """)
            if not settings or not settings["enabled"]:
                return {"ok": False, "error": "The ONYX economy is disabled."}
            if amount < settings["min_bet"] or amount > settings["max_bet"]:
                return {
                    "ok": False,
                    "error": (
                        f"Bets must be between {settings['min_bet']:,} "
                        f"and {settings['max_bet']:,} Credits."
                    ),
                }
            return await spend_credits(
                conn, user_id, amount, source, "ONYX Arcade wager"
            )


async def pay_out(bot, user_id, amount, source, reference):
    if amount <= 0:
        return
    async with bot.db.pool.acquire() as conn:
        async with conn.transaction():
            return await grant_credits(
                conn,
                user_id,
                amount,
                source=source,
                description="ONYX Arcade payout",
                reference_id=str(reference),
            )


class PlayerView(discord.ui.View):
    """Restricts game controls to the member who placed the wager."""

    def __init__(self, bot, user_id, bet, game, reference, timeout=60):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.user_id = user_id
        self.bet = bet
        self.game = game
        self.reference = reference
        self.finished = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This game belongs to another player.", ephemeral=True
            )
            return False
        if self.finished:
            await interaction.response.send_message(
                "This game has already ended.", ephemeral=True
            )
            return False
        return True

    async def refund(self):
        if self.finished:
            return
        self.finished = True
        await pay_out(
            self.bot, self.user_id, self.bet,
            f"{self.game}_refund", self.reference
        )
        for child in self.children:
            child.disabled = True

    async def on_timeout(self):
        try:
            await self.refund()
        except Exception:
            # Never crash Discord's view timeout task.
            pass


class BetChoiceView(PlayerView):
    def __init__(self, bot, user_id, bet, game, reference):
        super().__init__(bot, user_id, bet, game, reference)

    async def settle(self, interaction, choice):
        if self.game == "betflip":
            result = random.choice(("heads", "tails"))
            won = choice == result
            result_text = result.title()
        else:
            result = random.randint(1, 6)
            won = result >= 4 if choice == "high" else result <= 3
            result_text = str(result)

        self.finished = True
        for child in self.children:
            child.disabled = True

        if won:
            payout = self.bet * 2
            await pay_out(
                self.bot, self.user_id, payout,
                f"{self.game}_payout", self.reference
            )
            message = f"🎉 You won **{money(payout)}**!\nResult: **{result_text}**"
        else:
            message = f"You lost **{money(self.bet)}**.\nResult: **{result_text}**"

        await interaction.response.edit_message(
            embed=make_embed(f"ONYX {self.game.title()}", message),
            view=self,
        )

    @discord.ui.button(label="Heads", style=discord.ButtonStyle.primary)
    async def heads(self, interaction, button):
        if self.game != "betflip":
            return await interaction.response.send_message(
                "That choice isn't available in this game.", ephemeral=True
            )
        await self.settle(interaction, "heads")

    @discord.ui.button(label="Tails", style=discord.ButtonStyle.primary)
    async def tails(self, interaction, button):
        if self.game != "betflip":
            return await interaction.response.send_message(
                "That choice isn't available in this game.", ephemeral=True
            )
        await self.settle(interaction, "tails")

    @discord.ui.button(
        label="High (4–6)", style=discord.ButtonStyle.success, row=1
    )
    async def high(self, interaction, button):
        if self.game != "dice":
            return await interaction.response.send_message(
                "That choice isn't available in this game.", ephemeral=True
            )
        await self.settle(interaction, "high")

    @discord.ui.button(
        label="Low (1–3)", style=discord.ButtonStyle.secondary, row=1
    )
    async def low(self, interaction, button):
        if self.game != "dice":
            return await interaction.response.send_message(
                "That choice isn't available in this game.", ephemeral=True
            )
        await self.settle(interaction, "low")


class SlotsView(PlayerView):
    def __init__(self, bot, user_id, bet, reference):
        super().__init__(bot, user_id, bet, "slots", reference)

    @discord.ui.button(
        label="Spin", emoji="🎰", style=discord.ButtonStyle.success
    )
    async def spin(self, interaction, button):
        reels = [random.choice(SLOT_SYMBOLS) for _ in range(3)]
        if reels == ["7️⃣", "7️⃣", "7️⃣"]:
            multiplier = 10
        elif len(set(reels)) == 1:
            multiplier = 5
        elif len(set(reels)) == 2:
            multiplier = 2
        else:
            multiplier = 0

        self.finished = True
        button.disabled = True

        if multiplier:
            winnings = self.bet * multiplier
            await pay_out(
                self.bot, self.user_id, winnings,
                "slots_payout", self.reference
            )
            result = f"🎉 **{money(winnings)}** payout ({multiplier}x)!"
        else:
            result = f"No win this time. You lost {money(self.bet)}."

        await interaction.response.edit_message(
            embed=make_embed(
                "🎰 ONYX Slots",
                f"# {' | '.join(reels)}\n\n{result}",
            ),
            view=self,
        )


class BlackjackView(PlayerView):
    def __init__(self, bot, user_id, bet, reference, player, dealer):
        super().__init__(bot, user_id, bet, "blackjack", reference, timeout=90)
        self.player = player
        self.dealer = dealer

    @staticmethod
    def draw():
        return random.choice([2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 11])

    @staticmethod
    def total(hand):
        total = sum(hand)
        aces = hand.count(11)
        while total > 21 and aces:
            total -= 10
            aces -= 1
        return total

    def display(self, reveal=False, result=""):
        dealer = " ".join(map(str, self.dealer)) if reveal else f"{self.dealer[0]}  ?"
        description = (
            f"**Your hand:** {' '.join(map(str, self.player))} "
            f"({self.total(self.player)})\n"
            f"**Dealer:** {dealer}"
        )
        if result:
            description += f"\n\n{result}"
        return make_embed("🃏 ONYX Blackjack", description)

    async def finish(self, interaction, dealer_plays=True):
        if dealer_plays:
            while self.total(self.dealer) < 17:
                self.dealer.append(self.draw())

        player_total = self.total(self.player)
        dealer_total = self.total(self.dealer)
        self.finished = True
        for child in self.children:
            child.disabled = True

        if player_total > 21:
            result = f"💥 Bust! You lost {money(self.bet)}."
        elif dealer_total > 21 or player_total > dealer_total:
            returned = self.bet * 2
            await pay_out(
                self.bot, self.user_id, returned,
                "blackjack_payout", self.reference
            )
            result = f"🎉 You won! **{money(returned)}** returned."
        elif player_total == dealer_total:
            await pay_out(
                self.bot, self.user_id, self.bet,
                "blackjack_push", self.reference
            )
            result = f"🤝 Push! Your **{money(self.bet)}** wager was returned."
        else:
            result = f"Dealer wins. You lost {money(self.bet)}."

        await interaction.response.edit_message(
            embed=self.display(True, result), view=self
        )

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary)
    async def hit(self, interaction, button):
        self.player.append(self.draw())
        total = self.total(self.player)
        if total >= 21:
            await self.finish(interaction, dealer_plays=(total == 21))
        else:
            await interaction.response.edit_message(
                embed=self.display(), view=self
            )

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction, button):
        await self.finish(interaction)

    @discord.ui.button(label="Double Down", style=discord.ButtonStyle.success)
    async def double_down(self, interaction, button):
        if len(self.player) != 2:
            return await interaction.response.send_message(
                "Double Down is only available on your first turn.",
                ephemeral=True,
            )
        result = await place_wager(
            self.bot, self.user_id, self.bet, "blackjack_double"
        )
        if not result.get("ok"):
            return await interaction.response.send_message(
                result.get("error", "You cannot double down."),
                ephemeral=True,
            )
        self.bet *= 2
        self.player.append(self.draw())
        await self.finish(interaction)


class Economy(commands.Cog):
    """Global ONYX Credits, rewards, transfers, and arcade games."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        if self.bot.db.backend != "postgres":
            return
        await ensure_economy_tables(self.bot.db.pool)

    async def available(self, ctx):
        if self.bot.db.backend != "postgres":
            await ctx.send(
                "ONYX Credits require the PostgreSQL database. "
                "Your existing Prestige Tokens are unaffected."
            )
            return False
        settings = await settings_for(self.bot)
        if not settings or not settings["enabled"]:
            await ctx.send("The global ONYX economy is currently disabled.")
            return False
        return True

    @commands.command(
        name="balance", aliases=["bal", "credits"],
        help="View your global ONYX Credits balance.",
    )
    async def balance(self, ctx, member: discord.User = None):
        if not await self.available(ctx):
            return
        member = member or ctx.author
        async with self.bot.db.pool.acquire() as conn:
            wallet = await get_credit_balance(conn, member.id)
        em = make_embed(
            f"💳 {member.display_name}'s Wallet",
            f"## {money(wallet['credits'])}",
        )
        em.add_field(
            name="Lifetime earned",
            value=money(wallet["lifetime_earned"]),
        )
        em.add_field(
            name="Lifetime spent",
            value=money(wallet["lifetime_spent"]),
        )
        em.set_footer(text="One global wallet shared across every ONYX server")
        await ctx.send(embed=em)

    async def run_reward(self, ctx, action):
        if not await self.available(ctx):
            return
        config = await settings_for(self.bot)
        if action == "daily":
            amount = int(config["daily_reward"])
        elif action == "weekly":
            amount = int(config["weekly_reward"])
        elif action == "work":
            amount = random.randint(
                int(config["work_min"]), int(config["work_max"])
            )
        else:
            amount = random.randint(
                int(config["beg_min"]), int(config["beg_max"])
            )
            if random.random() < 0.35:
                amount = 0

        cooldown = int(config[f"{action}_cooldown"])
        success, value = await claim_reward(
            self.bot, ctx.author.id, action, amount, cooldown
        )
        if not success:
            seconds = max(
                1, int((value - datetime.now(timezone.utc)).total_seconds())
            )
            hours, remainder = divmod(seconds, 3600)
            minutes = remainder // 60
            return await ctx.send(
                f"⏳ You already claimed **{action}**. "
                f"Try again in **{hours}h {minutes}m**."
            )

        if amount:
            message = f"{ctx.author.mention}, you received **{money(amount)}**!"
            title = f"💰 ONYX {action.title()}"
        else:
            title = "🪙 No luck this time"
            message = "Nobody had any spare Credits to give you. Try again later."
        await ctx.send(embed=make_embed(title, message))

    @commands.command(name="daily", help="Claim your daily ONYX Credits.")
    async def daily(self, ctx):
        await self.run_reward(ctx, "daily")

    @commands.command(name="weekly", help="Claim your weekly ONYX Credits.")
    async def weekly(self, ctx):
        await self.run_reward(ctx, "weekly")

    @commands.command(name="work", help="Work to earn ONYX Credits.")
    async def work(self, ctx):
        await self.run_reward(ctx, "work")

    @commands.command(name="beg", help="Try your luck begging for Credits.")
    async def beg(self, ctx):
        await self.run_reward(ctx, "beg")

    @commands.command(name="pay", help="Transfer Credits to another member.")
    async def pay(self, ctx, member: discord.User, amount: int):
        if not await self.available(ctx):
            return
        if member.bot or member.id == ctx.author.id:
            return await ctx.send("You can only pay another human member.")
        if amount < 1 or amount > MAX_CREDITS:
            return await ctx.send("Enter a valid positive Credit amount.")

        async with self.bot.db.pool.acquire() as conn:
            async with conn.transaction():
                sent = await spend_credits(
                    conn, ctx.author.id, amount, "member_transfer",
                    f"Transfer to {member.id}",
                )
                if not sent.get("ok"):
                    return await ctx.send(
                        f"Not enough Credits. Your balance is "
                        f"{money(sent.get('credits', 0))}."
                    )
                received = await grant_credits(
                    conn, member.id, amount, "member_transfer",
                    f"Transfer from {ctx.author.id}",
                    reference_id=f"transfer:{uuid.uuid4().hex}",
                )
                if not received.get("ok"):
                    raise RuntimeError("Recipient wallet transfer failed.")

        await ctx.send(embed=make_embed(
            "💸 Credits Transferred",
            f"{ctx.author.mention} sent **{money(amount)}** "
            f"to {member.mention}.",
        ))

    @commands.group(
        name="economy", invoke_without_command=True,
        help="View ONYX global economy information.",
    )
    async def economy(self, ctx):
        if not await self.available(ctx):
            return
        config = await settings_for(self.bot)
        em = make_embed(
            "💰 ONYX Global Economy",
            "Earn Credits, build your wallet, and play in the ONYX Arcade.",
        )
        em.add_field(name="Daily", value=money(config["daily_reward"]))
        em.add_field(name="Weekly", value=money(config["weekly_reward"]))
        em.add_field(
            name="Bet limits",
            value=f"{config['min_bet']:,}–{config['max_bet']:,}",
        )
        em.set_footer(text="Credits are global across every ONYX server.")
        await ctx.send(embed=em)

    @economy.command(
        name="leaderboard", aliases=["top", "lb"],
        help="View the global Credits leaderboard.",
    )
    async def leaderboard(self, ctx):
        if not await self.available(ctx):
            return
        async with self.bot.db.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT user_id, credits
                FROM onyx_credit_wallet
                ORDER BY credits DESC, user_id ASC
                LIMIT 10
            """)
        if not rows:
            return await ctx.send("No ONYX wallets have been created yet.")
        lines = []
        for index, row in enumerate(rows, 1):
            user = self.bot.get_user(int(row["user_id"]))
            name = (
                discord.utils.escape_markdown(user.display_name)
                if user else f"User {row['user_id']}"
            )
            lines.append(f"**{index}.** {name} — {money(row['credits'])}")
        await ctx.send(embed=make_embed(
            "🏆 ONYX Global Credits Leaderboard", "\n".join(lines)
        ))

    async def begin_game(self, ctx, amount, source):
        if not await self.available(ctx):
            return None
        result = await place_wager(
            self.bot, ctx.author.id, amount, source
        )
        if not result.get("ok"):
            await ctx.send(
                result.get("error", "Unable to place that wager.")
            )
            return None
        return uuid.uuid4().hex

    @commands.command(
        name="betflip", help="Bet on heads or tails. Usage: ,betflip <amount>"
    )
    async def betflip(self, ctx, amount: int):
        reference = await self.begin_game(ctx, amount, "betflip_wager")
        if reference:
            await ctx.send(
                embed=make_embed(
                    "🪙 ONYX Betflip",
                    f"Wager: **{money(amount)}**\nChoose heads or tails.",
                ),
                view=BetChoiceView(
                    self.bot, ctx.author.id, amount, "betflip", reference
                ),
            )

    @commands.command(
        name="dice", help="Bet high or low. Usage: ,dice <amount>"
    )
    async def dice(self, ctx, amount: int):
        reference = await self.begin_game(ctx, amount, "dice_wager")
        if reference:
            await ctx.send(
                embed=make_embed(
                    "🎲 ONYX Dice",
                    f"Wager: **{money(amount)}**\nChoose Low (1–3) or High (4–6).",
                ),
                view=BetChoiceView(
                    self.bot, ctx.author.id, amount, "dice", reference
                ),
            )

    @commands.command(
        name="slots", help="Play the ONYX slot machine. Usage: ,slots <amount>"
    )
    async def slots(self, ctx, amount: int):
        reference = await self.begin_game(ctx, amount, "slots_wager")
        if reference:
            await ctx.send(
                embed=make_embed(
                    "🎰 ONYX Slots",
                    f"Wager: **{money(amount)}**\nPress Spin to play.",
                ),
                view=SlotsView(self.bot, ctx.author.id, amount, reference),
            )

    @commands.command(
        name="blackjack", aliases=["bj"],
        help="Play blackjack. Usage: ,blackjack <amount>",
    )
    async def blackjack(self, ctx, amount: int):
        reference = await self.begin_game(ctx, amount, "blackjack_wager")
        if not reference:
            return
        draw = BlackjackView.draw
        player = [draw(), draw()]
        dealer = [draw(), draw()]
        view = BlackjackView(
            self.bot, ctx.author.id, amount, reference, player, dealer
        )
        if view.total(player) == 21:
            view.finished = True
            for child in view.children:
                child.disabled = True
            winnings = int(amount * 2.5)
            await pay_out(
                self.bot, ctx.author.id, winnings,
                "blackjack_natural", reference,
            )
            return await ctx.send(
                embed=view.display(
                    True, f"🌟 Blackjack! You received {money(winnings)}."
                ),
                view=view,
            )
        await ctx.send(embed=view.display(), view=view)

    @commands.group(name="econconfig", invoke_without_command=True, hidden=True)
    @commands.is_owner()
    async def econconfig(self, ctx):
        await ctx.send(
            "ONYX owner-only economy settings:\n"
            "`,econconfig rewards daily <amount>`\n"
            "`,econconfig rewards weekly <amount>`\n"
            "`,econconfig rewards work <min> <max>`\n"
            "`,econconfig rewards beg <min> <max>`\n"
            "`,econconfig cooldown <daily|weekly|work|beg> <seconds>`\n"
            "`,econconfig bets <minimum> <maximum>`\n"
            "`,econconfig enabled <true|false>`"
        )

    @econconfig.command(name="rewards", hidden=True)
    @commands.is_owner()
    async def config_rewards(
        self, ctx, reward: str, minimum: int, maximum: int = None
    ):
        reward = reward.casefold()
        maximum = minimum if maximum is None else maximum
        if (
            reward not in {"daily", "weekly", "work", "beg"}
            or minimum < 0 or maximum < minimum or maximum > MAX_CREDITS
        ):
            return await ctx.send("Invalid reward settings.")
        async with self.bot.db.pool.acquire() as conn:
            if reward in {"daily", "weekly"}:
                if minimum != maximum:
                    return await ctx.send(
                        "Daily and weekly rewards use one fixed amount."
                    )
                await conn.execute(
                    f"""UPDATE onyx_economy_settings
                    SET {reward}_reward=$1, updated_by=$2,
                    updated_at=CURRENT_TIMESTAMP WHERE id=1""",
                    minimum, ctx.author.id,
                )
            else:
                await conn.execute(
                    f"""UPDATE onyx_economy_settings
                    SET {reward}_min=$1, {reward}_max=$2,
                    updated_by=$3, updated_at=CURRENT_TIMESTAMP WHERE id=1""",
                    minimum, maximum, ctx.author.id,
                )
        await ctx.send(f"✅ {reward.title()} reward updated.")

    @econconfig.command(name="cooldown", hidden=True)
    @commands.is_owner()
    async def config_cooldown(self, ctx, action: str, seconds: int):
        columns = {
            "daily": "daily_cooldown",
            "weekly": "weekly_cooldown",
            "work": "work_cooldown",
            "beg": "beg_cooldown",
        }
        action = action.casefold()
        if action not in columns or not 60 <= seconds <= 31_536_000:
            return await ctx.send(
                "Choose daily, weekly, work, or beg and a cooldown "
                "between 60 and 31,536,000 seconds."
            )
        async with self.bot.db.pool.acquire() as conn:
            await conn.execute(
                f"""UPDATE onyx_economy_settings SET {columns[action]}=$1,
                updated_by=$2, updated_at=CURRENT_TIMESTAMP WHERE id=1""",
                seconds, ctx.author.id,
            )
        await ctx.send(f"✅ {action.title()} cooldown updated.")

    @econconfig.command(name="bets", hidden=True)
    @commands.is_owner()
    async def config_bets(self, ctx, minimum: int, maximum: int):
        if minimum < 1 or maximum < minimum or maximum > MAX_CREDITS:
            return await ctx.send("Invalid betting limits.")
        async with self.bot.db.pool.acquire() as conn:
            await conn.execute("""
                UPDATE onyx_economy_settings
                SET min_bet=$1, max_bet=$2, updated_by=$3,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=1
            """, minimum, maximum, ctx.author.id)
        await ctx.send(
            f"✅ Betting limits set to {minimum:,}–{maximum:,} Credits."
        )

    @econconfig.command(name="enabled", hidden=True)
    @commands.is_owner()
    async def config_enabled(self, ctx, value: str):
        value = value.casefold()
        if value not in {"true", "false", "on", "off"}:
            return await ctx.send("Use true or false.")
        enabled = value in {"true", "on"}
        async with self.bot.db.pool.acquire() as conn:
            await conn.execute("""
                UPDATE onyx_economy_settings
                SET enabled=$1, updated_by=$2, updated_at=CURRENT_TIMESTAMP
                WHERE id=1
            """, enabled, ctx.author.id)
        await ctx.send(
            f"✅ Global ONYX Economy {'enabled' if enabled else 'disabled'}."
        )


async def setup(bot):
    await bot.add_cog(Economy(bot))
