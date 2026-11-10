import discord
from discord.ext import commands

class Prefix(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @commands.group(name="prefix", invoke_without_command=True)
    async def prefix_group(self, ctx):
        await ctx.send(f"Use `{ctx.prefix}prefix show`, `{ctx.prefix}prefix set <new_prefix>`, or `{ctx.prefix}prefix reset`.")

    @prefix_group.command(name="show")
    async def show_prefix(self, ctx):
        if ctx.guild is None: return await ctx.send("Prefixes are configured separately for each server.")
        row = await self.bot.db.fetchone("SELECT prefix FROM guild_settings WHERE guild_id=?", (ctx.guild.id,))
        prefix = row["prefix"] if row and row["prefix"] else ","
        await ctx.send(f"This server's ONYX prefix is `{prefix}`.")

    @prefix_group.command(name="set")
    @commands.has_permissions(manage_guild=True)
    async def set_prefix(self, ctx, *, new_prefix: str):
        new_prefix = new_prefix.strip()
        if not 1 <= len(new_prefix) <= 5 or any(char.isspace() for char in new_prefix):
            return await ctx.send("Choose a prefix between 1 and 5 characters, with no spaces.")
        await self.bot.db.execute("INSERT INTO guild_settings (guild_id,prefix) VALUES (?,?) ON CONFLICT(guild_id) DO UPDATE SET prefix=excluded.prefix", (ctx.guild.id, new_prefix))
        await ctx.send(f"ONYX's prefix for this server is now `{new_prefix}`.")

    @prefix_group.command(name="reset")
    @commands.has_permissions(manage_guild=True)
    async def reset_prefix(self, ctx):
        await self.bot.db.execute("INSERT INTO guild_settings (guild_id,prefix) VALUES (?,',') ON CONFLICT(guild_id) DO UPDATE SET prefix=excluded.prefix", (ctx.guild.id,))
        await ctx.send("ONYX's prefix has been reset to `,`.")

async def setup(bot): await bot.add_cog(Prefix(bot))
