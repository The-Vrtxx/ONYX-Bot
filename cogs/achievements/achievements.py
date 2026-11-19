import discord
from discord.ext import commands

from cogs.achievements.definitions import ACHIEVEMENTS, CATEGORIES
from cogs.achievements.engine import ensure_tables, get_unlocks, get_titles, get_equipped_title, get_metric

PAGE_SIZE = 5
ONYX_COLOR = discord.Color.from_rgb(44, 38, 67)


class AchievementView(discord.ui.View):
    """Paged achievement browser with category filters and individual detail pages."""

    def __init__(self, cog, viewer_id, target_id, category="all", page=0, detail_id=None):
        super().__init__(timeout=180)
        self.cog = cog
        self.viewer_id = viewer_id
        self.target_id = target_id
        self.category = category
        self.page = page
        self.detail_id = detail_id
        self.build_components()

    async def interaction_check(self, interaction):
        if interaction.user.id != self.viewer_id:
            await interaction.response.send_message("This achievement menu belongs to another member.", ephemeral=True)
            return False
        return True

    def build_components(self):
        category_options = [discord.SelectOption(label="All Achievements", value="all")]
        category_options.extend(
            discord.SelectOption(label=label, value=key, default=self.category == key)
            for key, (label, _) in CATEGORIES.items()
        )
        category_options[0].default = self.category == "all"
        category_select = discord.ui.Select(placeholder="Choose a category", options=category_options, row=0)

        async def choose_category(interaction):
            self.category = category_select.values[0]
            self.page = 0
            self.detail_id = None
            await self.refresh(interaction)

        category_select.callback = choose_category
        self.add_item(category_select)

        if self.detail_id is None:
            items = self.cog.get_category_items(self.category)
            start = self.page * PAGE_SIZE
            page_items = items[start:start + PAGE_SIZE]
            if page_items:
                options = [
                    discord.SelectOption(
                        label=data["name"][:100], value=achievement_id,
                        description=data.get("description", "View achievement details")[:100],
                        emoji=data.get("icon"),
                    )
                    for achievement_id, data in page_items
                ]
                achievement_select = discord.ui.Select(
                    placeholder="Select an achievement for details", options=options, row=1
                )

                async def choose_achievement(interaction):
                    self.detail_id = achievement_select.values[0]
                    await self.refresh(interaction)

                achievement_select.callback = choose_achievement
                self.add_item(achievement_select)

            previous = discord.ui.Button(
                label="Previous", style=discord.ButtonStyle.secondary,
                disabled=self.page <= 0, row=2
            )
            next_button = discord.ui.Button(
                label="Next", style=discord.ButtonStyle.secondary,
                disabled=start + PAGE_SIZE >= len(items), row=2
            )

            async def go_previous(interaction):
                self.page = max(0, self.page - 1)
                await self.refresh(interaction)

            async def go_next(interaction):
                self.page += 1
                await self.refresh(interaction)

            previous.callback = go_previous
            next_button.callback = go_next
            self.add_item(previous)
            self.add_item(next_button)
        else:
            back = discord.ui.Button(label="Back to achievements", style=discord.ButtonStyle.primary, row=2)

            async def go_back(interaction):
                self.detail_id = None
                await self.refresh(interaction)

            back.callback = go_back
            self.add_item(back)

    async def refresh(self, interaction):
        self.clear_items()
        self.build_components()
        embed = await self.cog.make_embed(self.target_id, self.category, self.page, self.detail_id)
        await interaction.response.edit_message(embed=embed, view=self)


