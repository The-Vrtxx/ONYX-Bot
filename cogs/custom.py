import re
import discord
from discord.ext import commands

class Custom(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @commands.command(name="embed", help="Create and send a simple custom embed.")
    @commands.has_permissions(manage_messages=True)
    async def embed(self, ctx: commands.Context, title: str, *, description: str, color: str = "5865F2"):
        if len(title) > 256 or len(description) > 4000:
            return await ctx.send("Title or description is too long.",)
        try: parsed = int(color.replace("#", ""), 16)
        except ValueError: return await ctx.send("Color must be a hex value, e.g. `5865F2`.",)
        await ctx.channel.send(embed=discord.Embed(title=title, help=description, color=parsed))
        await ctx.send("Embed sent.",)

    @commands.command(name="custom_add", help="Create a custom text command.")
    @commands.has_permissions(manage_guild=True)
    async def add(self, ctx: commands.Context, name: str, *, response: str):
        name = name.lower()
        if not re.fullmatch(r"[a-z0-9_-]{2,32}", name):
            return await ctx.send("Use 2–32 letters, numbers, underscores or hyphens.",)
        if len(response) > 1800:
            return await ctx.send("Response must be 1800 characters or fewer.",)
        await self.bot.db.execute("INSERT INTO custom_commands VALUES (?,?,?) ON CONFLICT(guild_id,name) DO UPDATE SET response=excluded.response", (ctx.guild.id, name, response))
        await ctx.send(f"Custom command `{ctx.prefix}{name}` saved. Use `,custom_run` with that name.",)

    @commands.command(name="custom_run", help="Run a server custom command.")
    async def run_custom(self, ctx: commands.Context, name: str):
        row = await self.bot.db.fetchone("SELECT response FROM custom_commands WHERE guild_id=? AND name=?", (ctx.guild.id, name.lower()))
        if not row: return await ctx.send("That custom command doesn't exist.",)
        safe = row["response"].replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
        await ctx.send(safe, allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="custom_remove", help="Delete a server custom command.")
    @commands.has_permissions(manage_guild=True)
    async def remove(self, ctx: commands.Context, name: str):
        await self.bot.db.execute("DELETE FROM custom_commands WHERE guild_id=? AND name=?", (ctx.guild.id, name.lower()))
        await ctx.send(f"Deleted `{name}` if it existed.",)


    @commands.command(name="embed_template_save", help="Save an embed template for this server.")
    @commands.has_permissions(manage_messages=True)
    async def template_save(self, ctx: commands.Context, name: str, title: str,
                            *, description: str, color: str = "5865F2"):
        name = name.lower()
        if not re.fullmatch(r"[a-z0-9_-]{2,32}", name):
            return await ctx.send("Use 2–32 letters, numbers, underscores or hyphens.",)
        if len(title) > 256 or len(description) > 4000:
            return await ctx.send("Title or description is too long.",)
        try: int(color.replace("#", ""), 16)
        except ValueError: return await ctx.send("Color must be a hex value such as `5865F2`.",)
        await self.bot.db.execute(
            "INSERT INTO embed_templates VALUES (?,?,?,?,?) ON CONFLICT(guild_id,name) DO UPDATE SET title=excluded.title,help=excluded.description,color=excluded.color",
            (ctx.guild.id, name, title, description, color.replace("#", "")))
        await ctx.send(f"Saved embed template `{name}`.",)

    @commands.command(name="embed_template_send", help="Send a saved embed template.")
    @commands.has_permissions(manage_messages=True)
    async def template_send(self, ctx: commands.Context, name: str,
                            channel: discord.TextChannel = None):
        row = await self.bot.db.fetchone("SELECT title,description,color FROM embed_templates WHERE guild_id=? AND name=?",
                                         (ctx.guild.id, name.lower()))
        if not row:
            return await ctx.send("Template not found.",)
        target = channel or ctx.channel
        embed = discord.Embed(title=row["title"], help=row["description"],
                              color=int(row["color"], 16))
        await target.send(embed=embed)
        await ctx.send(f"Sent `{name}` to {target.mention}.",)

    @commands.command(name="embed_template_delete", help="Delete a saved embed template.")
    @commands.has_permissions(manage_messages=True)
    async def template_delete(self, ctx: commands.Context, name: str):
        await self.bot.db.execute("DELETE FROM embed_templates WHERE guild_id=? AND name=?",
                                  (ctx.guild.id, name.lower()))
        await ctx.send(f"Deleted `{name}` if it existed.",)

async def setup(bot): await bot.add_cog(Custom(bot))
