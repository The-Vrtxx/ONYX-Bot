import re
from urllib.parse import urlparse

import discord
from discord.ext import commands


EMBED_COLOR = 0x2C2643
MAX_FIELDS = 25


def valid_http_url(value):
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def build_embed(data):
    color_text = data.get("color", "2C2643").strip().lstrip("#")
    try:
        color = int(color_text, 16)
        if len(color_text) not in (3, 6):
            raise ValueError
        if len(color_text) == 3:
            color = int("".join(ch * 2 for ch in color_text), 16)
    except (TypeError, ValueError):
        color = EMBED_COLOR

    embed = discord.Embed(
        title=data.get("title") or None,
        description=data.get("description") or None,
        color=color
    )

    if data.get("author"):
        embed.set_author(name=data["author"][:256])
    if data.get("footer"):
        embed.set_footer(text=data["footer"][:2048])
    if data.get("thumbnail") and valid_http_url(data["thumbnail"]):
        embed.set_thumbnail(url=data["thumbnail"])
    if data.get("image") and valid_http_url(data["image"]):
        embed.set_image(url=data["image"])

    for field in data.get("fields", [])[:MAX_FIELDS]:
        embed.add_field(
            name=field["name"][:256],
            value=field["value"][:1024],
            inline=field.get("inline", False)
        )

    if data.get("timestamp"):
        embed.timestamp = discord.utils.utcnow()

    return embed


