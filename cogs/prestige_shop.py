"""ONYX Prestige Shop — interactive Discord shop.

Commands:
  ,shop / ,pshop       Open the interactive Prestige Shop
  ,pinventory          View owned cosmetics and equipped items
  ,pequip <category> <item>   Equip an owned cosmetic or earned title
  ,punequip <category>        Reset a cosmetic slot
"""
import asyncio
import io
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import discord
from discord.ext import commands

from .levels import render_onyx_profile_card


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


RARITY_BY_COST = {
    5: ("COMMON", (170, 185, 198)),
    10: ("UNCOMMON", (70, 210, 160)),
    15: ("RARE", (70, 160, 255)),
    20: ("EPIC", (180, 100, 255)),
    25: ("LEGENDARY", (255, 190, 65)),
}
ART_PALETTES = {
    "steel": (150, 175, 195), "neon": (40, 235, 220),
    "elite": (255, 195, 70), "obsidian": (150, 100, 230),
    "legendary": (255, 95, 65), "frost": (110, 205, 255),
    "inferno": (255, 95, 45), "toxic": (130, 240, 75),
    "eclipse": (185, 100, 255), "void": (125, 75, 220),
    "veteran": (160, 190, 215), "champion": (255, 200, 70),
    "warlord": (255, 90, 85), "mythic": (210, 100, 255),
    "elite": (255, 195, 70), "teal_glow": (40, 235, 220),
    "silver_shine": (220, 235, 245), "electric_pulse": (70, 145, 255),
    "cosmic_aura": (185, 90, 255),
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
        return levels.unlocked_titles(row)

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

    def _shop_art(self, category: str, item_id: str | None = None):
        """Create a distinct compact cosmetic illustration for the selected shop item."""
        item_id = item_id if item_id in SHOP.get(category, {}) else next(iter(SHOP[category]))
        name, cost, _ = SHOP[category][item_id]
        rarity, accent = RARITY_BY_COST[cost]
        accent = ART_PALETTES.get(item_id, accent)
        image = Image.new("RGB", (512, 512), (5, 12, 22))
        draw = ImageDraw.Draw(image)
        # Layered radial-style rings and a category-specific centerpiece.
        for radius, alpha in ((225, 55), (185, 85), (145, 125)):
            box = (256-radius, 256-radius, 256+radius, 256+radius)
            draw.ellipse(box, outline=tuple(int(c*alpha/125) for c in accent), width=5)
        seed = sum(ord(ch) for ch in (category + item_id))
        for i in range(12):
            angle = (math.pi * 2 * i / 12) + (seed % 17) * .03
            x1, y1 = 256 + math.cos(angle)*150, 256 + math.sin(angle)*150
            x2, y2 = 256 + math.cos(angle)*218, 256 + math.sin(angle)*218
            draw.line((x1, y1, x2, y2), fill=accent, width=4)
        if category == "frame":
            draw.rounded_rectangle((115, 115, 397, 397), radius=42, outline=accent, width=20)
            draw.rounded_rectangle((145, 145, 367, 367), radius=28, outline=(210,225,240), width=3)
            for x,y in ((115,115),(397,115),(115,397),(397,397)):
                draw.polygon([(x,y-18),(x+18,y),(x,y+18),(x-18,y)], fill=accent)
        elif category == "theme":
            for i in range(7):
                y = 145 + i*34
                draw.arc((90, y-50, 422, y+90), start=190+(seed%40), end=350+(seed%40), fill=accent, width=9)
            draw.ellipse((195,195,317,317), fill=(12,24,42), outline=accent, width=8)
        elif category == "emblem":
            points=[]
            for i in range(16):
                angle=-math.pi/2 + i*math.pi/8
                r=145 if i%2==0 else 78
                points.append((256+math.cos(angle)*r,256+math.sin(angle)*r))
            draw.polygon(points, fill=(12,25,42), outline=accent)
            draw.ellipse((210,210,302,302), outline=(230,240,250), width=7)
            draw.line((256,178,256,334), fill=accent, width=8)
        else:
            for i in range(9):
                angle=(math.pi*2*i/9)+(seed%13)*.04
                x=256+math.cos(angle)*105; y=256+math.sin(angle)*105
                draw.ellipse((x-18,y-18,x+18,y+18), fill=accent)
                draw.line((256,256,x,y), fill=accent, width=5)
            draw.ellipse((205,205,307,307), outline=(235,245,255), width=8)
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", 24)
        except OSError:
            font = ImageFont.load_default()
        label = rarity
        bbox = draw.textbbox((0,0), label, font=font)
        draw.text(((512-(bbox[2]-bbox[0]))/2, 455), label, font=font, fill=accent)
        output = io.BytesIO()
        image.save(output, format="PNG")
        output.seek(0)
        return discord.File(output, filename="onyx-shop-art.png")

    def _shop_welcome_art(self):
        """Return the ONYX welcome banner shown before a member selects an item."""
        asset = Path(__file__).resolve().parent.parent / "assets" / "onyx_shop_welcome.png"
        if not asset.exists():
            raise FileNotFoundError(f"Missing ONYX shop welcome artwork: {asset}")
        return discord.File(str(asset), filename="onyx-shop-welcome.png")

    def _shop_embed(self, balance: int, category: str = "frame",
                    selected: str | None = None, owned=None):
        owned = owned or set()
        embed = discord.Embed(
            title="ONYX  /  PRESTIGE SHOP",
            description=(
                "Use your Prestige Tokens to customize your global profile card.\n"
                "Choose a category, select an item, and preview its details here. "
                "Use **Preview on Card** to see the cosmetic on your actual profile card."
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
            rarity, rarity_rgb = RARITY_BY_COST[cost]
            embed.color = discord.Color.from_rgb(*rarity_rgb)
            embed.add_field(
                name=f"{rarity}  /  {name}",
                value=f"{description}\n\n**Price:** {cost} tokens\n**Rarity:** {rarity.title()}\n**Status:** {status}",
                inline=False,
            )
            embed.set_thumbnail(url="attachment://onyx-shop-art.png")
        else:
            embed.set_image(url="attachment://onyx-shop-welcome.png")
            embed.add_field(
                name="HOW TO SHOP",
                value="1. Pick a category below.\n2. Select an item.\n3. Press **Buy Item** to unlock it permanently.",
                inline=False,
            )

        lines = []
        for item_id, (name, cost, _desc) in SHOP[category].items():
            mark = " ✓" if (category, item_id) in owned else ""
            rarity = RARITY_BY_COST[cost][0].title()
            lines.append(f"`{cost:>2}` • **{name}** — *{rarity}*{mark}")
        embed.add_field(name=f"{category.upper()} CATALOG", value="\n".join(lines), inline=False)
        embed.add_field(
            name="RARITY GUIDE",
            value="Common · Uncommon · Rare · Epic · Legendary\nHigher token prices indicate higher cosmetic rarity.",
            inline=False,
        )
        embed.set_footer(text="Each item has its own generated artwork • Purchases are permanent")
        return embed

    async def _send_workspace(self, ctx, workspace: str = "shop"):
        user_id = ctx.author.id
        if workspace == "inventory":
            await ctx.send(
                embed=await self._inventory_embed(user_id, ctx.author.display_name),
                view=InventoryView(self, user_id),
            )
        elif workspace == "studio":
            levels = self._levels_cog()
            if not levels:
                return await ctx.send("The Levels cog is not loaded. Please try again after it starts.")
            equipped = await self._equipped(user_id)
            owned = await self._owned(user_id)
            titles = await self._earned_titles(user_id)
            view = ProfilePreviewView(self, user_id, equipped, owned, titles)
            await ctx.send(embed=view.make_embed(), view=view)
        else:
            balance = await self._wallet(user_id)
            owned = await self._owned(user_id)
            view = ShopView(self, user_id, balance, owned)
            await ctx.send(embed=self._shop_embed(balance, owned=owned), file=self._shop_welcome_art(), view=view)

    @commands.command(name="onyx", aliases=["menu", "hub"])
    @commands.guild_only()
    async def onyx(self, ctx):
        """Open the central ONYX menu."""
        await self._send_workspace(ctx, "shop")

    @commands.command(name="shop", aliases=["pshop", "prestigeshop"])
    @commands.guild_only()
    async def shop(self, ctx):
        await self._send_workspace(ctx, "shop")

    @commands.command(name="pinventory", aliases=["prestigeinventory", "inventory"])
    @commands.guild_only()
    async def pinventory(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        if member.id == ctx.author.id:
            await self._send_workspace(ctx, "inventory")
        else:
            await ctx.send(embed=await self._inventory_embed(member.id, member.display_name))

    async def _inventory_embed(self, user_id: int, display_name: str = "Your"):
        owned = await self._owned(user_id)
        balance = await self._wallet(user_id)
        equipped = await self._equipped(user_id)
        embed = discord.Embed(
            title=f"{display_name}  /  ONYX INVENTORY",
            description=(
                f"**Prestige Tokens:** {balance}\n"
                "Choose a slot below, select an owned item, then equip or preview it."
            ),
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
                name=f"{category.title()}  •  Equipped: {current_name}",
                value="\n".join(items) if items else "Nothing unlocked yet.",
                inline=False,
            )
        titles = await self._earned_titles(user_id)
        active_title = equipped.get("title_id") or (titles[-1] if titles else None)
        embed.add_field(
            name="Prestige Master Titles",
            value=", ".join(titles) if titles else "No titles unlocked yet.",
            inline=False,
        )
        embed.add_field(name="Equipped Title", value=active_title or "No title selected", inline=False)
        embed.set_footer(text="Cosmetics are permanent unlocks • Equip one item per slot")
        return embed

    @commands.command(name="preview", aliases=["cardpreview", "profilepreview"])
    @commands.guild_only()
    async def preview(self, ctx):
        """Open a private cosmetic loadout preview before applying changes."""
        levels = self._levels_cog()
        if not levels:
            return await ctx.send("The Levels cog is not loaded. Please try again after it starts.")
        equipped = await self._equipped(ctx.author.id)
        owned = await self._owned(ctx.author.id)
        titles = await self._earned_titles(ctx.author.id)
        view = ProfilePreviewView(self, ctx.author.id, equipped, owned, titles)
        await ctx.send(
            embed=view.make_embed(),
            view=view,
            delete_after=None,
        )

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
        self.add_item(WorkspaceSelect(self, "shop"))

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
            attachments=[self.cog._shop_art(self.category, self.selected) if self.selected else self.cog._shop_welcome_art()],
            view=self,
        )

    @discord.ui.button(label="Buy Item", style=discord.ButtonStyle.success, emoji=None, row=2)
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
            attachments=[self.cog._shop_art(self.category, self.selected)],
            view=self,
        )

    @discord.ui.button(label="Preview on Card", style=discord.ButtonStyle.primary, emoji=None, row=2)
    async def preview_art_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected:
            return await interaction.response.send_message(
                "Select a shop item first, then preview it on your profile card.",
                ephemeral=True,
            )
        levels = self.cog._levels_cog()
        if not levels:
            return await interaction.response.send_message(
                "The Levels cog is not loaded. Please try again after it starts.",
                ephemeral=True,
            )
        # Acknowledge immediately so Discord does not expire the component interaction
        # while database reads and PNG rendering are in progress.
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            row = await levels.profile(self.user_id)
            titles = levels.unlocked_titles(row)
            cosmetics = await levels.equipped_cosmetics(self.user_id)
            column = COLUMN_BY_CATEGORY[self.category]
            cosmetics[column] = self.selected
            card = render_onyx_profile_card(
                display_name=interaction.user.display_name,
                row=row,
                unlocked_titles=titles,
                tokens=await levels.prestige_tokens(self.user_id),
                cosmetics=cosmetics,
            )
            name = display_item(self.category, self.selected)
            await interaction.followup.send(
                content=f"**{name}** — preview only. This has not been equipped or purchased.",
                file=discord.File(card, filename="onyx-cosmetic-preview.png"),
                ephemeral=True,
            )
        except Exception:
            await interaction.followup.send(
                "I couldn't generate that preview. Please try again; the error has been logged.",
                ephemeral=True,
            )
            raise

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, emoji=None, row=2)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.refresh(interaction)

    @discord.ui.button(label="Inventory", style=discord.ButtonStyle.primary, emoji=None, row=2)
    async def inventory_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=await self.cog._inventory_embed(self.user_id),
            view=InventoryView(self.cog, self.user_id),
            ephemeral=True,
        )

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji=None, row=2)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Shop closed.", view=self)


