"""Owner and approved-developer currency grant command for ONYX."""

import logging

import discord
from discord.ext import commands

from currency_system import ensure_currency_tables, grant_credits

log = logging.getLogger("onyx.economy_admin")

MAX_GRANT = 2_000_000_000

TOKEN_NAMES = {
    "token", "tokens", "prestige", "prestige_token",
    "prestige_tokens", "prestigetoken", "prestigetokens"
}

CREDIT_NAMES = {
    "credit", "credits", "onyx_credit", "onyx_credits",
    "onyxcredit", "onyxcredits"
}


class EconomyAdmin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_developers (
                user_id BIGINT PRIMARY KEY,
                appointed_by BIGINT NOT NULL,
                appointed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        if self.bot.db.backend == "postgres":
            await ensure_currency_tables(self.bot.db.pool)

    async def can_manage_currency(self, user):
        if self.bot.owner_id and user.id == self.bot.owner_id:
            return True

        try:
            row = await self.bot.db.fetchone(
                "SELECT 1 FROM onyx_developers WHERE user_id=?",
                (user.id,)
            )
            return row is not None
        except Exception:
            log.exception(
                "Could not verify currency grant permission for user %s",
                user.id
            )
            return False

    @commands.command(
        name="give",
        hidden=True,
        help="Grant Prestige Tokens or ONYX Credits to a member. Owner and approved developers only.",
        brief="Grant a member currency."
    )
    async def give_currency(
        self,
        ctx,
        member: discord.User,
        currency: str,
        amount: int
    ):
        """Usage: ,give <member> <currency> <amount>"""

        if not await self.can_manage_currency(ctx.author):
            return await ctx.send(
                "You don't have permission to grant ONYX currency."
            )

        if member.bot:
            return await ctx.send(
                "Currency cannot be granted to bot accounts."
            )

        if amount < 1 or amount > MAX_GRANT:
            return await ctx.send(
                f"Amount must be between 1 and {MAX_GRANT:,}."
            )

        currency_key = currency.strip().casefold().replace("-", "_")

        if currency_key in TOKEN_NAMES:
            await self.bot.db.execute("""
                INSERT INTO onyx_prestige_wallet (user_id, tokens)
                VALUES (?, ?)
                ON CONFLICT(user_id)
                DO UPDATE SET tokens =
                    onyx_prestige_wallet.tokens + excluded.tokens
            """, (member.id, amount))

            row = await self.bot.db.fetchone(
                "SELECT tokens FROM onyx_prestige_wallet WHERE user_id=?",
                (member.id,)
            )

            balance = int(row["tokens"]) if row else 0
            currency_label = "Prestige Tokens"
            balance_label = "Prestige Token balance"

        elif currency_key in CREDIT_NAMES:
            if self.bot.db.backend != "postgres":
                return await ctx.send(
                    "ONYX Credits grants require the PostgreSQL database."
                )

            async with self.bot.db.pool.acquire() as conn:
                async with conn.transaction():
                    result = await grant_credits(
                        conn,
                        member.id,
                        amount,
                        source="admin_grant",
                        description=(
                            f"Granted by ONYX staff member {ctx.author.id}"
                        )
                    )

                    if not result.get("ok"):
                        return await ctx.send(
                            "That Credit grant could not be completed."
                        )

                    balance = int(result["credits"])

            currency_label = "ONYX Credits"
            balance_label = "ONYX Credit balance"

        else:
            return await ctx.send(
                "Unknown currency. Use tokens or credits.\n"
                f"Example: {ctx.prefix}give @member tokens 500"
            )

        embed = discord.Embed(
            title="ONYX • Currency Granted",
            description=(
                f"Successfully granted {amount:,} {currency_label} "
                f"to {member.mention}."
            ),
            color=discord.Color.from_rgb(25, 190, 190)
        )

        embed.add_field(
            name=balance_label,
            value=f"{balance:,}",
            inline=True
        )

        embed.add_field(
            name="Granted by",
            value=ctx.author.mention,
            inline=True
        )

        embed.set_footer(text="ONYX Economy • Staff Transaction")

        await ctx.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions(users=True)
        )

        log.info(
            "Currency grant: actor=%s recipient=%s currency=%s amount=%s",
            ctx.author.id,
            member.id,
            currency_key,
            amount
        )


async def setup(bot):
    await bot.add_cog(EconomyAdmin(bot))
