"""ONYX Prestige Shop cog.

Load this extension/cog alongside Levels. It uses the same bot.db wrapper and
SQLite/PostgreSQL-compatible SQL style as cogs/levels.py.

Commands:
  ,pshop
  ,pbuy <item>
  ,pinventory
  ,pequip <frame|theme|emblem|effect|title> <item>
  ,punequip <frame|theme|emblem|effect|title>
"""
import asyncio
import re

import discord
from discord.ext import commands


SHOP = {
    "frame": {
        "steel": ("Steel Frame", 5, "A clean metallic border."),
        "neon": ("Neon Frame", 10, "A bright ONYX-style neon edge."),
        "elite": ("Elite Frame", 15, "A refined gold-accented frame."),
        "obsidian": ("Obsidian Frame", 20, "A dark, premium frame."),
        "legendary": ("Legendary Frame", 25, "The highest-tier frame."),
    },
    "theme": {
        "frost": ("Frost Theme", 5, "Cool blue and ice tones."),
        "inferno": ("Inferno Theme", 5, "Fiery red and orange tones."),
        "toxic": ("Toxic Theme", 10, "Bright green highlights."),
        "eclipse": ("Eclipse Theme", 15, "Purple eclipse styling."),
        "void": ("Void Theme", 20, "Deep-space purple styling."),
    },
    "emblem": {
        "veteran": ("Veteran Emblem", 5, "A Prestige Master Veteran emblem."),
        "elite": ("Elite Emblem", 10, "An Elite emblem."),
        "champion": ("Champion Emblem", 15, "A Champion emblem."),
        "warlord": ("Warlord Emblem", 20, "A Warlord emblem."),
        "mythic": ("Mythic Emblem", 25, "A Mythic emblem."),
    },
    "effect": {
        "teal_glow": ("Teal Glow", 10, "A teal glow around your card."),
        "silver_shine": ("Silver Shine", 15, "A silver highlight effect."),
        "electric_pulse": ("Electric Pulse", 20, "An electric blue effect."),
        "cosmic_aura": ("Cosmic Aura", 25, "A cosmic purple aura."),
    },
}

DEFAULTS = {
    "frame": "default",
    "theme": "onyx",
    "emblem": "default",
    "effect": "none",
    "title": None,
}
COLUMN_BY_CATEGORY = {
    "frame": "frame_id",
    "theme": "theme_id",
    "emblem": "emblem_id",
    "effect": "effect_id",
    "title": "title_id",
}
CATEGORY_ALIASES = {
    "frames": "frame", "background": "theme", "backgrounds": "theme",
    "themes": "theme", "emblems": "emblem", "effects": "effect",
    "titles": "title",
}


def slugify(value: str) -> str:
    value = value.casefold().strip().replace("-", "_")
    value = re.sub(r"[^a-z0-9_ ]", "", value)
    return re.sub(r"\s+", "_", value)


def display_item(category: str, item_id: str) -> str:
    if category in SHOP and item_id in SHOP[category]:
        return SHOP[category][item_id][0]
    return str(item_id).replace("_", " ").title()