class CategorySelect(discord.ui.Select):
    def __init__(self, shop_view: ShopView):
        self.shop_view = shop_view
        options = [
            discord.SelectOption(label=label.split(" ", 1)[1], value=key, emoji=None)
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
                emoji=None,
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


class WorkspaceSelect(discord.ui.Select):
    """One navigation dropdown shared by Shop, Inventory, and Profile Studio."""
    def __init__(self, parent_view, current: str):
        self.parent_view = parent_view
        options = [
            discord.SelectOption(
                label="Prestige Shop",
                value="shop",
                description="Browse and purchase profile cosmetics",
                emoji=None,
                default=current == "shop",
            ),
            discord.SelectOption(
                label="Inventory & Equipment",
                value="inventory",
                description="Manage owned cosmetics and titles",
                emoji=None,
                default=current == "inventory",
            ),
            discord.SelectOption(
                label="Profile Card Studio",
                value="studio",
                description="Customize and preview your profile card",
                emoji=None,
                default=current == "studio",
            ),
        ]
        super().__init__(
            placeholder="ONYX Hub • Switch section...",
            min_values=1,
            max_values=1,
            options=options,
            row=3,
        )

    async def callback(self, interaction: discord.Interaction):
        cog = self.parent_view.cog
        user_id = self.parent_view.user_id
        destination = self.values[0]

        if destination == "inventory":
            new_view = InventoryView(cog, user_id)
            embed = await cog._inventory_embed(user_id)
            content = "🎒 **ONYX Inventory & Equipment**"
        elif destination == "studio":
            levels = cog._levels_cog()
            if not levels:
                return await interaction.response.send_message(
                    "The Levels cog is not loaded. Please try again after it starts.",
                    ephemeral=True,
                )
            equipped = await cog._equipped(user_id)
            owned = await cog._owned(user_id)
            titles = await cog._earned_titles(user_id)
            new_view = ProfilePreviewView(cog, user_id, equipped, owned, titles)
            embed = new_view.make_embed()
            content = "🎨 **ONYX Profile Card Studio**"
        else:
            balance = await cog._wallet(user_id)
            owned = await cog._owned(user_id)
            new_view = ShopView(cog, user_id, balance, owned)
            embed = cog._shop_embed(balance, owned=owned)
            content = "🛒 **ONYX Prestige Shop**"

        if destination == "shop":
            await interaction.response.edit_message(content=content, embed=embed, attachments=[cog._shop_welcome_art()], view=new_view)
        else:
            await interaction.response.edit_message(content=content, embed=embed, attachments=[], view=new_view)


class InventoryView(discord.ui.View):
    """Interactive inventory for equipping, previewing, and resetting cosmetics."""
    def __init__(self, cog: PrestigeShop, user_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        self.category = "frame"
        self.selected = None
        self.add_item(InventoryCategorySelect(self))
        self.add_item(InventoryItemSelect(self))
        self.add_item(WorkspaceSelect(self, "inventory"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This inventory belongs to someone else. Run `,inventory` to open your own.",
                ephemeral=True,
            )
            return False
        return True

    async def redraw(self, interaction: discord.Interaction):
        self.selected = None
        for child in list(self.children):
            if isinstance(child, InventoryItemSelect):
                self.remove_item(child)
        self.add_item(InventoryItemSelect(self))
        await interaction.response.edit_message(
            embed=await self.cog._inventory_embed(self.user_id), view=self
        )

    @discord.ui.button(label="Equip Selected", style=discord.ButtonStyle.success, emoji=None, row=2)
    async def equip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected:
            return await interaction.response.send_message("Select an owned item first.", ephemeral=True)
        category, item_id = self.category, self.selected
        if category == "title":
            titles = await self.cog._earned_titles(self.user_id)
            title_lookup = {slugify(title): title for title in titles}
            if item_id not in title_lookup:
                return await interaction.response.send_message("That title is not unlocked.", ephemeral=True)
            value = title_lookup[item_id]
        else:
            if (category, item_id) not in await self.cog._owned(self.user_id):
                return await interaction.response.send_message("You do not own that item.", ephemeral=True)
            value = item_id
        await self.cog._equipped(self.user_id)
        await self.cog.bot.db.execute(
            f"UPDATE onyx_profile_equipped SET {COLUMN_BY_CATEGORY[category]}=? WHERE user_id=?",
            (value, self.user_id),
        )
        await interaction.response.edit_message(
            content=f"✅ Equipped **{display_item(category, value)}**. Your next `,rank` card will use it.",
            embed=await self.cog._inventory_embed(self.user_id), view=self,
        )

    @discord.ui.button(label="Preview", style=discord.ButtonStyle.primary, emoji=None, row=2)
    async def preview_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected:
            return await interaction.response.send_message("Select an item to preview first.", ephemeral=True)
        levels = self.cog._levels_cog()
        if not levels:
            return await interaction.response.send_message("The Levels cog is not loaded.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            row = await levels.profile(self.user_id)
            titles = levels.unlocked_titles(row)
            cosmetics = await levels.equipped_cosmetics(self.user_id)
            if self.category in ("frame", "theme", "emblem", "effect"):
                cosmetics[COLUMN_BY_CATEGORY[self.category]] = self.selected
            elif self.category == "title":
                earned = {slugify(title): title for title in titles}
                if self.selected not in earned:
                    return await interaction.followup.send("That title is not unlocked.", ephemeral=True)
                cosmetics["title_id"] = earned[self.selected]
            card = render_onyx_profile_card(
                display_name=interaction.user.display_name,
                row=row,
                unlocked_titles=titles,
                tokens=await levels.prestige_tokens(self.user_id),
                cosmetics=cosmetics,
            )
            note = "Preview only — nothing has been equipped."
            await interaction.followup.send(
                content=note,
                file=discord.File(card, filename="onyx-inventory-preview.png"),
                ephemeral=True,
            )
        except Exception:
            await interaction.followup.send(
                "I couldn't generate that preview. Please try again; the error has been logged.",
                ephemeral=True,
            )
            raise

    @discord.ui.button(label="Unequip Slot", style=discord.ButtonStyle.secondary, emoji=None, row=2)
    async def unequip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        category = self.category
        await self.cog._equipped(self.user_id)
        await self.cog.bot.db.execute(
            f"UPDATE onyx_profile_equipped SET {COLUMN_BY_CATEGORY[category]}=? WHERE user_id=?",
            (DEFAULTS[category], self.user_id),
        )
        await interaction.response.edit_message(
            content=f"Reset your {category} slot to its default.",
            embed=await self.cog._inventory_embed(self.user_id), view=self,
        )

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, emoji=None, row=2)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=await self.cog._inventory_embed(self.user_id), view=self
        )


class InventoryCategorySelect(discord.ui.Select):
    def __init__(self, view: InventoryView):
        self.inventory_view = view
        options = [
            discord.SelectOption(label=label.split(" ", 1)[1], value=key, emoji=None)
            for key, label in CATEGORY_LABELS.items()
        ]
        options.append(discord.SelectOption(label="Titles", value="title", emoji=None))
        super().__init__(placeholder="Choose an equipment slot...", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        self.inventory_view.category = self.values[0]
        category = self.values[0]
        if category == "title":
            items = await self.inventory_view.cog._earned_titles(self.inventory_view.user_id)
            options = [discord.SelectOption(label=title, value=slugify(title)) for title in items[:25]]
        else:
            owned = await self.inventory_view.cog._owned(self.inventory_view.user_id)
            items = [item_id for owned_category, item_id in sorted(owned) if owned_category == category]
            options = [discord.SelectOption(label=display_item(category, item_id), value=item_id) for item_id in items[:25]]
        if not options:
            options = [discord.SelectOption(label="No items owned in this slot", value="none", description="Purchase or unlock one first")]
        for child in list(self.inventory_view.children):
            if isinstance(child, InventoryItemSelect):
                self.inventory_view.remove_item(child)
        self.inventory_view.add_item(InventoryItemSelect(self.inventory_view, options))
        await interaction.response.edit_message(embed=await self.inventory_view.cog._inventory_embed(self.inventory_view.user_id), view=self.inventory_view)


class InventoryItemSelect(discord.ui.Select):
    def __init__(self, view: InventoryView, options=None):
        self.inventory_view = view
        options = options or [discord.SelectOption(label="Choose a slot above first", value="none")]
        super().__init__(placeholder="Select an owned item...", min_values=1, max_values=1, options=options[:25], row=1)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return await interaction.response.send_message(
                "Choose a category first, then select one of your owned items.",
                ephemeral=True,
            )
        self.inventory_view.selected = self.values[0]
        await interaction.response.send_message(
            f"Selected **{display_item(self.inventory_view.category, self.values[0])}**. Use Equip Selected or Preview.",
            ephemeral=True,
        )



class ProfilePreviewView(discord.ui.View):
    """Temporary loadout builder; changes are only saved after Apply Changes."""
    def __init__(self, cog: PrestigeShop, user_id: int, equipped, owned, titles):
        super().__init__(timeout=240)
        self.cog = cog
        self.user_id = user_id
        self.owned = owned
        self.titles = titles
        self.original = {
            "frame_id": equipped.get("frame_id") or DEFAULTS["frame"],
            "theme_id": equipped.get("theme_id") or DEFAULTS["theme"],
            "emblem_id": equipped.get("emblem_id") or DEFAULTS["emblem"],
            "effect_id": equipped.get("effect_id") or DEFAULTS["effect"],
            "title_id": equipped.get("title_id"),
        }
        self.pending = dict(self.original)
        self.category = "frame"
        self.add_item(PreviewCategorySelect(self))
        self.add_item(PreviewItemSelect(self))
        self.add_item(WorkspaceSelect(self, "studio"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This preview belongs to someone else. Run `,preview` to open your own.",
                ephemeral=True,
            )
            return False
        return True

    def make_embed(self):
        embed = discord.Embed(
            title="ONYX  /  PROFILE CARD STUDIO",
            description=(
                "Build a cosmetic combination and preview the card before saving. "
                "Nothing changes until you press **Apply Changes**."
            ),
            color=discord.Color.from_rgb(25, 190, 190),
        )
        labels = {
            "frame_id": "Frame", "theme_id": "Theme", "emblem_id": "Emblem",
            "effect_id": "Effect", "title_id": "Title",
        }
        values = []
        for key, label in labels.items():
            value = self.pending.get(key)
            if key == "title_id":
                shown = value or "No title"
            elif value == DEFAULTS[key.replace("_id", "")]:
                shown = "Default"
            else:
                shown = display_item(key.replace("_id", ""), value)
            changed = "  •  modified" if value != self.original.get(key) else ""
            values.append(f"**{label}:** {shown}{changed}")
        embed.add_field(name="CURRENT PREVIEW LOADOUT", value="\n".join(values), inline=False)
        embed.set_footer(text="Preview is temporary • Apply Changes saves all selected slots")
        return embed

    def item_options(self):
        category = self.category
        if category == "title":
            options = [discord.SelectOption(label="No title", value="__default__")]
            options.extend(discord.SelectOption(label=title, value=slugify(title)) for title in self.titles[:24])
            return options[:25]
        options = [discord.SelectOption(label="Default", value="__default__")]
        options.extend(
            discord.SelectOption(label=display_item(category, item_id), value=item_id)
            for owned_category, item_id in sorted(self.owned)
            if owned_category == category
        )
        return options[:25]

    async def redraw(self, interaction: discord.Interaction, content=None):
        for child in list(self.children):
            if isinstance(child, PreviewItemSelect):
                self.remove_item(child)
        self.add_item(PreviewItemSelect(self, self.item_options()))
        await interaction.response.edit_message(content=content, embed=self.make_embed(), view=self)

    @discord.ui.button(label="Preview Card", style=discord.ButtonStyle.primary, emoji=None, row=2)
    async def preview_card_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        levels = self.cog._levels_cog()
        if not levels:
            return await interaction.response.send_message("The Levels cog is not loaded.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            row = await levels.profile(self.user_id)
            titles = levels.unlocked_titles(row)
            card = render_onyx_profile_card(
                display_name=interaction.user.display_name,
                row=row,
                unlocked_titles=titles,
                tokens=await levels.prestige_tokens(self.user_id),
                cosmetics=dict(self.pending),
            )
            await interaction.followup.send(
                content="👁️ **Temporary preview** — your equipped cosmetics have not changed.",
                file=discord.File(card, filename="onyx-profile-preview.png"),
                ephemeral=True,
            )
        except Exception:
            await interaction.followup.send(
                "I couldn't generate that preview. Please try again; the error has been logged.",
                ephemeral=True,
            )
            raise

    @discord.ui.button(label="Apply Changes", style=discord.ButtonStyle.success, emoji=None, row=2)
    async def apply_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._equipped(self.user_id)
        for column in ("frame_id", "theme_id", "emblem_id", "effect_id", "title_id"):
            await self.cog.bot.db.execute(
                f"UPDATE onyx_profile_equipped SET {column}=? WHERE user_id=?",
                (self.pending[column], self.user_id),
            )
        self.original = dict(self.pending)
        await interaction.response.edit_message(
            content="✅ **Your profile loadout has been saved!** Run `,rank` to see your updated card.",
            embed=self.make_embed(),
            view=self,
        )

    @discord.ui.button(label="Reset Preview", style=discord.ButtonStyle.secondary, emoji=None, row=2)
    async def reset_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.pending = dict(self.original)
        await interaction.response.edit_message(
            content="Preview reset to your currently saved loadout.",
            embed=self.make_embed(),
            view=self,
        )


class PreviewCategorySelect(discord.ui.Select):
    def __init__(self, preview: ProfilePreviewView):
        self.preview = preview
        options = [
            discord.SelectOption(label="Frames", value="frame", emoji=None),
            discord.SelectOption(label="Themes", value="theme", emoji=None),
            discord.SelectOption(label="Emblems", value="emblem", emoji=None),
            discord.SelectOption(label="Effects", value="effect", emoji=None),
            discord.SelectOption(label="Titles", value="title", emoji=None),
        ]
        super().__init__(placeholder="Choose a slot to customize...", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        self.preview.category = self.values[0]
        await self.preview.redraw(interaction)


class PreviewItemSelect(discord.ui.Select):
    def __init__(self, preview: ProfilePreviewView, options=None):
        self.preview = preview
        options = options or preview.item_options()
        super().__init__(
            placeholder="Choose an owned cosmetic or default...",
            min_values=1,
            max_values=1,
            options=options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        category = self.preview.category
        selected = self.values[0]
        if category == "title":
            if selected == "__default__":
                value = None
            else:
                title_lookup = {slugify(title): title for title in self.preview.titles}
                value = title_lookup.get(selected)
                if value is None:
                    return await interaction.response.send_message("That title is not unlocked.", ephemeral=True)
            self.preview.pending["title_id"] = value
        else:
            column = COLUMN_BY_CATEGORY[category]
            if selected == "__default__":
                value = DEFAULTS[category]
            else:
                if (category, selected) not in self.preview.owned:
                    return await interaction.response.send_message("You do not own that cosmetic.", ephemeral=True)
                value = selected
            self.preview.pending[column] = value
        await interaction.response.edit_message(embed=self.preview.make_embed(), view=self.preview)


async def setup(bot):
    await bot.add_cog(PrestigeShop(bot))
