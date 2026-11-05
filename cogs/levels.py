"""ONYX global leveling + Prestige system.

Global progression is keyed only by Discord user ID. Server-specific XP eligibility,
announcement preferences, ignored channels, and role rewards remain guild-scoped.
"""
import random
import time
from pathlib import Path

import discord
from discord.ext import commands

COLOR = discord.Color.from_rgb(25, 190, 190)
BASE_XP = 100
LINEAR_XP = 50
QUADRATIC_XP = 5
MAX_LEVEL = 60
MAX_PRESTIGE = 10
MAX_MASTER_LEVEL = 1000
ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "onyx_prestige"


def xp_needed(level: int) -> int:
    return max(1, int(BASE_XP + LINEAR_XP * level + QUADRATIC_XP * level * level))


def progress_bar(current: int, required: int, size: int = 14) -> str:
    ratio = min(1.0, max(0.0, current / required)) if required else 1.0
    filled = int(ratio * size)
    return "▰" * filled + "▱" * (size - filled)


def emblem_filename(prestige: int, master_level: int) -> str:
    if prestige >= MAX_PRESTIGE:
        return "prestige_master.png"
    return f"prestige_{max(1, prestige)}.png" if prestige else "prestige_1.png"


def stage_label(row) -> str:
    if row["master_mode"]:
        return f"Prestige Master • Level {row['master_level']:,}/{MAX_MASTER_LEVEL:,}"
    if row["prestige"]:
        return f"Prestige {row['prestige']} • Level {row['level']:,}/{MAX_LEVEL}"
    return f"Level {row['level']:,}/{MAX_LEVEL}"