class Achievements(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await ensure_tables(self.bot.db)

    def get_category_items(self, category):
        if category == "all":
            return list(ACHIEVEMENTS.items())
        return list(CATEGORIES.get(category, ("", {}))[1].items())

    async def make_embed(self, uid, category="all", page=0, detail_id=None):
        unlock_rows = await get_unlocks(self.bot.db, uid)
        unlocked = {row["achievement_id"] for row in unlock_rows}
        titles = await get_titles(self.bot.db, uid)
        equipped = await get_equipped_title(self.bot.db, uid)

        if detail_id:
            return await self.make_detail_embed(uid, detail_id, unlocked)

        items = self.get_category_items(category)
        total_pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(0, min(page, total_pages - 1))
        page_items = items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
        category_name = "All Achievements" if category == "all" else CATEGORIES[category][0]
        embed = discord.Embed(
            title=f"🏆 ONYX Achievements — {category_name}",
            description=(
                f"**{len(unlocked)}/{len(ACHIEVEMENTS)} unlocked**\n"
                "Select an achievement below to see its requirements, rewards, and progress."
            ),
            color=ONYX_COLOR,
        )
        for achievement_id, data in page_items:
            status = "✅ Unlocked" if achievement_id in unlocked else "🔒 Locked"
            progress = await self.progress_text(uid, data)
            embed.add_field(
                name=f"{data.get('icon', '🏆')} {data['name']} · {status}",
                value=f"{data.get('description', 'No description available.')}\n**Progress:** {progress}",
                inline=False,
            )
        embed.add_field(
            name="Your Titles",
            value=f"Equipped: **{equipped or 'None'}**\nUnlocked: {', '.join(titles) or 'None'}",
            inline=False,
        )
        embed.set_footer(
            text=f"Page {page + 1}/{total_pages} • {len(page_items)} shown • Secret achievements are separate (,secrets)"
        )
        return embed

    async def progress_text(self, uid, data):
        metric = data.get("metric")
        if not metric:
            return "Progress not configured"
        current = await get_metric(self.bot.db, uid, metric)
        target = int(data.get("target", 1))
        text = f"{min(current, target):,}/{target:,}"
        extra = data.get("extra_metric")
        if extra:
            extra_current = await get_metric(self.bot.db, uid, extra)
            extra_target = int(data.get("extra_target", 1))
            text += f" • Additional requirement: {min(extra_current, extra_target):,}/{extra_target:,}"
        return text

    async def make_detail_embed(self, uid, achievement_id, unlocked):
        data = ACHIEVEMENTS.get(achievement_id)
        if not data:
            return discord.Embed(title="Achievement not found", description="That achievement could not be found.", color=ONYX_COLOR)
        is_unlocked = achievement_id in unlocked
        progress = await self.progress_text(uid, data)
        embed = discord.Embed(
            title=f"{data.get('icon', '🏆')} {data['name']}",
            description=data.get("description", "No description available."),
            color=discord.Color.green() if is_unlocked else ONYX_COLOR,
        )
        embed.add_field(name="Category", value=CATEGORIES[data["category"]][0], inline=True)
        embed.add_field(name="Tier", value=data.get("tier", "Standard"), inline=True)
        embed.add_field(name="Status", value="✅ Unlocked" if is_unlocked else "🔒 Locked", inline=True)
        embed.add_field(name="How to unlock", value=data.get("description", "See achievement requirement above."), inline=False)
        embed.add_field(name="Your progress", value=progress, inline=False)
        reward = int(data.get("reward", 0) or 0)
        reward_text = f"💰 {reward:,} Credits" if reward else "No Credit reward"
        if data.get("title"):
            reward_text += f"\n🏷️ Title: **{data['title']}**"
        embed.add_field(name="Rewards", value=reward_text, inline=False)
        embed.set_footer(text="Progress reflects the activity ONYX has recorded for your account.")
        return embed

    @commands.command(name="achievements", help="Browse your ONYX achievements, progress, and rewards.")
    async def achievements(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        view = AchievementView(self, ctx.author.id, member.id)
        await ctx.send(embed=await self.make_embed(member.id), view=view)

    @commands.command(name="achievementleaderboard", aliases=["achievementlb"], help="View the ONYX achievement leaderboard.")
    async def leaderboard(self, ctx):
        rows = await self.bot.db.fetchall(
            "SELECT user_id,COUNT(*) AS total FROM onyx_achievement_unlocks "
            "GROUP BY user_id ORDER BY total DESC LIMIT 10"
        )
        lines = [f"`{i}.` <@{row['user_id']}> — **{row['total']}**" for i, row in enumerate(rows, 1)]
        await ctx.send("🏆 **ONYX Achievement Leaderboard**\n" + ("\n".join(lines) or "No unlocks yet."))

    @commands.command(name="equiptitle", help="Equip an achievement title you have earned.")
    async def equiptitle(self, ctx, *, title: str):
        titles = await get_titles(self.bot.db, ctx.author.id)
        match = next((item for item in titles if item.casefold() == title.casefold()), None)
        if not match:
            return await ctx.send("You haven't unlocked that title.")
        await self.bot.db.execute(
            "INSERT INTO onyx_achievement_equipped(user_id,title) VALUES(?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET title=excluded.title",
            (ctx.author.id, match),
        )
        await ctx.send(f"✨ Equipped **{match}**.")

    @commands.command(name="unequiptitle", help="Remove your equipped achievement title.")
    async def unequiptitle(self, ctx):
        await self.bot.db.execute("DELETE FROM onyx_achievement_equipped WHERE user_id=?", (ctx.author.id,))
        await ctx.send("Title unequipped.")

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        if ctx.author.bot:
            return
        try:
            from cogs.achievements.engine import record_command
            from cogs.achievements.secrets import secret_event
            await record_command(self.bot, ctx)
            await secret_event(self.bot, ctx.author, "command", ctx.guild, ctx.command.qualified_name.split()[-1].casefold())
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        try:
            from cogs.achievements.engine import record_message
            from cogs.achievements.secrets import secret_event
            await record_message(self.bot, message)
            await secret_event(self.bot, message.author, "message", message.guild)
        except Exception:
            pass


async def setup(bot):
    await bot.add_cog(Achievements(bot))
