"""ONYX global Credits economy and arcade games."""

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
    update_discord_user_profile,
)

from cogs.economy._common import (
    make_embed,
    money,
    pay_out,
    place_wager,
)

from cogs.economy.games._blackjack import BlackjackView
from cogs.economy.games._quick_games import QuickGameView
from cogs.economy.games._slots import SlotsView
from cogs.economy.games._mines import MinesView
from cogs.economy.games._roulette import RouletteView
from cogs.economy.games._manager import ArcadeManager
from cogs.economy.games._streak_views import StreakDecisionView
from cogs.economy.games._streaks import (
    ensure_streak_tables,
    create_streak,
    get_streak,
)
from cogs.economy.games._controls import ensure_arcade_control_tables
from cogs.economy.games._stats import (
    ensure_arcade_stats_tables,
    record_arcade_round,
)

COLOR = discord.Color.from_rgb(25, 190, 190)


async def ensure_economy_tables(pool):
    """Create the global economy tables."""

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
            VALUES (1)
            ON CONFLICT (id) DO NOTHING
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS onyx_economy_cooldowns (
                user_id BIGINT NOT NULL,
                action TEXT NOT NULL,
                next_claim_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (user_id, action)
            )
        """)


async def settings_for(bot):
    async with bot.db.pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM onyx_economy_settings WHERE id=1"
        )


async def claim_reward(
    bot,
    user_id,
    action,
    amount,
    cooldown,
    display_name=None,
    username=None,
):
    """Claim a bot reward and refresh the user's global Discord name."""

    async with bot.db.pool.acquire() as conn:
        async with conn.transaction():

            await update_discord_user_profile(
                conn,
                user_id,
                display_name=display_name,
                username=username,
            )

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


