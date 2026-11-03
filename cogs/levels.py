import random
import time
import discord
from discord.ext import commands

COLOR = discord.Color.from_rgb(44, 38, 67)


def xp_needed(level, base=100, linear=50, quadratic=5):
    return max(1, int(base + linear * level + quadratic * level * level))


def progress_bar(current, required, size=12):
    ratio = min(1.0, max(0.0, current / required)) if required else 1.0
    filled = int(ratio * size)
    return "▰" * filled + "▱" * (size - filled)


class ConfirmResetView(discord.ui.View):
    def __init__(self, cog, guild_id, actor_id, member_id=None):
        super().__init__(timeout=30)
        self.cog, self.guild_id = cog, guild_id
        self.actor_id, self.member_id = actor_id, member_id
        self.done = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.actor_id:
            await interaction.response.send_message(
                "Only the administrator who started this reset can confirm it.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Confirm reset", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction, button):
        if self.done:
            return await interaction.response.send_message("This reset was already handled.", ephemeral=True)
        self.done = True
        if self.member_id is None:
            await self.cog.bot.db.execute("DELETE FROM levels WHERE guild_id=?", (self.guild_id,))
            result = "All leveling data for this server has been reset."
        else:
            await self.cog.bot.db.execute(
                "DELETE FROM levels WHERE guild_id=? AND user_id=?",
                (self.guild_id, self.member_id)
            )
            result = f"Leveling data for <@{self.member_id}> has been reset."
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content=f"✅ {result}", view=self)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction, button):
        self.done = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="Reset cancelled. No leveling data was changed.", view=self
        )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cooldowns = {}

    async def cog_load(self):
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_level_settings (
                guild_id BIGINT PRIMARY KEY,
                min_xp INTEGER NOT NULL DEFAULT 15,
                max_xp INTEGER NOT NULL DEFAULT 25,
                cooldown_seconds INTEGER NOT NULL DEFAULT 60,
                base_xp INTEGER NOT NULL DEFAULT 100,
                linear_xp INTEGER NOT NULL DEFAULT 50,
                quadratic_xp INTEGER NOT NULL DEFAULT 5,
                announcement_message TEXT NOT NULL DEFAULT '🎉 {mention} reached **level {level}**!'
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_level_ignored_channels (
                guild_id BIGINT NOT NULL,
                channel_id BIGINT NOT NULL,
                PRIMARY KEY (guild_id, channel_id)
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS level_rewards (
                guild_id BIGINT NOT NULL,
                level INTEGER NOT NULL,
                role_id BIGINT NOT NULL,
                PRIMARY KEY (guild_id, level)
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_level_announcement_settings (
                guild_id BIGINT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1
            )
        """)

    async def settings_for(self, guild_id):
        row = await self.bot.db.fetchone(
            "SELECT * FROM onyx_level_settings WHERE guild_id=?", (guild_id,)
        )
        if row is None:
            await self.bot.db.execute(
                "INSERT INTO onyx_level_settings (guild_id) VALUES (?) "
                "ON CONFLICT(guild_id) DO NOTHING", (guild_id,)
            )
            row = await self.bot.db.fetchone(
                "SELECT * FROM onyx_level_settings WHERE guild_id=?", (guild_id,)
            )
        return row

    async def level_row(self, guild_id, user_id):
        return await self.bot.db.fetchone(
            "SELECT xp,level FROM levels WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        )

    async def total_xp(self, guild_id, user_id, settings):
        row = await self.level_row(guild_id, user_id)
        if not row:
            return 0
        total = row["xp"]
        for lvl in range(row["level"]):
            total += xp_needed(lvl, settings["base_xp"], settings["linear_xp"], settings["quadratic_xp"])
        return total

    async def give_rewards(self, member, level):
        rows = await self.bot.db.fetchall(
            "SELECT role_id FROM level_rewards WHERE guild_id=? AND level<=? ORDER BY level",
            (member.guild.id, level)
        )
        added = []
        me = member.guild.me
        if me is None:
            return added
        for row in rows:
            role = member.guild.get_role(row["role_id"])
            if not role or role in member.roles or role.is_default() or role.managed or role >= me.top_role:
                continue
            try:
                await member.add_roles(role, reason=f"ONYX level reward at level {level}")
                added.append(role)
            except (discord.Forbidden, discord.HTTPException):
                continue
        return added

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot or message.webhook_id:
            return
        if len(message.content.strip()) < 3:
            return
        try:
            if (await self.bot.get_context(message)).valid:
                return
        except Exception:
            pass

        gid = message.guild.id
        settings = await self.settings_for(gid)
        enabled = await self.bot.db.fetchone(
            "SELECT xp_enabled FROM guild_settings WHERE guild_id=?", (gid,)
        )
        if enabled and not enabled["xp_enabled"]:
            return
        ignored = await self.bot.db.fetchone(
            "SELECT 1 FROM onyx_level_ignored_channels WHERE guild_id=? AND channel_id=?",
            (gid, message.channel.id)
        )
        if ignored:
            return

        key = (gid, message.author.id)
        now = time.monotonic()
        if now - self.cooldowns.get(key, 0) < settings["cooldown_seconds"]:
            return
        self.cooldowns[key] = now

        gained = random.randint(settings["min_xp"], settings["max_xp"])
        row = await self.level_row(gid, message.author.id)
        xp = (row["xp"] if row else 0) + gained
        old_level = row["level"] if row else 0
        new_level = old_level
        while xp >= xp_needed(new_level, settings["base_xp"], settings["linear_xp"], settings["quadratic_xp"]):
            xp -= xp_needed(new_level, settings["base_xp"], settings["linear_xp"], settings["quadratic_xp"])
            new_level += 1

        await self.bot.db.execute(
            "INSERT INTO levels (guild_id,user_id,xp,level) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET xp=excluded.xp,level=excluded.level",
            (gid, message.author.id, xp, new_level)
        )
        if new_level > old_level:
            rewards = await self.give_rewards(message.author, new_level)
            announcement_setting = await self.bot.db.fetchone(
                "SELECT enabled FROM onyx_level_announcement_settings WHERE guild_id=?",
                (gid,)
            )
            announcements_enabled = (
                announcement_setting["enabled"] if announcement_setting else 1
            )
            if not announcements_enabled:
                return
            config = await self.bot.db.fetchone(
                "SELECT levelup_channel_id FROM guild_settings WHERE guild_id=?", (gid,)
            )
            channel = message.guild.get_channel(config["levelup_channel_id"]) if config and config["levelup_channel_id"] else message.channel
            if channel:
                announcement = settings["announcement_message"]
                replacements = {
                    "{mention}": message.author.mention,
                    "{user}": discord.utils.escape_markdown(message.author.display_name),
                    "{level}": str(new_level),
                    "{server}": discord.utils.escape_markdown(message.guild.name)
                }
                for token, value in replacements.items():
                    announcement = announcement.replace(token, value)
                if rewards:
                    announcement += "\n🎁 Reward unlocked: " + ", ".join(role.mention for role in rewards)
                try:
                    await channel.send(
                        announcement,
                        allowed_mentions=discord.AllowedMentions(users=True, roles=True)
                    )
                except discord.HTTPException:
                    pass

    @commands.command(name="rank", aliases=["level"], help="View your rank or another member's rank.")
    @commands.guild_only()
    async def rank(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        settings = await self.settings_for(ctx.guild.id)
        row = await self.level_row(ctx.guild.id, member.id)
        xp, level = (row["xp"], row["level"]) if row else (0, 0)
        needed = xp_needed(level, settings["base_xp"], settings["linear_xp"], settings["quadratic_xp"])
        ahead = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM levels WHERE guild_id=? AND (level>? OR (level=? AND xp>?))",
            (ctx.guild.id, level, level, xp)
        )
        total = await self.total_xp(ctx.guild.id, member.id, settings)
        embed = discord.Embed(title=f"{member.display_name} • Rank", color=COLOR)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Level", value=f"**{level:,}**")
        embed.add_field(name="Total XP", value=f"**{total:,}**")
        embed.add_field(name="Server rank", value=f"**#{(ahead['n'] if ahead else 0) + 1:,}**")
        embed.add_field(
            name=f"Progress • {xp:,}/{needed:,} XP",
            value=f"`{progress_bar(xp, needed)}` **{xp / needed * 100:.1f}%**",
            inline=False
        )
        embed.set_footer(text=f"ONYX Levels • {ctx.guild.name}")
        await ctx.send(embed=embed)

    @commands.command(name="leaderboard", aliases=["levels_top"], help="Show the server's top 10 members.")
    @commands.guild_only()
    async def leaderboard(self, ctx):
        rows = await self.bot.db.fetchall(
            "SELECT user_id,level,xp FROM levels WHERE guild_id=? ORDER BY level DESC,xp DESC LIMIT 10",
            (ctx.guild.id,)
        )
        if not rows:
            return await ctx.send("No level data yet. Start chatting to earn XP!")
        lines = []
        for i, row in enumerate(rows, 1):
            member = ctx.guild.get_member(row["user_id"])
            name = discord.utils.escape_markdown(member.display_name) if member else f"User {row['user_id']}"
            lines.append(f"**{i}.** {name} — Level **{row['level']:,}** • {row['xp']:,} XP")
        embed = discord.Embed(title="🏆 ONYX • Level Leaderboard", description="\n".join(lines), color=COLOR)
        embed.set_footer(text=f"{ctx.guild.name} • Top 10")
        await ctx.send(embed=embed)

    @commands.group(name="levels", invoke_without_command=True, help="View leveling status and admin settings.")
    @commands.guild_only()
    async def levels(self, ctx):
        s = await self.settings_for(ctx.guild.id)
        enabled = await self.bot.db.fetchone(
            "SELECT xp_enabled FROM guild_settings WHERE guild_id=?", (ctx.guild.id,)
        )
        active = enabled["xp_enabled"] if enabled else 1
        embed = discord.Embed(title="ONYX • Leveling Settings", color=COLOR)
        embed.add_field(name="Status", value="Enabled" if active else "Disabled")
        embed.add_field(name="XP per message", value=f"{s['min_xp']}–{s['max_xp']}")
        embed.add_field(name="Cooldown", value=f"{s['cooldown_seconds']} seconds")
        embed.add_field(name="Level curve", value=f"{s['base_xp']} + {s['linear_xp']}L + {s['quadratic_xp']}L²", inline=False)
        embed.add_field(
            name="Admin commands",
            value=(
                "`,levels enable/disable`\n`,levels rate <min> <max>`\n"
                "`,levels cooldown <seconds>`\n`,levels curve <base> <linear> <quadratic>`\n"
                "`,levels channel #channel` or `off`\n`,levels message <text>`\n"
                "`,levels ignore add/remove/list #channel`\n`,levels reward add/remove/list ...`\n"
                "`,levels xp add/set/remove @member <amount>`\n`,levels reset @member` or `,levels reset all`"
            ),
            inline=False
        )
        await ctx.send(embed=embed)

    @levels.command(name="announcements")
    @commands.has_guild_permissions(manage_guild=True)
    async def announcements(self, ctx, setting: str):
        setting = setting.casefold()
        if setting not in ("on", "off", "enable", "disable"):
            return await ctx.send(
                f"Use `{ctx.prefix}levels announcements on` or "
                f"`{ctx.prefix}levels announcements off`."
            )
        enabled = setting in ("on", "enable")
        await self.bot.db.execute(
            "INSERT INTO onyx_level_announcement_settings (guild_id,enabled) VALUES (?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled",
            (ctx.guild.id, int(enabled))
        )
        await ctx.send(
            "✅ Level-up messages are now enabled."
            if enabled else
            "🔕 Level-up messages are now disabled. XP and level rewards will continue working."
        )

    @levels.command(name="enable")
    @commands.has_guild_permissions(manage_guild=True)
    async def enable(self, ctx):
        await self.bot.db.execute(
            "INSERT INTO guild_settings (guild_id,xp_enabled) VALUES (?,1) "
            "ON CONFLICT(guild_id) DO UPDATE SET xp_enabled=1", (ctx.guild.id,)
        )
        await ctx.send("✅ Leveling enabled.")

    @levels.command(name="disable")
    @commands.has_guild_permissions(manage_guild=True)
    async def disable(self, ctx):
        await self.bot.db.execute(
            "INSERT INTO guild_settings (guild_id,xp_enabled) VALUES (?,0) "
            "ON CONFLICT(guild_id) DO UPDATE SET xp_enabled=0", (ctx.guild.id,)
        )
        await ctx.send("⏸️ Leveling disabled.")

    @levels.command(name="rate")
    @commands.has_guild_permissions(manage_guild=True)
    async def rate(self, ctx, minimum: int, maximum: int):
        if not 1 <= minimum <= maximum <= 1000:
            return await ctx.send("Use values from 1–1000, with minimum no higher than maximum.")
        await self.bot.db.execute(
            "INSERT INTO onyx_level_settings (guild_id,min_xp,max_xp) VALUES (?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET min_xp=excluded.min_xp,max_xp=excluded.max_xp",
            (ctx.guild.id, minimum, maximum)
        )
        await ctx.send(f"✅ XP rate set to **{minimum}–{maximum} XP** per eligible message.")

    @levels.command(name="cooldown")
    @commands.has_guild_permissions(manage_guild=True)
    async def cooldown(self, ctx, seconds: int):
        if not 5 <= seconds <= 3600:
            return await ctx.send("Cooldown must be between 5 and 3,600 seconds.")
        await self.bot.db.execute(
            "INSERT INTO onyx_level_settings (guild_id,cooldown_seconds) VALUES (?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET cooldown_seconds=excluded.cooldown_seconds",
            (ctx.guild.id, seconds)
        )
        await ctx.send(f"✅ XP cooldown set to **{seconds} seconds**.")

    @levels.command(name="curve")
    @commands.has_guild_permissions(manage_guild=True)
    async def curve(self, ctx, base: int, linear: int, quadratic: int):
        if not 1 <= base <= 100000 or not 0 <= linear <= 100000 or not 0 <= quadratic <= 10000:
            return await ctx.send("Use base 1–100,000, linear 0–100,000, and quadratic 0–10,000.")
        await self.bot.db.execute(
            "INSERT INTO onyx_level_settings (guild_id,base_xp,linear_xp,quadratic_xp) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET base_xp=excluded.base_xp,linear_xp=excluded.linear_xp,quadratic_xp=excluded.quadratic_xp",
            (ctx.guild.id, base, linear, quadratic)
        )
        await ctx.send(f"✅ Level curve: **{base} + {linear}L + {quadratic}L² XP**.")

    @levels.command(name="channel")
    @commands.has_guild_permissions(manage_guild=True)
    async def channel(self, ctx, channel: discord.TextChannel = None):
        await self.bot.db.execute(
            "INSERT INTO guild_settings (guild_id,levelup_channel_id) VALUES (?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET levelup_channel_id=excluded.levelup_channel_id",
            (ctx.guild.id, channel.id if channel else None)
        )
        await ctx.send(
            f"✅ Level-up announcements set to {channel.mention}."
            if channel else "✅ Level-up announcements will appear where the member levels up."
        )

    @levels.command(name="message")
    @commands.has_guild_permissions(manage_guild=True)
    async def message(self, ctx, *, text: str):
        if len(text) > 1000:
            return await ctx.send("Announcement messages are limited to 1,000 characters.")
        import re
        tokens = set(re.findall(r"\{[^{}]+\}", text))
        allowed = {"{mention}", "{user}", "{level}", "{server}"}
        if tokens - allowed:
            return await ctx.send("Allowed placeholders: `{mention}`, `{user}`, `{level}`, `{server}`.")
        await self.bot.db.execute(
            "INSERT INTO onyx_level_settings (guild_id,announcement_message) VALUES (?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET announcement_message=excluded.announcement_message",
            (ctx.guild.id, text)
        )
        await ctx.send("✅ Level-up announcement updated.")

    @levels.group(name="ignore", invoke_without_command=True)
    @commands.has_guild_permissions(manage_guild=True)
    async def ignore(self, ctx):
        await ctx.send(f"Use `{ctx.prefix}levels ignore add/remove/list #channel`.")

    @ignore.command(name="add")
    @commands.has_guild_permissions(manage_guild=True)
    async def ignore_add(self, ctx, channel: discord.TextChannel):
        await self.bot.db.execute(
            "INSERT INTO onyx_level_ignored_channels (guild_id,channel_id) VALUES (?,?) ON CONFLICT DO NOTHING",
            (ctx.guild.id, channel.id)
        )
        await ctx.send(f"🚫 {channel.mention} will no longer award XP.")

    @ignore.command(name="remove")
    @commands.has_guild_permissions(manage_guild=True)
    async def ignore_remove(self, ctx, channel: discord.TextChannel):
        await self.bot.db.execute(
            "DELETE FROM onyx_level_ignored_channels WHERE guild_id=? AND channel_id=?",
            (ctx.guild.id, channel.id)
        )
        await ctx.send(f"✅ XP is enabled again in {channel.mention}.")

    @ignore.command(name="list")
    @commands.has_guild_permissions(manage_guild=True)
    async def ignore_list(self, ctx):
        rows = await self.bot.db.fetchall(
            "SELECT channel_id FROM onyx_level_ignored_channels WHERE guild_id=?", (ctx.guild.id,)
        )
        desc = "\n".join(f"• <#{r['channel_id']}>" for r in rows) or "No ignored channels."
        await ctx.send(embed=discord.Embed(title="ONYX • XP Ignored Channels", description=desc, color=COLOR))

    @levels.group(name="reward", invoke_without_command=True)
    @commands.has_guild_permissions(manage_guild=True)
    async def reward(self, ctx):
        await ctx.send(f"Use `{ctx.prefix}levels reward add <level> @role`, `remove <level>`, or `list`.")

    @reward.command(name="add")
    @commands.has_guild_permissions(manage_guild=True)
    async def reward_add(self, ctx, level: int, role: discord.Role):
        me = ctx.guild.me
        if not 1 <= level <= 10000:
            return await ctx.send("Reward level must be between 1 and 10,000.")
        if role.is_default() or role.managed or not me or role >= me.top_role:
            return await ctx.send("That role cannot be assigned by ONYX. Check role hierarchy.")
        await self.bot.db.execute(
            "INSERT INTO level_rewards (guild_id,level,role_id) VALUES (?,?,?) "
            "ON CONFLICT(guild_id,level) DO UPDATE SET role_id=excluded.role_id",
            (ctx.guild.id, level, role.id)
        )
        await ctx.send(f"🎁 {role.mention} is now the reward for level **{level}**.")

    @reward.command(name="remove")
    @commands.has_guild_permissions(manage_guild=True)
    async def reward_remove(self, ctx, level: int):
        await self.bot.db.execute(
            "DELETE FROM level_rewards WHERE guild_id=? AND level=?", (ctx.guild.id, level)
        )
        await ctx.send(f"Removed the reward for level **{level}**, if one existed.")

    @reward.command(name="list")
    @commands.has_guild_permissions(manage_guild=True)
    async def reward_list(self, ctx):
        rows = await self.bot.db.fetchall(
            "SELECT level,role_id FROM level_rewards WHERE guild_id=? ORDER BY level", (ctx.guild.id,)
        )
        desc = "\n".join(f"Level **{r['level']}** → <@&{r['role_id']}>" for r in rows) or "No rewards configured."
        await ctx.send(embed=discord.Embed(title="ONYX • Level Rewards", description=desc, color=COLOR))

    @levels.group(name="xp", invoke_without_command=True)
    @commands.has_guild_permissions(manage_guild=True)
    async def xp(self, ctx):
        await ctx.send(f"Use `{ctx.prefix}levels xp add/set/remove @member <amount>`.")

    async def change_xp(self, ctx, member, amount, mode):
        if not 1 <= amount <= 10_000_000:
            return await ctx.send("Amount must be between 1 and 10,000,000 XP.")
        s = await self.settings_for(ctx.guild.id)
        total = await self.total_xp(ctx.guild.id, member.id, s)
        if mode == "add":
            total += amount
        elif mode == "remove":
            total = max(0, total - amount)
        else:
            total = amount
        lvl, remaining = 0, total
        while remaining >= xp_needed(lvl, s["base_xp"], s["linear_xp"], s["quadratic_xp"]):
            remaining -= xp_needed(lvl, s["base_xp"], s["linear_xp"], s["quadratic_xp"])
            lvl += 1
            if lvl > 100000:
                break
        await self.bot.db.execute(
            "INSERT INTO levels (guild_id,user_id,xp,level) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET xp=excluded.xp,level=excluded.level",
            (ctx.guild.id, member.id, remaining, lvl)
        )
        verb = {"add": "Added", "set": "Set", "remove": "Removed"}[mode]
        await ctx.send(f"✅ {verb} XP for {member.mention}. New total: **{total:,} XP** (Level **{lvl}**).")

    @xp.command(name="add")
    @commands.has_guild_permissions(manage_guild=True)
    async def xp_add(self, ctx, member: discord.Member, amount: int):
        await self.change_xp(ctx, member, amount, "add")

    @xp.command(name="set")
    @commands.has_guild_permissions(manage_guild=True)
    async def xp_set(self, ctx, member: discord.Member, amount: int):
        await self.change_xp(ctx, member, amount, "set")

    @xp.command(name="remove")
    @commands.has_guild_permissions(manage_guild=True)
    async def xp_remove(self, ctx, member: discord.Member, amount: int):
        await self.change_xp(ctx, member, amount, "remove")

    @levels.command(name="reset")
    @commands.has_guild_permissions(manage_guild=True)
    async def reset(self, ctx, target: str = None):
        if target is None:
            return await ctx.send(f"Use `{ctx.prefix}levels reset @member` or `{ctx.prefix}levels reset all`.")
        if target.casefold() == "all":
            member_id = None
            description = "This permanently deletes **all leveling data** for this server."
        else:
            try:
                member = await commands.MemberConverter().convert(ctx, target)
            except commands.BadArgument:
                return await ctx.send("Mention a server member or use `all`.")
            member_id = member.id
            description = f"This permanently deletes the leveling data for {member.mention}."
        await ctx.send(
            embed=discord.Embed(title="⚠️ Confirm Leveling Reset", description=description, color=discord.Color.orange()),
            view=ConfirmResetView(self, ctx.guild.id, ctx.author.id, member_id)
        )

    @commands.command(name="levels_settings", aliases=["levelsettings"],
                       help="Legacy leveling toggle and announcement channel setting.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def levels_settings_legacy(self, ctx, enabled: bool, channel: discord.TextChannel = None):
        await self.bot.db.execute(
            "INSERT INTO guild_settings (guild_id,xp_enabled,levelup_channel_id) VALUES (?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET xp_enabled=excluded.xp_enabled,"
            "levelup_channel_id=COALESCE(excluded.levelup_channel_id,guild_settings.levelup_channel_id)",
            (ctx.guild.id, int(enabled), channel.id if channel else None)
        )
        await ctx.send(f"Leveling {'enabled' if enabled else 'disabled'}.")


async def setup(bot):
    await bot.add_cog(Levels(bot))
