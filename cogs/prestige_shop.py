"""ONYX Prestige Shop — interactive Discord shop.

Commands:
  ,shop / ,pshop       Open the interactive Prestige Shop
  ,pinventory          View owned cosmetics and equipped items
  ,pequip <category> <item>   Equip an owned cosmetic or earned title
  ,punequip <category>        Reset a cosmetic slot
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
CATEGORY_LABELS = {
    "frame": "🖼️ Frames",
    "theme": "🎨 Themes",
    "emblem": "🏅 Emblems",
    "effect": "✨ Effects",
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

    async def _earned_titles(self, user_id: int):
        levels = self._levels_cog()
        if not levels:
            return []
        row = await levels.profile(user_id)
        return await levels.sync_unlocked_titles(user_id, row)

    async def _purchase(self, user_id: int, category: str, item_id: str):
        """Return (success, message, new_balance)."""
        name, cost, _description = SHOP[category][item_id]
        async with self._purchase_lock:
            owned = await self._owned(user_id)
            if (category, item_id) in owned:
                return False, f"You already own **{name}**.", await self._wallet(user_id)

            balance = await self._wallet(user_id)
            if balance < cost:
                return (
                    False,
                    f"You need **{cost} tokens** for {name}, but your balance is **{balance}**.",
                    balance,
                )

            await self.bot.db.execute(
                "UPDATE onyx_prestige_wallet SET tokens=tokens-? "
                "WHERE user_id=? AND tokens>=?",
                (cost, user_id, cost),
            )
            after = await self._wallet(user_id)
            if after != balance - cost:
                return (
                    False,
                    "Your balance changed during that purchase. Please try again.",
                    after,
                )

            await self.bot.db.execute(
                "INSERT INTO onyx_prestige_owned (user_id,category,item_id) "
                "VALUES (?,?,?) ON CONFLICT(user_id,category,item_id) DO NOTHING",
                (user_id, category, item_id),
            )
            return True, f"You unlocked **{name}**!", after

    def _shop_embed(self, balance: int, category: str = "frame",
                    selected: str | None = None, owned=None):
        owned = owned or set()
        embed = discord.Embed(
            title="ONYX  /  PRESTIGE SHOP",
            description=(
                "Use your Prestige Tokens to customize your global profile card.\n"
                "Choose a category, select an item, and preview its details here."
            ),
            color=discord.Color.from_rgb(25, 190, 190),
        )
        embed.add_field(name="YOUR BALANCE", value=f"**{balance}** Prestige Tokens", inline=False)

        if selected and selected in SHOP.get(category, {}):
            name, cost, description = SHOP[category][selected]
            is_owned = (category, selected) in owned
            status = "✅ Owned" if is_owned else (
                "🟢 Affordable" if balance >= cost else "🔒 Not enough tokens"
            )
            embed.add_field(
                name=f"SELECTED ITEM  /  {name}",
                value=f"{description}\n\n**Price:** {cost} tokens\n**Status:** {status}",
                inline=False,
            )
        else:
            embed.add_field(
                name="HOW TO SHOP",
                value="1. Pick a category below.\n2. Select an item.\n3. Press **Buy Item** to unlock it permanently.",
                inline=False,
            )

        lines = []
        for item_id, (name, cost, _desc) in SHOP[category].items():
            mark = " ✓" if (category, item_id) in owned else ""
            lines.append(f"`{cost:>2}` • **{name}**{mark}")
        embed.add_field(name=f"{category.upper()} CATALOG", value="\n".join(lines), inline=False)
        embed.set_footer(text="Purchases are permanent • Titles are earned through progression")
        return embed

    @commands.command(name="shop", aliases=["pshop", "prestigeshop"])
    @commands.guild_only()
    async def shop(self, ctx):
        balance = await self._wallet(ctx.author.id)
        owned = await self._owned(ctx.author.id)
        view = ShopView(self, ctx.author.id, balance, owned)
        await ctx.send(embed=self._shop_embed(balance, owned=owned), view=view)

    @commands.command(name="pinventory", aliases=["prestigeinventory", "inventory"])
    @commands.guild_only()
    async def pinventory(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        owned = await self._owned(member.id)
        balance = await self._wallet(member.id)
        equipped = await self._equipped(member.id)

        embed = discord.Embed(
            title=f"{member.display_name}  /  PRESTIGE INVENTORY",
            description=f"**Prestige Tokens:** {balance}",
            color=discord.Color.from_rgb(25, 190, 190),
        )
        for category in SHOP:
            items = [
                display_item(category, item_id)
                for owned_category, item_id in sorted(owned)
                if owned_category == category
            ]
            current = equipped.get(COLUMN_BY_CATEGORY[category]) or DEFAULTS[category]
            current_name = "Default" if current == DEFAULTS[category] else display_item(category, current)
            embed.add_field(
                name=f"{category.title()}s  •  Equipped: {current_name}",
                value="\n".join(items) if items else "Nothing unlocked yet.",
                inline=False,
            )

        titles = await self._earned_titles(member.id)
        active_title = equipped.get("title_id") or (titles[-1] if titles else None)
        embed.add_field(
            name="Earned Titles",
            value=", ".join(titles) if titles else "No Prestige Master titles yet.",
            inline=False,
        )
        embed.add_field(name="Equipped Title", value=active_title or "No title", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="pequip", aliases=["prestigeequip"])
    @commands.guild_only()
    async def pequip(self, ctx, category: str, *, item: str):
        category = CATEGORY_ALIASES.get(category.casefold(), category.casefold())
        if category not in COLUMN_BY_CATEGORY:
            return await ctx.send("Choose: `frame`, `theme`, `emblem`, `effect`, or `title`.")
        item_id = slugify(item)

        if category == "title":
            titles = await self._earned_titles(ctx.author.id)
            title_lookup = {slugify(title): title for title in titles}
            if item_id not in title_lookup:
                return await ctx.send(
                    "You haven't unlocked that title. Titles are earned through Prestige Master progression."
                )
            stored_value = title_lookup[item_id]
        else:
            if item_id not in SHOP[category]:
                return await ctx.send(f"That {category} isn't in the shop.")
            if (category, item_id) not in await self._owned(ctx.author.id):
                return await ctx.send(
                    f"You don't own **{display_item(category, item_id)}** yet. Open `,shop` to browse."
                )
            stored_value = item_id

        await self._equipped(ctx.author.id)
        await self.bot.db.execute(
            f"UPDATE onyx_profile_equipped SET {COLUMN_BY_CATEGORY[category]}=? WHERE user_id=?",
            (stored_value, ctx.author.id),
        )
        await ctx.send(f"✅ Equipped **{display_item(category, stored_value)}**.")

    @commands.command(name="punequip", aliases=["prestigeunequip"])
    @commands.guild_only()
    async def punequip(self, ctx, category: str):
        category = CATEGORY_ALIASES.get(category.casefold(), category.casefold())
        if category not in COLUMN_BY_CATEGORY:
            return await ctx.send("Choose: `frame`, `theme`, `emblem`, `effect`, or `title`.")
        await self._equipped(ctx.author.id)
        await self.bot.db.execute(
            f"UPDATE onyx_profile_equipped SET {COLUMN_BY_CATEGORY[category]}=? WHERE user_id=?",
            (DEFAULTS[category], ctx.author.id),
        )
        await ctx.send(f"Your equipped {category} has been reset.")


class ShopView(discord.ui.View):
    def __init__(self, cog: PrestigeShop, user_id: int, balance: int, owned):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        self.balance = balance
        self.owned = owned
        self.category = "frame"
        self.selected = None
        self.add_item(CategorySelect(self))
        self.add_item(ItemSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This shop belongs to someone else. Run `,shop` to open your own.",
                ephemeral=True,
            )
            return False
        return True

    async def refresh(self, interaction: discord.Interaction):
        self.balance = await self.cog._wallet(self.user_id)
        self.owned = await self.cog._owned(self.user_id)
        await interaction.response.edit_message(
            embed=self.cog._shop_embed(self.balance, self.category, self.selected, self.owned),
            view=self,
        )

    @discord.ui.button(label="Buy Item", style=discord.ButtonStyle.success, emoji="🛒", row=2)
    async def buy_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected:
            return await interaction.response.send_message(
                "Select an item first.", ephemeral=True
            )
        if (self.category, self.selected) in self.owned:
            return await interaction.response.send_message(
                "You already own this item.", ephemeral=True
            )
        success, message, balance = await self.cog._purchase(
            self.user_id, self.category, self.selected
        )
        self.balance = balance
        self.owned = await self.cog._owned(self.user_id)
        if success:
            self.selected = self.selected
        await interaction.response.edit_message(
            content=f"✅ {message}" if success else f"ℹ️ {message}",
            embed=self.cog._shop_embed(self.balance, self.category, self.selected, self.owned),
            view=self,
        )

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄", row=2)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.refresh(interaction)

    @discord.ui.button(label="Inventory", style=discord.ButtonStyle.primary, emoji="🎒", row=2)
    async def inventory_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Use `,pinventory` to view your owned items and equipped cosmetics.",
            ephemeral=True,
        )

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="✖", row=2)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Shop closed.", view=self)


class CategorySelect(discord.ui.Select):
    def __init__(self, shop_view: ShopView):
        self.shop_view = shop_view
        options = [
            discord.SelectOption(label=label.split(" ", 1)[1], value=key, emoji=label.split(" ", 1)[0])
            for key, label in CATEGORY_LABELS.items()
        ]
        super().__init__(
            placeholder="Browse a category...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        self.shop_view.category = self.values[0]
        self.shop_view.selected = None
        for child in list(self.shop_view.children):
            if isinstance(child, ItemSelect):
                self.shop_view.remove_item(child)
                break
        self.shop_view.add_item(ItemSelect(self.shop_view))
        await self.shop_view.refresh(interaction)


class ItemSelect(discord.ui.Select):
    def __init__(self, shop_view: ShopView):
        self.shop_view = shop_view
        category = shop_view.category
        options = []
        for item_id, (name, cost, _description) in SHOP[category].items():
            owned = (category, item_id) in shop_view.owned
            options.append(discord.SelectOption(
                label=name,
                value=item_id,
                description=f"{cost} tokens • {'Owned' if owned else 'Unlock permanently'}",
                emoji="✅" if owned else "🔓",
            ))
        super().__init__(
            placeholder="Select an item to view details...",
            min_values=1,
            max_values=1,
            options=options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        self.shop_view.selected = self.values[0]
        await self.shop_view.refresh(interaction)


async def setup(bot):
    await bot.add_cog(PrestigeShop(bot))