class PrestigeChoiceView(discord.ui.View):
    def __init__(self, cog, user_id: int):
        super().__init__(timeout=90)
        self.cog = cog
        self.user_id = user_id
        self.finished = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This Prestige choice belongs to another user.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Prestige", style=discord.ButtonStyle.primary, emoji="⬆️")
    async def prestige(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.finished:
            return await interaction.response.send_message("This choice has already been handled.", ephemeral=True)
        row = await self.cog.profile(self.user_id)
        if not self.cog.eligible(row):
            self.finished = True
            return await interaction.response.edit_message(content="Your Prestige eligibility has changed. Run `,prestige` to check your status.", view=None)
        await self.cog.apply_prestige(self.user_id, row)
        self.finished = True
        for item in self.children:
            item.disabled = True
        updated = await self.cog.profile(self.user_id)
        await interaction.response.edit_message(
            content=f"🏆 **Prestige unlocked!** Your profile is now **{stage_label(updated)}**. Your lifetime XP has been preserved.",
            view=self,
        )

    @discord.ui.button(label="Stay at Level 60", style=discord.ButtonStyle.secondary, emoji="🛡️")
    async def stay(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.finished = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="You chose to keep your current rank. Your XP and Level 60 progress are safe. You can run `,prestige` again whenever you're ready.",
            view=self,
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cooldowns = {}  # global per-user cooldown, shared across every server
        self._xp_lock = __import__("asyncio").Lock()

    async def cog_load(self):
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_global_levels (
                user_id BIGINT PRIMARY KEY,
                xp BIGINT NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 0,
                prestige INTEGER NOT NULL DEFAULT 0,
                master_mode INTEGER NOT NULL DEFAULT 0,
                master_level INTEGER NOT NULL DEFAULT 0,
                lifetime_xp BIGINT NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_level_settings (
                guild_id BIGINT PRIMARY KEY,
                min_xp INTEGER NOT NULL DEFAULT 15,
                max_xp INTEGER NOT NULL DEFAULT 25,
                cooldown_seconds INTEGER NOT NULL DEFAULT 60,
                announcement_message TEXT NOT NULL DEFAULT '🎉 {mention} reached **{level}**!'
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_level_ignored_channels (
                guild_id BIGINT NOT NULL, channel_id BIGINT NOT NULL,
                PRIMARY KEY (guild_id, channel_id)
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_level_announcement_settings (
                guild_id BIGINT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS level_rewards (
                guild_id BIGINT NOT NULL, level INTEGER NOT NULL, role_id BIGINT NOT NULL,
                PRIMARY KEY (guild_id, level)
            )
        """)
        # One-time reset marker: legacy `levels` rows are deliberately left untouched as an
        # archive, but are never read by this cog. New global profiles start at zero.
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_level_migrations (
                migration_key TEXT PRIMARY KEY, completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self.bot.db.execute(
            "INSERT INTO onyx_level_migrations (migration_key) VALUES (?) ON CONFLICT(migration_key) DO NOTHING",
            ("global_levels_reset_v1",),
        )

    async def settings_for(self, guild_id):
        row = await self.bot.db.fetchone("SELECT * FROM onyx_level_settings WHERE guild_id=?", (guild_id,))
        if row is None:
            await self.bot.db.execute("INSERT INTO onyx_level_settings (guild_id) VALUES (?) ON CONFLICT(guild_id) DO NOTHING", (guild_id,))
            row = await self.bot.db.fetchone("SELECT * FROM onyx_level_settings WHERE guild_id=?", (guild_id,))
        return row

    async def profile(self, user_id: int):
        row = await self.bot.db.fetchone("SELECT * FROM onyx_global_levels WHERE user_id=?", (user_id,))
        if row is None:
            await self.bot.db.execute(
                "INSERT INTO onyx_global_levels (user_id) VALUES (?) ON CONFLICT(user_id) DO NOTHING", (user_id,)
            )
            row = await self.bot.db.fetchone("SELECT * FROM onyx_global_levels WHERE user_id=?", (user_id,))
        return row

    def eligible(self, row) -> bool:
        if row["master_mode"]:
            return row["master_level"] >= MAX_MASTER_LEVEL
        return row["level"] >= MAX_LEVEL

    async def give_rewards(self, member: discord.Member, level: int):
        rows = await self.bot.db.fetchall(
            "SELECT role_id FROM level_rewards WHERE guild_id=? AND level<=? ORDER BY level",
            (member.guild.id, level),
        )
        added = []
        me = member.guild.me
        if me is None:
            return added
        for item in rows:
            role = member.guild.get_role(item["role_id"])
            if not role or role in member.roles or role.is_default() or role.managed or role >= me.top_role:
                continue
            try:
                await member.add_roles(role, reason=f"ONYX global level reward at level {level}")
                added.append(role)
            except (discord.Forbidden, discord.HTTPException):
                pass
        return added

    async def add_xp(self, user_id: int, amount: int):
        """Apply XP to current global stage. Returns (old row, new row, levels_gained)."""
        async with self._xp_lock:
            old = await self.profile(user_id)
            xp = int(old["xp"]) + amount
            level = int(old["level"])
            master_level = int(old["master_level"])
            gained_levels = 0
            if not old["master_mode"]:
                while level < MAX_LEVEL and xp >= xp_needed(level):
                    xp -= xp_needed(level)
                    level += 1
                    gained_levels += 1
                if level >= MAX_LEVEL:
                    xp = 0
            else:
                while master_level < MAX_MASTER_LEVEL and xp >= xp_needed(master_level):
                    xp -= xp_needed(master_level)
                    master_level += 1
                    gained_levels += 1
                if master_level >= MAX_MASTER_LEVEL:
                    xp = 0
            await self.bot.db.execute(
                "UPDATE onyx_global_levels SET xp=?,level=?,master_level=?,lifetime_xp=lifetime_xp+?,updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
                (xp, level, master_level, amount, user_id),
            )
            new = await self.profile(user_id)
            return old, new, gained_levels

    async def apply_prestige(self, user_id: int, row):
        prestige = int(row["prestige"])
        if prestige < MAX_PRESTIGE:
            await self.bot.db.execute(
                "UPDATE onyx_global_levels SET prestige=prestige+1,level=0,xp=0,updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
                (user_id,),
            )
        else:
            await self.bot.db.execute(
                "UPDATE onyx_global_levels SET master_mode=1,master_level=0,level=0,xp=0,updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
                (user_id,),
            )

    async def announce_level_up(self, message, settings, new_row, rewards):
        gid = message.guild.id
        pref = await self.bot.db.fetchone("SELECT enabled FROM onyx_level_announcement_settings WHERE guild_id=?", (gid,))
        if pref and not pref["enabled"]:
            return
        cfg = await self.bot.db.fetchone("SELECT levelup_channel_id FROM guild_settings WHERE guild_id=?", (gid,))
        channel_id = cfg["levelup_channel_id"] if cfg else None
        channel = message.guild.get_channel(channel_id) if channel_id else message.channel
        if not channel:
            return
        level_text = stage_label(new_row)
        announcement = settings["announcement_message"]
        replacements = {
            "{mention}": message.author.mention,
            "{user}": discord.utils.escape_markdown(message.author.display_name),
            "{level}": level_text,
            "{server}": discord.utils.escape_markdown(message.guild.name),
        }
        for token, value in replacements.items():
            announcement = announcement.replace(token, value)
        if rewards:
            announcement += "\n🎁 Reward unlocked: " + ", ".join(role.mention for role in rewards)
        if self.eligible(new_row) and not new_row["master_mode"]:
            announcement += f"\n🏆 You've reached Level {MAX_LEVEL}! Use `,prestige` when you're ready to choose your next step."
        try:
            await channel.send(announcement, allowed_mentions=discord.AllowedMentions(users=True, roles=True))
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot or message.webhook_id or len(message.content.strip()) < 3:
            return
        try:
            if (await self.bot.get_context(message)).valid:
                return
        except Exception:
            pass
        gid = message.guild.id
        settings = await self.settings_for(gid)
        enabled = await self.bot.db.fetchone("SELECT xp_enabled FROM guild_settings WHERE guild_id=?", (gid,))
        if enabled and not enabled["xp_enabled"]:
            return
        ignored = await self.bot.db.fetchone(
            "SELECT 1 FROM onyx_level_ignored_channels WHERE guild_id=? AND channel_id=?", (gid, message.channel.id)
        )
        if ignored:
            return
        now = time.monotonic()
        user_id = message.author.id
        if now - self.cooldowns.get(user_id, 0) < settings["cooldown_seconds"]:
            return
        self.cooldowns[user_id] = now
        gained = random.randint(settings["min_xp"], settings["max_xp"])
        old, new, gained_levels = await self.add_xp(user_id, gained)
        if gained_levels:
            rewards = []
            # Guild roles remain server-specific; use the new global level threshold.
            reward_level = new["master_level"] if new["master_mode"] else new["level"]
            rewards = await self.give_rewards(message.author, reward_level)
            await self.announce_level_up(message, settings, new, rewards)

    @commands.command(name="rank", aliases=["level"], help="View your global ONYX rank.")
    @commands.guild_only()
    async def rank(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        row = await self.profile(member.id)
        current_level = row["master_level"] if row["master_mode"] else row["level"]
        needed = xp_needed(current_level)
        rank_count = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM onyx_global_levels WHERE prestige>? OR (prestige=? AND master_level>?) OR (prestige=? AND master_level=? AND level>?) OR (prestige=? AND master_level=? AND level=? AND xp>?)",
            (row["prestige"], row["prestige"], row["master_level"], row["prestige"], row["master_level"], row["level"], row["prestige"], row["master_level"], row["level"], row["xp"]),
        )
        filename = "prestige_master.png" if row["master_mode"] else (f"prestige_{max(1, row['prestige'])}.png")
        path = ASSET_DIR / filename
        embed = discord.Embed(title=f"{member.display_name} • ONYX Global Rank", color=COLOR)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Rank", value=f"**{stage_label(row)}**", inline=False)
        embed.add_field(name="Prestige", value="**Prestige Master**" if row["master_mode"] else f"**{row['prestige']}/{MAX_PRESTIGE}**")
        embed.add_field(name="Lifetime XP", value=f"**{row['lifetime_xp']:,}**")
        embed.add_field(name="Global position", value=f"**#{(rank_count['n'] if rank_count else 0) + 1:,}**")
        if not self.eligible(row):
            embed.add_field(name=f"Progress • {row['xp']:,}/{needed:,} XP", value=f"`{progress_bar(row['xp'], needed)}` **{row['xp'] / needed * 100:.1f}%**", inline=False)
        else:
            embed.add_field(name="Next step", value="Run `,prestige` to choose whether to Prestige or keep your rank.", inline=False)
        embed.set_footer(text="ONYX • One global profile across every server")
        if path.exists():
            file = discord.File(path, filename=filename)
            embed.set_image(url=f"attachment://{filename}")
            await ctx.send(embed=embed, file=file)
        else:
            await ctx.send(embed=embed)

    @commands.command(name="leaderboard", aliases=["levels_top"], help="Show the global ONYX leaderboard.")
    @commands.guild_only()
    async def leaderboard(self, ctx):
        rows = await self.bot.db.fetchall(
            "SELECT user_id,prestige,level,master_level,xp,lifetime_xp FROM onyx_global_levels ORDER BY prestige DESC,master_level DESC,level DESC,xp DESC LIMIT 10"
        )
        if not rows:
            return await ctx.send("No global level data yet. Start chatting to earn XP!")
        lines = []
        for i, row in enumerate(rows, 1):
            user = self.bot.get_user(row["user_id"])
            name = discord.utils.escape_markdown(user.display_name) if user else f"User {row['user_id']}"
            lines.append(f"**{i}.** {name} — {stage_label(row)} • {row['lifetime_xp']:,} lifetime XP")
        embed = discord.Embed(title="🏆 ONYX • Global Leaderboard", description="\n".join(lines), color=COLOR)
        embed.set_footer(text="Rankings are shared across all ONYX servers")
        await ctx.send(embed=embed)

    @commands.group(name="prestige", invoke_without_command=True, help="View your Prestige status or choose to Prestige at Level 60.")
    @commands.guild_only()
    async def prestige(self, ctx):
        row = await self.profile(ctx.author.id)
        if row["master_mode"] and row["master_level"] >= MAX_MASTER_LEVEL:
            return await ctx.send(f"🏆 You have completed the ONYX Prestige track at **Prestige Master Level {MAX_MASTER_LEVEL:,}**!")
        if not self.eligible(row):
            return await ctx.send(f"You are **{stage_label(row)}**. Reach Level 60 to unlock your next Prestige choice.")
        if not row["master_mode"] and row["prestige"] < MAX_PRESTIGE:
            description = f"You've reached **Level {MAX_LEVEL}**. Choose whether to reset to Level 0 and unlock Prestige **{row['prestige'] + 1}**, or keep your current rank. Your lifetime XP and previously earned server roles stay intact."
        elif not row["master_mode"]:
            description = f"You've completed **Prestige {MAX_PRESTIGE} Level {MAX_LEVEL}**. Confirm to enter the **Prestige Master** track (1,000 levels)."
        else:
            description = f"You've completed Prestige Master Level {MAX_MASTER_LEVEL:,}. The Prestige track is complete!"
        embed = discord.Embed(title="🏆 ONYX • Prestige Available", description=description, color=COLOR)
        await ctx.send(embed=embed, view=PrestigeChoiceView(self, ctx.author.id))

    @prestige.command(name="leaderboard")
    async def prestige_leaderboard(self, ctx):
        rows = await self.bot.db.fetchall(
            "SELECT user_id,prestige,level,master_level,lifetime_xp FROM onyx_global_levels WHERE prestige>0 ORDER BY master_mode DESC,prestige DESC,master_level DESC,level DESC,lifetime_xp DESC LIMIT 10"
        )
        if not rows:
            return await ctx.send("No one has earned Prestige yet.")
        lines = []
        for i, row in enumerate(rows, 1):
            user = self.bot.get_user(row["user_id"])
            name = discord.utils.escape_markdown(user.display_name) if user else f"User {row['user_id']}"
            lines.append(f"**{i}.** {name} — {stage_label(row)}")
        await ctx.send(embed=discord.Embed(title="🏅 ONYX • Prestige Leaderboard", description="\n".join(lines), color=COLOR))

    @commands.group(name="levels", invoke_without_command=True, help="View global leveling and manage this server's XP settings.")
    @commands.guild_only()
    async def levels(self, ctx):
        s = await self.settings_for(ctx.guild.id)
        enabled = await self.bot.db.fetchone("SELECT xp_enabled FROM guild_settings WHERE guild_id=?", (ctx.guild.id,))
        active = enabled["xp_enabled"] if enabled else 1
        embed = discord.Embed(title="ONYX • Global Leveling Settings", color=COLOR)
        embed.add_field(name="Server XP status", value="Enabled" if active else "Disabled")
        embed.add_field(name="XP per message", value=f"{s['min_xp']}–{s['max_xp']}")
        embed.add_field(name="Global cooldown", value=f"{s['cooldown_seconds']} seconds")
        embed.add_field(name="Progression", value="10 Prestiges • Level 1–60 each • Prestige Master 1–1,000", inline=False)
        embed.add_field(name="Commands", value=(
            "`,rank [member]` • `,leaderboard` • `,prestige`\n"
            "`,levels enable/disable` • `,levels rate <min> <max>`\n"
            "`,levels cooldown <seconds>` • `,levels channel #channel`\n"
            "`,levels announcements on/off` • `,levels message <text>`\n"
            "`,levels ignore add/remove/list #channel`\n"
            "`,levels reward add/remove/list ...`\n"
            "Owner: `,levels xp add/set/remove @member <amount>` and `,levels reset @member/all`"
        ), inline=False)
        await ctx.send(embed=embed)

    @levels.command(name="announcements")
    @commands.has_guild_permissions(manage_guild=True)
    async def announcements(self, ctx, setting: str):
        setting = setting.casefold()
        if setting not in ("on", "off", "enable", "disable"):
            return await ctx.send(f"Use `{ctx.prefix}levels announcements on` or `,levels announcements off`.")
        enabled = setting in ("on", "enable")
        await self.bot.db.execute(
            "INSERT INTO onyx_level_announcement_settings (guild_id,enabled) VALUES (?,?) ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled",
            (ctx.guild.id, int(enabled)),
        )
        await ctx.send("✅ Level-up announcements enabled." if enabled else "🔕 Level-up announcements disabled. XP still accumulates globally.")

    @commands.command(name="levelmessages", help="Enable or disable level-up announcements in this server.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def levelmessages(self, ctx, setting: str):
        setting = setting.casefold()
        if setting not in ("on", "off"):
            return await ctx.send(f"Use `{ctx.prefix}levelmessages on` or `{ctx.prefix}levelmessages off`.")
        enabled = int(setting == "on")
        await self.bot.db.execute(
            "INSERT INTO onyx_level_announcement_settings (guild_id,enabled) VALUES (?,?) ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled",
            (ctx.guild.id, enabled),
        )
        await ctx.send("✅ Level-up messages enabled in this server." if enabled else "🔕 Level-up messages disabled in this server. Global XP will continue.")

    @levels.command(name="enable")
    @commands.has_guild_permissions(manage_guild=True)
    async def enable(self, ctx):
        await self.bot.db.execute("INSERT INTO guild_settings (guild_id,xp_enabled) VALUES (?,1) ON CONFLICT(guild_id) DO UPDATE SET xp_enabled=1", (ctx.guild.id,))
        await ctx.send("✅ XP earning enabled in this server.")

    @levels.command(name="disable")
    @commands.has_guild_permissions(manage_guild=True)
    async def disable(self, ctx):
        await self.bot.db.execute("INSERT INTO guild_settings (guild_id,xp_enabled) VALUES (?,0) ON CONFLICT(guild_id) DO UPDATE SET xp_enabled=0", (ctx.guild.id,))
        await ctx.send("⏸️ XP earning disabled in this server. Global profiles remain intact.")

    @levels.command(name="rate")
    @commands.has_guild_permissions(manage_guild=True)
    async def rate(self, ctx, minimum: int, maximum: int):
        if not 1 <= minimum <= maximum <= 1000:
            return await ctx.send("Use values from 1–1,000, with minimum no higher than maximum.")
        await self.bot.db.execute("INSERT INTO onyx_level_settings (guild_id,min_xp,max_xp) VALUES (?,?,?) ON CONFLICT(guild_id) DO UPDATE SET min_xp=excluded.min_xp,max_xp=excluded.max_xp", (ctx.guild.id, minimum, maximum))
        await ctx.send(f"✅ This server now awards **{minimum}–{maximum} XP** per eligible message.")

    @levels.command(name="cooldown")
    @commands.has_guild_permissions(manage_guild=True)
    async def cooldown(self, ctx, seconds: int):
        if not 5 <= seconds <= 3600:
            return await ctx.send("Cooldown must be between 5 and 3,600 seconds.")
        await self.bot.db.execute("INSERT INTO onyx_level_settings (guild_id,cooldown_seconds) VALUES (?,?) ON CONFLICT(guild_id) DO UPDATE SET cooldown_seconds=excluded.cooldown_seconds", (ctx.guild.id, seconds))
        await ctx.send(f"✅ Global user cooldown set to **{seconds} seconds** when earning XP in this server.")

    @levels.command(name="channel")
    @commands.has_guild_permissions(manage_guild=True)
    async def channel(self, ctx, channel: discord.TextChannel = None):
        await self.bot.db.execute("INSERT INTO guild_settings (guild_id,levelup_channel_id) VALUES (?,?) ON CONFLICT(guild_id) DO UPDATE SET levelup_channel_id=excluded.levelup_channel_id", (ctx.guild.id, channel.id if channel else None))
        await ctx.send(f"✅ Level-up announcements set to {channel.mention}." if channel else "✅ Announcements will appear in the channel where XP was earned.")

    @levels.command(name="message")
    @commands.has_guild_permissions(manage_guild=True)
    async def message(self, ctx, *, text: str):
        import re
        allowed = {"{mention}", "{user}", "{level}", "{server}"}
        tokens = set(re.findall(r"\{[^{}]+\}", text))
        if len(text) > 1000 or tokens - allowed:
            return await ctx.send("Message must be 1,000 characters or fewer. Placeholders: `{mention}`, `{user}`, `{level}`, `{server}`.")
        await self.bot.db.execute("INSERT INTO onyx_level_settings (guild_id,announcement_message) VALUES (?,?) ON CONFLICT(guild_id) DO UPDATE SET announcement_message=excluded.announcement_message", (ctx.guild.id, text))
        await ctx.send("✅ Level-up announcement updated.")

    @levels.group(name="ignore", invoke_without_command=True)
    @commands.has_guild_permissions(manage_guild=True)
    async def ignore(self, ctx):
        await ctx.send(f"Use `{ctx.prefix}levels ignore add/remove/list #channel`.")

    @ignore.command(name="add")
    @commands.has_guild_permissions(manage_guild=True)
    async def ignore_add(self, ctx, channel: discord.TextChannel):
        await self.bot.db.execute("INSERT INTO onyx_level_ignored_channels (guild_id,channel_id) VALUES (?,?) ON CONFLICT DO NOTHING", (ctx.guild.id, channel.id))
        await ctx.send(f"🚫 {channel.mention} will not award XP.")

    @ignore.command(name="remove")
    @commands.has_guild_permissions(manage_guild=True)
    async def ignore_remove(self, ctx, channel: discord.TextChannel):
        await self.bot.db.execute("DELETE FROM onyx_level_ignored_channels WHERE guild_id=? AND channel_id=?", (ctx.guild.id, channel.id))
        await ctx.send(f"✅ XP earning restored in {channel.mention}.")

    @ignore.command(name="list")
    @commands.has_guild_permissions(manage_guild=True)
    async def ignore_list(self, ctx):
        rows = await self.bot.db.fetchall("SELECT channel_id FROM onyx_level_ignored_channels WHERE guild_id=?", (ctx.guild.id,))
        await ctx.send(embed=discord.Embed(title="ONYX • Ignored XP Channels", description="\n".join(f"• <#{r['channel_id']}>" for r in rows) or "No ignored channels.", color=COLOR))

    @levels.group(name="reward", invoke_without_command=True)
    @commands.has_guild_permissions(manage_guild=True)
    async def reward(self, ctx):
        await ctx.send(f"Use `{ctx.prefix}levels reward add <level> @role`, `remove <level>`, or `list`.")

    @reward.command(name="add")
    @commands.has_guild_permissions(manage_guild=True)
    async def reward_add(self, ctx, level: int, role: discord.Role):
        me = ctx.guild.me
        if not 1 <= level <= 1000 or role.is_default() or role.managed or not me or role >= me.top_role:
            return await ctx.send("Choose a level from 1–1,000 and a role ONYX can assign (check role hierarchy).")
        await self.bot.db.execute("INSERT INTO level_rewards (guild_id,level,role_id) VALUES (?,?,?) ON CONFLICT(guild_id,level) DO UPDATE SET role_id=excluded.role_id", (ctx.guild.id, level, role.id))
        await ctx.send(f"🎁 {role.mention} will be awarded at global level **{level}** in this server.")

    @reward.command(name="remove")
    @commands.has_guild_permissions(manage_guild=True)
    async def reward_remove(self, ctx, level: int):
        await self.bot.db.execute("DELETE FROM level_rewards WHERE guild_id=? AND level=?", (ctx.guild.id, level))
        await ctx.send(f"Removed the level **{level}** reward, if one existed.")

    @reward.command(name="list")
    @commands.has_guild_permissions(manage_guild=True)
    async def reward_list(self, ctx):
        rows = await self.bot.db.fetchall("SELECT level,role_id FROM level_rewards WHERE guild_id=? ORDER BY level", (ctx.guild.id,))
        await ctx.send(embed=discord.Embed(title="ONYX • Server Role Rewards", description="\n".join(f"Level **{r['level']}** → <@&{r['role_id']}>" for r in rows) or "No rewards configured.", color=COLOR))

    @levels.group(name="xp", invoke_without_command=True)
    @commands.is_owner()
    async def xp(self, ctx):
        await ctx.send(f"Owner-only global XP tools: `{ctx.prefix}levels xp add/set/remove @member <amount>`.")

    async def change_xp(self, ctx, member, amount, mode):
        if not 1 <= amount <= 10_000_000:
            return await ctx.send("Amount must be between 1 and 10,000,000 XP.")
        row = await self.profile(member.id)
        if mode == "add":
            old, new, _ = await self.add_xp(member.id, amount)
        else:
            current = int(row["xp"])
            value = amount if mode == "set" else max(0, current - amount)
            await self.bot.db.execute("UPDATE onyx_global_levels SET xp=?,updated_at=CURRENT_TIMESTAMP WHERE user_id=?", (value, member.id))
            new = await self.profile(member.id)
        verb = {"add": "Added", "set": "Set current-level XP for", "remove": "Removed current-level XP from"}[mode]
        await ctx.send(f"✅ {verb} {member.mention}. Current rank: **{stage_label(new)}** • XP: **{new['xp']:,}** • Lifetime XP: **{new['lifetime_xp']:,}**.")

    @xp.command(name="add")
    @commands.is_owner()
    async def xp_add(self, ctx, member: discord.User, amount: int):
        await self.change_xp(ctx, member, amount, "add")

    @xp.command(name="set")
    @commands.is_owner()
    async def xp_set(self, ctx, member: discord.User, amount: int):
        await self.change_xp(ctx, member, amount, "set")

    @xp.command(name="remove")
    @commands.is_owner()
    async def xp_remove(self, ctx, member: discord.User, amount: int):
        await self.change_xp(ctx, member, amount, "remove")

    @levels.command(name="reset")
    @commands.is_owner()
    async def reset(self, ctx, target: str = None):
        if not target:
            return await ctx.send(f"Use `{ctx.prefix}levels reset @user` or `{ctx.prefix}levels reset all`. This affects global profiles.")
        if target.casefold() == "all":
            await self.bot.db.execute("DELETE FROM onyx_global_levels")
            await ctx.send("✅ All ONYX global leveling profiles have been reset to Level 0. Server settings and rewards were preserved.")
            return
        try:
            user = await commands.UserConverter().convert(ctx, target)
        except commands.BadArgument:
            return await ctx.send("Mention a Discord user or use `all`.")
        await self.bot.db.execute("DELETE FROM onyx_global_levels WHERE user_id=?", (user.id,))
        await ctx.send(f"✅ Global leveling profile for {user.mention} has been reset.")


async def setup(bot):
    await bot.add_cog(Levels(bot))