class Economy(commands.Cog):
    """Global ONYX Credits, rewards, transfers, and arcade games."""

    def __init__(self, bot):
        self.bot = bot
        self.arcade = ArcadeManager(bot)

    async def cog_load(self):
        if self.bot.db.backend != "postgres":
            return

        await ensure_economy_tables(self.bot.db.pool)
        await ensure_streak_tables(self.bot.db.pool)
        await ensure_arcade_control_tables(self.bot.db.pool)
        await ensure_arcade_stats_tables(self.bot.db.pool)

    async def available(self, ctx):
        if self.bot.db.backend != "postgres":
            await ctx.send(
                "ONYX Credits require the PostgreSQL database. "
                "Your existing Prestige Tokens are unaffected."
            )
            return False

        settings = await settings_for(self.bot)

        if not settings or not settings["enabled"]:
            await ctx.send(
                "The global ONYX economy is currently disabled."
            )
            return False

        return True

    async def record_blackjack_stats(
        self,
        reference,
        user_id,
        wager,
        outcome,
        payout=0,
    ):
        """Record an immediately settled opening Blackjack result."""

        try:
            await record_arcade_round(
                self.bot.db.pool,
                reference=reference,
                user_id=user_id,
                game="blackjack",
                wager=wager,
                outcome=outcome,
                payout=payout,
            )
        except Exception:
            # Stats must never interfere with a settled wallet transaction.
            return False

        return True

    async def begin_game(self, ctx, amount, source):
        """Resolve a numeric, half, or all wager and place the bet."""

        if not await self.available(ctx):
            return None

        active = await get_streak(self.bot, ctx.author.id)

        if active:
            if active["status"] == "playing":
                await ctx.send(
                    "🔥 You already have a streak round in progress. "
                    "Finish that game before starting another."
                )
            else:
                await ctx.send(
                    "🔥 You have an active arcade streak. "
                    "Use `,streak` to cash out or continue it first."
                )
            return None

        amount_text = str(amount).strip().casefold()

        if amount_text in {"half", "all"}:
            async with self.bot.db.pool.acquire() as conn:
                wallet = await get_credit_balance(
                    conn,
                    ctx.author.id,
                )

            balance = int(wallet["credits"])

            if amount_text == "half":
                amount = balance // 2
            else:
                amount = balance

            if amount < 1:
                await ctx.send(
                    "You don't have enough Credits for that wager."
                )
                return None

        else:
            try:
                amount = int(amount_text)
            except (TypeError, ValueError):
                await ctx.send(
                    "Enter a number, `half`, or `all` for your wager."
                )
                return None

        result = await place_wager(
            self.bot,
            ctx.author.id,
            amount,
            source,
        )

        if not result.get("ok"):
            await ctx.send(
                result.get("error", "Unable to place that wager.")
            )
            return None

        return uuid.uuid4().hex, amount

    # ---------------------------------------------------------
    # WALLET
    # ---------------------------------------------------------

    @commands.command(
        name="balance",
        aliases=["bal", "credits"],
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
        em.set_footer(
            text="One global wallet shared across every ONYX server"
        )

        await ctx.send(embed=em)

    @commands.command(
        name="pay",
        help="Transfer Credits to another member.",
    )
    async def pay(self, ctx, member: discord.User, amount: int):
        if not await self.available(ctx):
            return

        if member.bot or member.id == ctx.author.id:
            return await ctx.send(
                "You can only pay another human member."
            )

        if amount < 1 or amount > MAX_CREDITS:
            return await ctx.send(
                "Enter a valid positive Credit amount."
            )

        async with self.bot.db.pool.acquire() as conn:
            async with conn.transaction():
                sent = await spend_credits(
                    conn,
                    ctx.author.id,
                    amount,
                    "member_transfer",
                    f"Transfer to {member.id}",
                )

                if not sent.get("ok"):
                    return await ctx.send(
                        "Not enough Credits. Your balance is "
                        f"{money(sent.get('credits', 0))}."
                    )

                received = await grant_credits(
                    conn,
                    member.id,
                    amount,
                    "member_transfer",
                    f"Transfer from {ctx.author.id}",
                    reference_id=f"transfer:{uuid.uuid4().hex}",
                )

                if not received.get("ok"):
                    raise RuntimeError(
                        "Recipient wallet transfer failed."
                    )

                await update_discord_user_profile(
                    conn,
                    ctx.author.id,
                    display_name=(
                        ctx.author.global_name or ctx.author.name
                    ),
                    username=ctx.author.name,
                )

                await update_discord_user_profile(
                    conn,
                    member.id,
                    display_name=(
                        member.global_name or member.name
                    ),
                    username=member.name,
                )

        await ctx.send(
            embed=make_embed(
                "💸 Credits Transferred",
                f"{ctx.author.mention} sent **{money(amount)}** "
                f"to {member.mention}.",
            )
        )

    # ---------------------------------------------------------
    # REWARDS
    # ---------------------------------------------------------

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
                int(config["work_min"]),
                int(config["work_max"]),
            )
        else:
            amount = random.randint(
                int(config["beg_min"]),
                int(config["beg_max"]),
            )
            if random.random() < 0.35:
                amount = 0

        cooldown = int(config[f"{action}_cooldown"])

        success, value = await claim_reward(
            self.bot,
            ctx.author.id,
            action,
            amount,
            cooldown,
            display_name=(
                ctx.author.global_name or ctx.author.name
            ),
            username=ctx.author.name,
        )

        if not success:
            seconds = max(
                1,
                int(
                    (
                        value - datetime.now(timezone.utc)
                    ).total_seconds()
                ),
            )

            hours, remainder = divmod(seconds, 3600)
            minutes = remainder // 60

            return await ctx.send(
                f"⏳ You already claimed **{action}**. "
                f"Try again in **{hours}h {minutes}m**."
            )

        if amount:
            title = f"💰 ONYX {action.title()}"
            message = (
                f"{ctx.author.mention}, you received "
                f"**{money(amount)}**!"
            )
        else:
            title = "🪙 No luck this time"
            message = (
                "Nobody had any spare Credits to give you. "
                "Try again later."
            )

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

    # ---------------------------------------------------------
    # ECONOMY INFORMATION
    # ---------------------------------------------------------

    @commands.group(
        name="economy",
        invoke_without_command=True,
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
        em.add_field(
            name="Daily",
            value=money(config["daily_reward"]),
        )
        em.add_field(
            name="Weekly",
            value=money(config["weekly_reward"]),
        )
        em.add_field(
            name="Bet limits",
            value=(
                f"{config['min_bet']:,}–"
                f"{config['max_bet']:,}"
            ),
        )
        em.set_footer(
            text="Credits are global across every ONYX server."
        )

        await ctx.send(embed=em)

    @economy.command(
        name="leaderboard",
        aliases=["top", "lb"],
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
            return await ctx.send(
                "No ONYX wallets have been created yet."
            )

        lines = []

        for index, row in enumerate(rows, 1):
            user = self.bot.get_user(int(row["user_id"]))

            name = (
                discord.utils.escape_markdown(user.display_name)
                if user
                else f"User {row['user_id']}"
            )

            lines.append(
                f"**{index}.** {name} — {money(row['credits'])}"
            )

        await ctx.send(
            embed=make_embed(
                "🏆 ONYX Global Credits Leaderboard",
                "\n".join(lines),
            )
        )

    # ---------------------------------------------------------
    # ARCADE STREAK RECOVERY
    # ---------------------------------------------------------

    @commands.command(
        name="streak",
        help="View, continue, or cash out your active arcade streak.",
    )
    async def streak(self, ctx):
        if not await self.available(ctx):
            return

        current = await self.arcade.get_player_streak(ctx.author.id)

        if not current:
            return await ctx.send(
                "You don't have an active ONYX arcade streak."
            )

        if current["status"] == "playing":
            return await ctx.send(
                "🔥 Your streak is currently marked as playing. "
                "Finish that game first. If the game disappeared "
                "after a bot restart, contact an ONYX administrator "
                "before starting another round."
            )

        view = StreakDecisionView(
            bot=self.bot,
            user_id=ctx.author.id,
            streak=current,
            launch_game=self.arcade.launch_streak_game,
        )

        await ctx.send(
            embed=await view.decision_embed(),
            view=view,
        )

    # ---------------------------------------------------------
    # ARCADE GAMES
    # ---------------------------------------------------------

    @commands.command(
        name="betflip",
        help="Bet on heads or tails. Usage: ,betflip <amount|half|all>",
    )
    async def betflip(self, ctx, amount: str):
        game_result = await self.begin_game(
            ctx,
            amount,
            "betflip_wager",
        )
        if not game_result:
            return

        reference, amount = game_result

        view = QuickGameView(
            self.bot,
            ctx.author.id,
            amount,
            "betflip",
            reference,
            result_handler=self.arcade.result_handler,
        )

        await ctx.send(
            embed=make_embed(
                "🪙 ONYX BETFLIP",
                f"**Wager:** {money(amount)}\n\n"
                "Choose Heads or Tails.",
            ),
            view=view,
        )

    @commands.command(
        name="dice",
        help="Bet high or low. Usage: ,dice <amount|half|all>",
    )
    async def dice(self, ctx, amount: str):
        game_result = await self.begin_game(
            ctx,
            amount,
            "dice_wager",
        )
        if not game_result:
            return

        reference, amount = game_result

        view = QuickGameView(
            self.bot,
            ctx.author.id,
            amount,
            "dice",
            reference,
            result_handler=self.arcade.result_handler,
        )

        await ctx.send(
            embed=make_embed(
                "🎲 ONYX DICE",
                f"**Wager:** {money(amount)}\n\n"
                "Choose Low (1–3) or High (4–6).",
            ),
            view=view,
        )

    @commands.command(
        name="slots",
        help="Play the ONYX slot machine. Usage: ,slots <amount|half|all>",
    )
    async def slots(self, ctx, amount: str):
        game_result = await self.begin_game(
            ctx,
            amount,
            "slots_wager",
        )
        if not game_result:
            return

        reference, amount = game_result

        view = SlotsView(
            self.bot,
            ctx.author.id,
            amount,
            reference,
            result_handler=self.arcade.result_handler,
        )

        await ctx.send(
            embed=view.slot_embed(
                ["❔", "❔", "❔"],
                f"**Wager:** {money(amount)}\nPress Spin to play.",
            ),
            view=view,
        )

    @commands.command(
        name="mines",
        help="Play ONYX Mines. Usage: ,mines <amount|half|all> [mine_count]",
    )
    async def mines(self, ctx, amount: str, mine_count: int = 3):
        if not 1 <= mine_count <= 19:
            return await ctx.send(
                "Choose between 1 and 19 mines."
            )

        game_result = await self.begin_game(
            ctx,
            amount,
            "mines_wager",
        )
        if not game_result:
            return

        reference, amount = game_result

        view = MinesView(
            self.bot,
            ctx.author.id,
            amount,
            reference,
            mines=mine_count,
            result_handler=self.arcade.result_handler,
        )

        await ctx.send(
            embed=view.current_embed(
                "Pick a tile. Cash out whenever you want after a safe pick."
            ),
            view=view,
        )

    @commands.command(
        name="roulette",
        aliases=["rl"],
        help="Play ONYX Roulette. Usage: ,roulette <amount|half|all>",
    )
    async def roulette(self, ctx, amount: str):
        game_result = await self.begin_game(
            ctx,
            amount,
            "roulette_wager",
        )
        if not game_result:
            return

        reference, amount = game_result

        view = RouletteView(
            self.bot,
            ctx.author.id,
            amount,
            reference,
            result_handler=self.arcade.result_handler,
        )

        await ctx.send(
            embed=view.current_embed(
                "Choose your bet, then spin the wheel!"
            ),
            view=view,
        )

    @commands.command(
        name="blackjack",
        aliases=["bj"],
        help="Play blackjack. Usage: ,blackjack <amount|half|all>",
    )
    async def blackjack(self, ctx, amount: str):
        game_result = await self.begin_game(
            ctx,
            amount,
            "blackjack_wager",
        )
        if not game_result:
            return

        reference, amount = game_result

        draw = BlackjackView.draw
        player = [draw(), draw()]
        dealer = [draw(), draw()]

        view = BlackjackView(
            self.bot,
            ctx.author.id,
            amount,
            reference,
            player,
            dealer,
            result_handler=self.arcade.result_handler,
        )

        player_total = view.total(player)
        dealer_total = view.total(dealer)

        # Natural blackjack is settled immediately.
        if player_total == 21:
            view.finished = True
            view.disable_controls()

            if dealer_total == 21:
                paid = await pay_out(
                    self.bot,
                    ctx.author.id,
                    amount,
                    "blackjack_push",
                    reference,
                )

                if paid.get("ok"):
                    await self.record_blackjack_stats(
                        reference,
                        ctx.author.id,
                        amount,
                        "push",
                        amount,
                    )

                result = (
                    "🤝 Both you and the dealer have blackjack. "
                    "Your wager was returned."
                    if paid.get("ok")
                    else "⚠️ Your wager return needs administrator review."
                )

                return await ctx.send(
                    embed=view.display(
                        reveal=True,
                        result=result,
                    ),
                    view=view,
                )

            natural_payout = int(amount * 2.5)

            created = await create_streak(
                self.bot,
                ctx.author.id,
                natural_payout,
                "blackjack",
                reference=reference,
            )

            if created.get("ok"):
                await self.record_blackjack_stats(
                    reference,
                    ctx.author.id,
                    amount,
                    "win",
                    natural_payout,
                )

                streak_view = StreakDecisionView(
                    bot=self.bot,
                    user_id=ctx.author.id,
                    streak=created["streak"],
                    launch_game=self.arcade.launch_streak_game,
                )

                decision_embed = await streak_view.decision_embed()

                embed = view.display(
                    reveal=True,
                    result=(
                        f"🌟 **Natural Blackjack!** "
                        f"You won **{money(natural_payout)}**."
                    ),
                )
                embed.description += (
                    "\n\n━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{decision_embed.description}"
                )

                return await ctx.send(
                    embed=embed,
                    view=streak_view,
                )

            paid = await pay_out(
                self.bot,
                ctx.author.id,
                natural_payout,
                "blackjack_natural",
                reference,
            )

            if paid.get("ok"):
                await self.record_blackjack_stats(
                    reference,
                    ctx.author.id,
                    amount,
                    "win",
                    natural_payout,
                )

            result = (
                f"🌟 Natural Blackjack! "
                f"You received {money(natural_payout)}."
                if paid.get("ok")
                else "⚠️ Your natural blackjack payout needs administrator review."
            )

            return await ctx.send(
                embed=view.display(reveal=True, result=result),
                view=view,
            )

        if dealer_total == 21:
            view.finished = True
            view.disable_controls()

            await self.record_blackjack_stats(
                reference,
                ctx.author.id,
                amount,
                "loss",
                0,
            )

            return await ctx.send(
                embed=view.display(
                    reveal=True,
                    result=(
                        f"Dealer has blackjack. "
                        f"You lost {money(amount)}."
                    ),
                ),
                view=view,
            )

        await ctx.send(
            embed=view.display(),
            view=view,
        )

    # ---------------------------------------------------------
    # OWNER ECONOMY CONFIGURATION
    # ---------------------------------------------------------

    @commands.group(
        name="econconfig",
        invoke_without_command=True,
        hidden=True,
    )
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
        self,
        ctx,
        reward: str,
        minimum: int,
        maximum: int = None,
    ):
        reward = reward.casefold()
        maximum = minimum if maximum is None else maximum

        if (
            reward not in {"daily", "weekly", "work", "beg"}
            or minimum < 0
            or maximum < minimum
            or maximum > MAX_CREDITS
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
                    minimum,
                    ctx.author.id,
                )
            else:
                await conn.execute(
                    f"""UPDATE onyx_economy_settings
                    SET {reward}_min=$1, {reward}_max=$2,
                    updated_by=$3, updated_at=CURRENT_TIMESTAMP WHERE id=1""",
                    minimum,
                    maximum,
                    ctx.author.id,
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
                f"""UPDATE onyx_economy_settings
                SET {columns[action]}=$1, updated_by=$2,
                updated_at=CURRENT_TIMESTAMP WHERE id=1""",
                seconds,
                ctx.author.id,
            )

        await ctx.send(f"✅ {action.title()} cooldown updated.")

    @econconfig.command(name="bets", hidden=True)
    @commands.is_owner()
    async def config_bets(self, ctx, minimum: int, maximum: int):
        if (
            minimum < 1
            or maximum < minimum
            or maximum > MAX_CREDITS
        ):
            return await ctx.send("Invalid betting limits.")

        async with self.bot.db.pool.acquire() as conn:
            await conn.execute("""
                UPDATE onyx_economy_settings
                SET min_bet=$1, max_bet=$2, updated_by=$3,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=1
            """, minimum, maximum, ctx.author.id)

        await ctx.send(
            f"✅ Betting limits set to "
            f"{minimum:,}–{maximum:,} Credits."
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
                SET enabled=$1, updated_by=$2,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=1
            """, enabled, ctx.author.id)

        await ctx.send(
            f"✅ Global ONYX Economy "
            f"{'enabled' if enabled else 'disabled'}."
        )


async def setup(bot):
    await bot.add_cog(Economy(bot))
