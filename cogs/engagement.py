import discord
from discord.ext import commands

class PollView(discord.ui.View):
    def __init__(self, options):
        super().__init__(timeout=86400)
        self.options = options
        self.votes = {}
        for i, option in enumerate(options):
            button = discord.ui.Button(label=option[:80], style=discord.ButtonStyle.secondary, custom_id=f"onyx_poll_{i}")
            async def callback(interaction, choice=i):
                self.votes[interaction.user.id] = choice
                await interaction.response.send_message(f"Vote recorded for **{self.options[choice]}**.", ephemeral=True)
            button.callback = callback
            self.add_item(button)

class Engagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.responses = {}

    @commands.command(name="poll", help="Create a poll: ,poll Question | Option 1 | Option 2")
    @commands.has_permissions(manage_messages=True)
    async def poll(self, ctx, *, text: str):
        parts = [p.strip() for p in text.split("|")]
        if len(parts) < 3 or len(parts) > 5 or any(not p for p in parts):
            return await ctx.send("Use `,poll Question | Option 1 | Option 2` (up to four options).")
        e = discord.Embed(title=parts[0][:256], description="\n".join(f"**{i}.** {p}" for i, p in enumerate(parts[1:], 1)), color=discord.Color.dark_grey())
        await ctx.send(embed=e, view=PollView(parts[1:]), allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="autoresponse_add", help="Add a keyword response: ,autoresponse add keyword | response")
    @commands.has_permissions(manage_guild=True)
    async def autoresponse_add(self, ctx, *, entry: str):
        parts = [p.strip() for p in entry.split("|", 1)]
        if len(parts) != 2 or not all(parts):
            return await ctx.send("Use `,autoresponse add keyword | response`.")
        if len(parts[0]) > 80 or len(parts[1]) > 1500:
            return await ctx.send("Keyword limit is 80 characters; response limit is 1,500.")
        self.responses[(ctx.guild.id, parts[0].casefold())] = parts[1]
        await ctx.send(f"Autoresponse added for **{parts[0]}**. It resets when ONYX restarts.")

    @commands.command(name="autoresponse_remove", help="Remove a keyword response.")
    @commands.has_permissions(manage_guild=True)
    async def autoresponse_remove(self, ctx, *, trigger: str):
        removed = self.responses.pop((ctx.guild.id, trigger.casefold()), None)
        await ctx.send("Autoresponse removed." if removed else "Keyword not found.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot:
            return
        for (guild_id, trigger), response in list(self.responses.items()):
            if guild_id == message.guild.id and trigger in message.content.casefold():
                await message.channel.send(response, allowed_mentions=discord.AllowedMentions.none())
                break

async def setup(bot):
    await bot.add_cog(Engagement(bot))