class EmbedEditModal(discord.ui.Modal):
    def __init__(self, creator, section):
        self.creator = creator
        self.section = section

        labels = {
            "title": ("Title", "Embed title", 256, False),
            "description": ("Description", "Main embed text", 4000, True),
            "color": ("Color", "Hex color, e.g. #5865F2", 7, False),
            "author": ("Author", "Author name", 256, False),
            "footer": ("Footer", "Footer text", 2048, False),
            "thumbnail": ("Thumbnail URL", "https://...", 500, False),
            "image": ("Image URL", "https://...", 500, False),
        }
        label, placeholder, max_length, paragraph = labels[section]
        super().__init__(title=f"Edit {label}")
        current = creator.data.get(section, "")
        self.value_input = discord.ui.TextInput(
            label=label,
            placeholder=placeholder,
            default=current[:max_length] if current else None,
            required=section not in {"author", "footer", "thumbnail", "image"},
            max_length=max_length,
            style=discord.TextStyle.paragraph if paragraph else discord.TextStyle.short
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        value = self.value_input.value.strip()
        if self.section in {"thumbnail", "image"} and value and not valid_http_url(value):
            return await interaction.response.send_message(
                "Please enter a valid URL beginning with `https://` or `http://`.",
                ephemeral=True
            )
        if self.section == "color" and value:
            color = value.lstrip("#")
            if not re.fullmatch(r"(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})", color):
                return await interaction.response.send_message(
                    "Use a 3- or 6-digit hex color, such as `#5865F2`.",
                    ephemeral=True
                )
            value = color
        self.creator.data[self.section] = value
        await interaction.response.edit_message(
            embed=self.creator.make_panel_embed(),
            view=self.creator
        )


class EmbedFieldModal(discord.ui.Modal):
    def __init__(self, creator):
        super().__init__(title="Add an embed field")
        self.creator = creator
        self.name_input = discord.ui.TextInput(
            label="Field name", max_length=256, placeholder="Field heading"
        )
        self.value_input = discord.ui.TextInput(
            label="Field content", max_length=1024,
            placeholder="What should this field say?",
            style=discord.TextStyle.paragraph
        )
        self.inline_input = discord.ui.TextInput(
            label="Inline? (yes or no)", required=False,
            default="no", max_length=3
        )
        self.add_item(self.name_input)
        self.add_item(self.value_input)
        self.add_item(self.inline_input)

    async def on_submit(self, interaction: discord.Interaction):
        if len(self.creator.data["fields"]) >= MAX_FIELDS:
            return await interaction.response.send_message(
                "An embed can contain up to 25 fields.", ephemeral=True
            )
        inline = self.inline_input.value.strip().lower() in {"yes", "y", "true"}
        self.creator.data["fields"].append({
            "name": self.name_input.value.strip(),
            "value": self.value_input.value.strip(),
            "inline": inline
        })
        await interaction.response.edit_message(
            embed=self.creator.make_panel_embed(),
            view=self.creator
        )


class EmbedSectionSelect(discord.ui.Select):
    def __init__(self, creator):
        self.creator = creator
        options = [
            discord.SelectOption(label="Title", value="title", description="Set the embed heading", emoji="📝"),
            discord.SelectOption(label="Description", value="description", description="Write the main message", emoji="📄"),
            discord.SelectOption(label="Color", value="color", description="Choose a hex color", emoji="🎨"),
            discord.SelectOption(label="Author", value="author", description="Add an author line", emoji="👤"),
            discord.SelectOption(label="Footer", value="footer", description="Add a footer", emoji="🔻"),
            discord.SelectOption(label="Thumbnail", value="thumbnail", description="Add a small image URL", emoji="🖼️"),
            discord.SelectOption(label="Main image", value="image", description="Add a large image URL", emoji="🌄"),
            discord.SelectOption(label="Add field", value="field", description="Add a named information field", emoji="➕"),
            discord.SelectOption(label="Timestamp", value="timestamp", description="Toggle the current timestamp", emoji="🕒"),
        ]
        super().__init__(
            placeholder="Choose what you want to edit...",
            min_values=1, max_values=1, options=options, row=0
        )

    async def callback(self, interaction: discord.Interaction):
        section = self.values[0]
        if section == "field":
            return await interaction.response.send_modal(EmbedFieldModal(self.creator))
        if section == "timestamp":
            self.creator.data["timestamp"] = not self.creator.data["timestamp"]
            return await interaction.response.edit_message(
                embed=self.creator.make_panel_embed(), view=self.creator
            )
        await interaction.response.send_modal(EmbedEditModal(self.creator, section))


class EmbedCreatorView(discord.ui.View):
    def __init__(self, author_id, channel, initial_data=None):
        super().__init__(timeout=600)
        self.author_id = author_id
        self.channel = channel
        self.data = initial_data or {
            "title": "",
            "description": "",
            "color": "2C2643",
            "author": "",
            "footer": "",
            "thumbnail": "",
            "image": "",
            "fields": [],
            "timestamp": False,
        }
        self.add_item(EmbedSectionSelect(self))

    def make_panel_embed(self):
        embed = discord.Embed(
            title="ONYX • Embed Creator",
            description=(
                "Use the dropdown below to build your embed. "
                "Your changes will appear in this panel."
            ),
            color=EMBED_COLOR
        )
        lines = [
            f"**Title:** {self.data['title'] or 'Not set'}",
            f"**Description:** {'Added' if self.data['description'] else 'Not set'}",
            f"**Color:** `#{self.data['color']}`",
            f"**Author:** {self.data['author'] or 'Not set'}",
            f"**Footer:** {self.data['footer'] or 'Not set'}",
            f"**Thumbnail:** {'Added' if self.data['thumbnail'] else 'Not set'}",
            f"**Main image:** {'Added' if self.data['image'] else 'Not set'}",
            f"**Fields:** {len(self.data['fields'])}/25",
            f"**Timestamp:** {'On' if self.data['timestamp'] else 'Off'}",
        ]
        embed.add_field(name="Builder status", value="\n".join(lines), inline=False)
        if self.data["fields"]:
            field_preview = "\n".join(
                f"• **{item['name']}** — {item['value'][:80]}"
                for item in self.data["fields"][:8]
            )
            embed.add_field(name="Added fields", value=field_preview, inline=False)
        embed.set_footer(text="Only the person who opened this creator can use it.")
        return embed

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This embed creator belongs to the person who opened it.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Preview", style=discord.ButtonStyle.secondary, emoji="👁️", row=1)
    async def preview_button(self, interaction, button):
        embed = build_embed(self.data)
        if not embed.title and not embed.description and not self.data["fields"]:
            return await interaction.response.send_message(
                "Add a title, description, or at least one field before previewing.",
                ephemeral=True
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Send Embed", style=discord.ButtonStyle.success, emoji="📨", row=1)
    async def send_button(self, interaction, button):
        embed = build_embed(self.data)
        if not embed.title and not embed.description and not self.data["fields"]:
            return await interaction.response.send_message(
                "Add a title, description, or at least one field before sending.",
                ephemeral=True
            )
        try:
            await self.channel.send(embed=embed)
        except discord.Forbidden:
            return await interaction.response.send_message(
                "I don't have permission to send embeds in this channel.",
                ephemeral=True
            )
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="✅ Embed sent successfully. This creator is now closed.",
            embed=None,
            view=self
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="✖️", row=1)
    async def cancel_button(self, interaction, button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="Embed creator cancelled.",
            embed=None,
            view=self
        )
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class Custom(commands.Cog):
    """Custom text commands and the single interactive embed builder."""

    def __init__(self, bot):
        self.bot = bot

    async def open_embed_creator(self, ctx):
        """Open the dropdown-based embed builder in the current channel."""
        view = EmbedCreatorView(ctx.author.id, ctx.channel)
        await ctx.send(embed=view.make_panel_embed(), view=view)

    @commands.group(
        name="embed",
        invoke_without_command=True,
        help="Open the interactive dropdown menu to create a custom embed."
    )
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    async def embed(self, ctx):
        await self.open_embed_creator(ctx)

    @embed.command(
        name="create",
        help="Open the interactive dropdown menu to build and send an embed."
    )
    @commands.has_permissions(manage_messages=True)
    async def embed_create(self, ctx):
        await self.open_embed_creator(ctx)

    @commands.command(
        name="copyembed",
        aliases=["embedcopy"],
        help="Load an embed from a message link or reply into the dropdown creator."
    )
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    async def copy_embed(self, ctx, message: discord.Message = None):
        """Load the first embed from a message into the visual embed creator."""
        source = message

        if source is None and ctx.message.reference:
            source = ctx.message.reference.resolved
            if source is None:
                reference = ctx.message.reference
                if reference.message_id:
                    try:
                        channel = (
                            self.bot.get_channel(reference.channel_id)
                            or await self.bot.fetch_channel(reference.channel_id)
                        )
                        source = await channel.fetch_message(reference.message_id)
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        source = None

        if source is None:
            return await ctx.send(
                f"Reply to a message containing an embed, or use "
                f"`{ctx.prefix}copyembed <message link>`."
            )

        if not source.embeds:
            return await ctx.send("That message doesn't contain an embed to copy.")

        original = source.embeds[0]
        color = f"{original.color.value:06X}" if original.color else "2C2643"
        copied_data = {
            "title": original.title or "",
            "description": original.description or "",
            "color": color,
            "author": original.author.name or "" if original.author else "",
            "footer": original.footer.text or "" if original.footer else "",
            "thumbnail": original.thumbnail.url or "" if original.thumbnail else "",
            "image": original.image.url or "" if original.image else "",
            "fields": [
                {
                    "name": field.name,
                    "value": field.value,
                    "inline": field.inline,
                }
                for field in original.fields[:MAX_FIELDS]
            ],
            "timestamp": original.timestamp is not None,
        }

        view = EmbedCreatorView(ctx.author.id, ctx.channel, initial_data=copied_data)
        await ctx.send(
            "Embed copied into the dropdown creator. Use the menu to edit it, then preview or send it.",
            embed=view.make_panel_embed(),
            view=view,
        )

    @commands.command(name="custom_add", help="Create or update a custom text command for this server.")
    @commands.has_permissions(manage_guild=True)
    async def add(self, ctx, name: str, *, response: str):
        name = name.lower()
        if not re.fullmatch(r"[a-z0-9_-]{2,32}", name):
            return await ctx.send("Use 2–32 letters, numbers, underscores or hyphens.")
        if len(response) > 1800:
            return await ctx.send("Response must be 1800 characters or fewer.")
        await self.bot.db.execute(
            "INSERT INTO custom_commands VALUES (?,?,?) "
            "ON CONFLICT(guild_id,name) DO UPDATE SET response=excluded.response",
            (ctx.guild.id, name, response)
        )
        await ctx.send(f"Custom command `{ctx.prefix}{name}` saved.")

    @commands.command(name="custom_run", help="Run a custom text command saved by this server.")
    async def run_custom(self, ctx, name: str):
        row = await self.bot.db.fetchone(
            "SELECT response FROM custom_commands WHERE guild_id=? AND name=?",
            (ctx.guild.id, name.lower())
        )
        if not row:
            return await ctx.send("That custom command doesn't exist.")
        safe = row["response"].replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
        await ctx.send(safe, allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="custom_remove", help="Delete a custom text command from this server.")
    @commands.has_permissions(manage_guild=True)
    async def remove(self, ctx, name: str):
        await self.bot.db.execute(
            "DELETE FROM custom_commands WHERE guild_id=? AND name=?",
            (ctx.guild.id, name.lower())
        )
        await ctx.send(f"Deleted `{name}` if it existed.")


async def setup(bot):
    await bot.add_cog(Custom(bot))
