import discord
from discord.ext import commands


class PollView(discord.ui.View):
    def __init__(self, options):
        super().__init__(timeout=86400)
        self.options = options
        self.votes = {}
        for index, option in enumerate(options):
            button = discord.ui.Button(
                label=option[:80],
                style=discord.ButtonStyle.secondary,
                custom_id=f"onyx_poll_{index}"
            )

            async def callback(interaction, choice=index):
                self.votes[interaction.user.id] = choice
                await interaction.response.send_message(
                    f"Your vote for **{self.options[choice]}** was recorded.",
                    ephemeral=True
                )

            button.callback = callback
            self.add_item(button)


class Engagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(
        name="poll",
        help="Create a poll: ,poll Question | Option 1 | Option 2"
    )
    @commands.has_permissions(manage_messages=True)
    async def poll(self, ctx, *, text: str):
        parts = [part.strip() for part in text.split("|")]
        if len(parts) < 3 or len(parts) > 5 or any(not part for part in parts):
            return await ctx.send(
                "Use `,poll Question | Option 1 | Option 2` (up to four options)."
            )

        embed = discord.Embed(
            title=parts[0][:256],
            description="\\n".join(
                f"**{index}.** {option}"
                for index, option in enumerate(parts[1:], 1)
            ),
            color=discord.Color.dark_grey()
        )
        await ctx.send(
            embed=embed,
            view=PollView(parts[1:]),
            allowed_mentions=discord.AllowedMentions.none()
        )

    @commands.command(
        name="autoresponse_add",
        help="Save a keyword response: ,autoresponse_add keyword | response"
    )
    @commands.has_permissions(manage_guild=True)
    async def autoresponse_add(self, ctx, *, entry: str):
        parts = [part.strip() for part in entry.split("|", 1)]
        if len(parts) != 2 or not all(parts):
            return await ctx.send("Use `,autoresponse_add keyword | response`.")
        trigger, response = parts
        if len(trigger) > 80 or len(response) > 1500:
            return await ctx.send(
                "Keyword limit is 80 characters; response limit is 1,500."
            )
        await self.bot.db.execute(
            "INSERT INTO onyx_autoresponses (guild_id,trigger,response) VALUES (?,?,?) "
            "ON CONFLICT(guild_id,trigger) DO UPDATE SET response=excluded.response",
            (ctx.guild.id, trigger.casefold(), response)
        )
        await ctx.send(f"Saved autoresponse for **{trigger}**.")

    @commands.command(
        name="autoresponse_remove",
        help="Remove a saved keyword response."
    )
    @commands.has_permissions(manage_guild=True)
    async def autoresponse_remove(self, ctx, *, trigger: str):
        await self.bot.db.execute(
            "DELETE FROM onyx_autoresponses WHERE guild_id=? AND trigger=?",
            (ctx.guild.id, trigger.casefold())
        )
        await ctx.send(f"Removed autoresponse for **{trigger}** (if it existed).")

    @commands.command(
        name="autoresponse_list",
        help="List saved keyword responses."
    )
    @commands.has_permissions(manage_guild=True)
    async def autoresponse_list(self, ctx):
        rows = await self.bot.db.fetchall(
            "SELECT trigger FROM onyx_autoresponses WHERE guild_id=? ORDER BY trigger",
            (ctx.guild.id,)
        )
        listing = "\\n".join(f"• `{row['trigger']}`" for row in rows)
        await ctx.send("**Saved triggers:**\n" + (listing or "None"))

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot:
            return
        rows = await self.bot.db.fetchall(
            "SELECT trigger,response FROM onyx_autoresponses WHERE guild_id=?",
            (message.guild.id,)
        )
        content = message.content.casefold()
        for row in rows:
            if row["trigger"] in content:
                await message.channel.send(
                    row["response"],
                    allowed_mentions=discord.AllowedMentions.none()
                )
                break


async def setup(bot):
    await bot.add_cog(Engagement(bot))