class PrestigeShop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._purchase_lock = asyncio.Lock()

    async def cog_load(self):
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_prestige_owned (
                user_id BIGINT NOT NULL,
                category TEXT NOT NULL,
                item_id TEXT NOT NULL,
                purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, category, item_id)
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_profile_equipped (
                user_id BIGINT PRIMARY KEY,
                frame_id TEXT NOT NULL DEFAULT 'default',
                theme_id TEXT NOT NULL DEFAULT 'onyx',
                emblem_id TEXT NOT NULL DEFAULT 'default',
                effect_id TEXT NOT NULL DEFAULT 'none',
                title_id TEXT
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_prestige_wallet (
                user_id BIGINT PRIMARY KEY,
                tokens INTEGER NOT NULL DEFAULT 0
            )
        """)

    async def _wallet(self, user_id: int) -> int:
        await self.bot.db.execute(
            "INSERT INTO onyx_prestige_wallet (user_id,tokens) VALUES (?,0) "
            "ON CONFLICT(user_id) DO NOTHING",
            (user_id,),
        )
        row = await self.bot.db.fetchone(
            "SELECT tokens FROM onyx_prestige_wallet WHERE user_id=?",
            (user_id,),
        )
        return int(row["tokens"]) if row else 0

    async def _owned(self, user_id: int):
        rows = await self.bot.db.fetchall(
            "SELECT category,item_id FROM onyx_prestige_owned "
            "WHERE user_id=? ORDER BY category,item_id",
            (user_id,),
        )
        return {(str(r["category"]), str(r["item_id"])) for r in rows}

    async def _equipped(self, user_id: int):
        await self.bot.db.execute(
            "INSERT INTO onyx_profile_equipped (user_id) VALUES (?) "
            "ON CONFLICT(user_id) DO NOTHING",
            (user_id,),
        )
        row = await self.bot.db.fetchone(
            "SELECT * FROM onyx_profile_equipped WHERE user_id=?",
            (user_id,),
        )
        return dict(row) if row else {}

    def _levels_cog(self):
        return self.bot.get_cog("Levels")

    @commands.command(name="pshop", aliases=["prestigeshop"])
    @commands.guild_only()
    async def pshop(self, ctx):
        embed = discord.Embed(
            title="ONYX • Prestige Shop",
            description=(
                "Spend Prestige Tokens on permanent profile-card cosmetics.\n"
                "Use `,pbuy <item>` to purchase an item."
            ),
            color=discord.Color.from_rgb(25, 190, 190),
        )
        for category, items in SHOP.items():
            lines = [
                f"**{name}** — `{cost} tokens`\n"
                f"`{item_id}` • {description}"
                for item_id, (name, cost, description) in items.items()
            ]
            embed.add_field(
                name=category.title() + "s",
                value="\n".join(lines),
                inline=False,
            )
        tokens = await self._wallet(ctx.author.id)
        embed.set_footer(text=f"Your balance: {tokens} Prestige Tokens")
        await ctx.send(embed=embed)

    @commands.command(name="pbuy", aliases=["prestigebuy"])
    @commands.guild_only()
    async def pbuy(self, ctx, *, item: str):
        wanted = slugify(item)
        match = None
        for category, items in SHOP.items():
            if wanted in items:
                match = (category, wanted, *items[wanted])
                break
            for item_id, (name, cost, description) in items.items():
                if slugify(name) == wanted:
                    match = (category, item_id, name, cost, description)
                    break
            if match:
                break
        if not match:
            return await ctx.send(
                "I couldn't find that item. Use `,pshop` to see the catalog "
                "and item IDs."
            )

        category, item_id, name, cost, _description = match
        async with self._purchase_lock:
            owned = await self._owned(ctx.author.id)
            if (category, item_id) in owned:
                return await ctx.send(f"You already own **{name}**.")
            balance = await self._wallet(ctx.author.id)
            if balance < cost:
                return await ctx.send(
                    f"**{name}** costs {cost} tokens, but you have {balance}."
                )

            # Atomic balance check prevents spending below zero.
            await self.bot.db.execute(
                "UPDATE onyx_prestige_wallet SET tokens=tokens-? "
                "WHERE user_id=? AND tokens>=?",
                (cost, ctx.author.id, cost),
            )
            new_balance = await self._wallet(ctx.author.id)
            if new_balance != balance - cost:
                return await ctx.send(
                    "Your token balance changed before the purchase completed. "
                    "Please try again."
                )
            await self.bot.db.execute(
                "INSERT INTO onyx_prestige_owned (user_id,category,item_id) "
                "VALUES (?,?,?) ON CONFLICT(user_id,category,item_id) DO NOTHING",
                (ctx.author.id, category, item_id),
            )

        await ctx.send(
            f"Purchase complete! You unlocked **{name}** for {cost} tokens. "
            f"Balance: **{new_balance}** tokens.\n"
            f"Equip it with `,pequip {category} {item_id}`."
        )

    @commands.command(name="pinventory", aliases=["prestigeinventory"])
    @commands.guild_only()
    async def pinventory(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        owned = await self._owned(member.id)
        balance = await self._wallet(member.id)
        equipped = await self._equipped(member.id)
        embed = discord.Embed(
            title=f"{member.display_name} • Prestige Inventory",
            description=f"**Prestige Tokens:** {balance}",
            color=discord.Color.from_rgb(25, 190, 190),
        )
        for category in SHOP:
            items = [
                display_item(category, item_id)
                for owned_category, item_id in sorted(owned)
                if owned_category == category
            ]
            column = COLUMN_BY_CATEGORY[category]
            current = equipped.get(column) or DEFAULTS[category]
            current_name = (
                "Default" if current == DEFAULTS[category]
                else display_item(category, current)
            )
            embed.add_field(
                name=f"{category.title()}s • Equipped: {current_name}",
                value="\n".join(items) if items else "Nothing unlocked yet.",
                inline=False,
            )
        levels = self._levels_cog()
        if levels:
            row = await levels.profile(member.id)
            titles = levels.unlocked_titles(row)
            active_title = equipped.get("title_id") or (titles[-1] if titles else None)
            embed.add_field(
                name="Earned Titles",
                value=", ".join(titles) if titles else "No Prestige Master titles yet.",
                inline=False,
            )
            embed.add_field(
                name="Equipped Title",
                value=active_title or "No title",
                inline=False,
            )
        await ctx.send(embed=embed)

    @commands.command(name="pequip", aliases=["prestigeequip"])
    @commands.guild_only()
    async def pequip(self, ctx, category: str, *, item: str):
        category = CATEGORY_ALIASES.get(category.casefold(), category.casefold())
        if category not in COLUMN_BY_CATEGORY:
            return await ctx.send(
                "Choose a category: `frame`, `theme`, `emblem`, `effect`, or `title`."
            )
        item_id = slugify(item)
        column = COLUMN_BY_CATEGORY[category]

        if category == "title":
            levels = self._levels_cog()
            if not levels:
                return await ctx.send("The Levels cog must be loaded to equip titles.")
            row = await levels.profile(ctx.author.id)
            titles = levels.unlocked_titles(row)
            title_lookup = {slugify(title): title for title in titles}
            if item_id not in title_lookup:
                return await ctx.send(
                    "You haven't unlocked that title yet. Prestige Master titles "
                    "are earned through progression, not purchased."
                )
            stored_value = title_lookup[item_id]
        else:
            if item_id not in SHOP[category]:
                return await ctx.send(
                    f"That {category} isn't in the shop. Use `,pshop` to browse."
                )
            owned = await self._owned(ctx.author.id)
            if (category, item_id) not in owned:
                return await ctx.send(
                    f"You don't own **{display_item(category, item_id)}** yet. "
                    "Use `,pbuy` to unlock it."
                )
            stored_value = item_id

        await self._equipped(ctx.author.id)
        await self.bot.db.execute(
            f"UPDATE onyx_profile_equipped SET {column}=? WHERE user_id=?",
            (stored_value, ctx.author.id),
        )
        await ctx.send(
            f"Equipped **{display_item(category, stored_value)}**. "
            "Your next `,rank` card will use it."
        )

    @commands.command(name="punequip", aliases=["prestigeunequip"])
    @commands.guild_only()
    async def punequip(self, ctx, category: str):
        category = CATEGORY_ALIASES.get(category.casefold(), category.casefold())
        if category not in COLUMN_BY_CATEGORY:
            return await ctx.send(
                "Choose a category: `frame`, `theme`, `emblem`, `effect`, or `title`."
            )
        await self._equipped(ctx.author.id)
        await self.bot.db.execute(
            f"UPDATE onyx_profile_equipped SET {COLUMN_BY_CATEGORY[category]}=? "
            "WHERE user_id=?",
            (DEFAULTS[category], ctx.author.id),
        )
        await ctx.send(f"Reset your equipped {category} to its default.")


async def setup(bot):
    await bot.add_cog(PrestigeShop(bot))
