import platform
from datetime import timedelta

import discord
from discord.ext import commands
from discord import __version__ as discord_py_version


SUPPORT_SERVER = "https://discord.gg/p6FSRWcnP9"
BOT_COLOR = discord.Color.from_rgb(44, 38, 67)


def format_dt(value, style="F"):
    if value is None:
        return "Unknown"
    return discord.utils.format_dt(value, style)


def human_duration(delta):
    seconds = max(0, int(delta.total_seconds()))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def safe_text(value, fallback="None"):
    if value is None or str(value).strip() == "":
        return fallback
    return str(value)


def add_field(embed, name, value, inline=False):
    value = str(value)
    if len(value) > 1024:
        value = value[:1018] + " [...]"
    embed.add_field(name=name[:256], value=value or "None", inline=inline)


def public_badges(user):
    flags = getattr(user, "public_flags", None)
    if flags is None:
        return "Unavailable"
    labels = []
    try:
        for name, enabled in flags:
            if enabled:
                labels.append(name.replace("_", " ").title())
    except (TypeError, AttributeError):
        # Fallback for discord.py versions exposing flag names differently.
        for name in dir(flags):
            if name.startswith("_"):
                continue
            try:
                value = getattr(flags, name)
            except Exception:
                continue
            if isinstance(value, bool) and value:
                labels.append(name.replace("_", " ").title())
    return ", ".join(sorted(set(labels))) if labels else "No public badges"


def channel_counts(guild):
    channels = list(guild.channels)
    types = {
        "Text": sum(isinstance(c, discord.TextChannel) for c in channels),
        "Voice": sum(isinstance(c, discord.VoiceChannel) for c in channels),
        "Categories": sum(isinstance(c, discord.CategoryChannel) for c in channels),
        "Forums": sum(isinstance(c, discord.ForumChannel) for c in channels),
        "Stages": sum(isinstance(c, discord.StageChannel) for c in channels),
    }
    if hasattr(discord, "MediaChannel"):
        types["Media"] = sum(isinstance(c, discord.MediaChannel) for c in channels)
    return types


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="ping", help="Check the bot's latency.")
    async def ping(self, ctx: commands.Context):
        await ctx.send(f"🏓 Pong! `{round(self.bot.latency * 1000)} ms`")

    @commands.command(name="userinfo", help="Show detailed information about a member.")
    async def userinfo(self, ctx: commands.Context, *, member: discord.Member = None):
        member = member or ctx.author
        user = member
        try:
            # Fetching the User object can expose profile banner/accent details
            # that may not be present on the cached guild Member.
            user = await self.bot.fetch_user(member.id)
        except (discord.HTTPException, discord.Forbidden):
            pass

        now = discord.utils.utcnow()
        roles = [role.mention for role in reversed(member.roles) if role != member.guild.default_role]
        roles_text = ", ".join(roles) if roles else "No roles"
        if len(roles_text) > 1000:
            roles_text = roles_text[:990] + " [...]"

        embed = discord.Embed(
            title=f"User Information • {member}",
            description=f"{member.mention}\n{'🤖 Bot account' if member.bot else '👤 User account'}",
            color=member.color if member.color.value else BOT_COLOR,
            timestamp=now
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        add_field(embed, "Display name", member.display_name, True)
        add_field(embed, "Username", f"`{member.name}`", True)
        add_field(embed, "User ID", f"`{member.id}`", True)
        add_field(embed, "Account created", f"{format_dt(member.created_at, 'F')}\n{format_dt(member.created_at, 'R')}", False)
        add_field(embed, "Joined this server", f"{format_dt(member.joined_at, 'F')}\n{format_dt(member.joined_at, 'R')}", False)
        add_field(embed, "Public badges", public_badges(user), False)
        add_field(embed, "Nickname", safe_text(member.nick), True)
        add_field(embed, "Top role", member.top_role.mention, True)
        add_field(embed, "Role count", len(member.roles) - 1, True)
        add_field(embed, "Roles", roles_text, False)
        add_field(embed, "Status", str(member.status).title(), True)
        add_field(embed, "Platform status", f"Desktop: {member.desktop_status}\nMobile: {member.mobile_status}\nWeb: {member.web_status}", True)
        add_field(embed, "Boosting since", format_dt(member.premium_since, "F") if member.premium_since else "Not boosting", True)
        add_field(embed, "Timed out until", format_dt(member.timed_out_until, "F") if member.timed_out_until else "Not timed out", True)
        add_field(embed, "Pending verification", "Yes" if member.pending else "No", True)
        add_field(embed, "Guild permissions", ", ".join(
            name.replace("_", " ").title()
            for name, enabled in member.guild_permissions
            if enabled and name in {
                "administrator", "manage_guild", "manage_roles", "manage_channels",
                "manage_messages", "moderate_members", "kick_members", "ban_members",
                "view_audit_log", "manage_webhooks", "mention_everyone"
            }
        ) or "No elevated permissions", False)

        activities = []
        for activity in member.activities:
            label = getattr(activity, "name", None) or getattr(activity, "details", None) or str(activity.type)
            activities.append(str(label))
        add_field(embed, "Activities", ", ".join(activities) if activities else "No visible activity", False)

        if getattr(user, "banner", None):
            embed.set_image(url=user.banner.url)
        footer = f"Account age: {human_duration(now - member.created_at)}"
        embed.set_footer(text=footer)
        await ctx.send(embed=embed)

    @commands.command(name="serverinfo", help="Show detailed information about this server.")
    @commands.guild_only()
    async def serverinfo(self, ctx: commands.Context):
        guild = ctx.guild
        counts = channel_counts(guild)
        channels_summary = "\n".join(f"**{name}:** {count}" for name, count in counts.items())
        text_channels = [c.mention for c in guild.text_channels]
        voice_channels = [c.mention for c in guild.voice_channels]
        categories = [c.name for c in guild.categories]

        def clipped_list(items, empty="None"):
            if not items:
                return empty
            result = ", ".join(items)
            return result if len(result) <= 1000 else result[:990] + " [...]"

        embed = discord.Embed(
            title=f"Server Information • {guild.name}",
            description=safe_text(guild.description, "No server description set."),
            color=BOT_COLOR,
            timestamp=discord.utils.utcnow()
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        if guild.banner:
            embed.set_image(url=guild.banner.url)

        add_field(embed, "Server ID", f"`{guild.id}`", True)
        add_field(embed, "Owner", f"<@{guild.owner_id}>", True)
        add_field(embed, "Created", f"{format_dt(guild.created_at, 'F')}\n{format_dt(guild.created_at, 'R')}", False)
        add_field(embed, "Members", f"Total: **{guild.member_count or 0}**\nHumans: **{sum(not m.bot for m in guild.members)}**\nBots: **{sum(m.bot for m in guild.members)}**", True)
        add_field(embed, "Channels", f"Total: **{len(guild.channels)}**\n{channels_summary}", True)
        add_field(embed, "Roles", f"{len(guild.roles)} total", True)
        add_field(embed, "Custom emojis", f"{len(guild.emojis)} total\nAnimated: {sum(e.animated for e in guild.emojis)}\nStatic: {sum(not e.animated for e in guild.emojis)}", True)
        add_field(embed, "Stickers", f"{len(guild.stickers)} total", True)
        add_field(embed, "Boosts", f"Level: **{guild.premium_tier}**\nBoost count: **{guild.premium_subscription_count or 0}**", True)
        add_field(embed, "Verification level", str(guild.verification_level).replace("_", " ").title(), True)
        add_field(embed, "Content filter", str(guild.explicit_content_filter).replace("_", " ").title(), True)
        add_field(embed, "Default notifications", str(guild.default_notifications).replace("_", " ").title(), True)
        add_field(embed, "AFK channel", guild.afk_channel.mention if guild.afk_channel else "Not set", True)
        add_field(embed, "AFK timeout", f"{guild.afk_timeout} seconds", True)
        add_field(embed, "System channel", guild.system_channel.mention if guild.system_channel else "Not set", True)
        add_field(embed, "Rules channel", guild.rules_channel.mention if guild.rules_channel else "Not set", True)
        add_field(embed, "Public updates channel", guild.public_updates_channel.mention if guild.public_updates_channel else "Not set", True)
        add_field(embed, "Server features", ", ".join(f.replace("_", " ").title() for f in guild.features) or "No special features", False)
        add_field(embed, "Categories", clipped_list(categories), False)
        add_field(embed, "Text channels", clipped_list(text_channels), False)
        add_field(embed, "Voice channels", clipped_list(voice_channels), False)
        if guild.vanity_url_code:
            add_field(embed, "Vanity invite", f"https://discord.gg/{guild.vanity_url_code}", True)
        embed.set_footer(text=f"Requested by {ctx.author} • Server ID: {guild.id}")
        await ctx.send(embed=embed)

        # Send custom asset names separately so large servers do not overflow
        # a single embed field.
        if guild.emojis or guild.stickers:
            assets = discord.Embed(title=f"{guild.name} • Custom Assets", color=BOT_COLOR)
            emoji_lines = [f"{str(e)} `:{e.name}:`" for e in guild.emojis[:40]]
            sticker_lines = [f"• {s.name}" for s in guild.stickers[:40]]
            add_field(assets, f"Emojis ({len(guild.emojis)})", "\n".join(emoji_lines) or "None", False)
            add_field(assets, f"Stickers ({len(guild.stickers)})", "\n".join(sticker_lines) or "None", False)
            await ctx.send(embed=assets)

    @commands.command(name="avatar", help="Display a member's avatar.")
    async def avatar(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        embed = discord.Embed(title=f"{member}'s avatar", color=BOT_COLOR)
        embed.set_image(url=member.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name="botinfo", help="Show detailed information about ONYX.")
    async def botinfo(self, ctx: commands.Context):
        now = discord.utils.utcnow()
        started_at = getattr(self.bot, "started_at", now)
        uptime = now - started_at
        app_info = None
        try:
            app_info = await self.bot.application_info()
        except (discord.HTTPException, discord.Forbidden):
            pass

        bot_user = self.bot.user
        owner = "Unavailable"
        if app_info:
            if getattr(app_info, "team", None):
                owner = f"{app_info.team.name} (Development Team)"
            elif getattr(app_info, "owner", None):
                owner = str(app_info.owner)

        invite_url = (
            f"https://discord.com/oauth2/authorize?client_id={self.bot.application_id}&scope=bot"
            if self.bot.application_id else "Unavailable"
        )
        command_count = sum(1 for command in self.bot.walk_commands() if not command.hidden)
        embed = discord.Embed(
            title="ONYX • Bot Information",
            description="A feature-rich Discord community bot.",
            color=BOT_COLOR,
            timestamp=now
        )
        if bot_user:
            embed.set_thumbnail(url=bot_user.display_avatar.url)
        if app_info and getattr(app_info, "description", None):
            embed.description = app_info.description[:4000]

        add_field(embed, "Bot username", str(bot_user), True)
        add_field(embed, "Bot ID", f"`{bot_user.id}`" if bot_user else "Unavailable", True)
        add_field(embed, "Application owner", owner, True)
        add_field(embed, "Created", format_dt(bot_user.created_at, "F") if bot_user else "Unavailable", False)
        add_field(embed, "Uptime", human_duration(uptime), True)
        add_field(embed, "Latency", f"{self.bot.latency * 1000:.0f} ms", True)
        add_field(embed, "Servers", len(self.bot.guilds), True)
        add_field(embed, "Cached users", len(self.bot.users), True)
        add_field(embed, "Commands", command_count, True)
        add_field(embed, "Loaded cogs", len(self.bot.cogs), True)
        add_field(embed, "Python", platform.python_version(), True)
        add_field(embed, "discord.py", discord_py_version, True)
        add_field(embed, "Shard count", self.bot.shard_count or 1, True)
        add_field(embed, "Default prefix", "`,` (server-specific prefixes may be configured)", False)
        add_field(embed, "Support server", f"[Join the ONYX Support Server]({SUPPORT_SERVER})", False)
        add_field(embed, "Invite ONYX", f"[Add ONYX to your server]({invite_url})" if invite_url != "Unavailable" else invite_url, False)
        if app_info:
            add_field(embed, "Public bot", "Yes" if app_info.bot_public else "No", True)
            add_field(embed, "Requires code grant", "Yes" if app_info.bot_require_code_grant else "No", True)
            add_field(embed, "Application tags", ", ".join(app_info.tags) if app_info.tags else "None", False)
            add_field(embed, "Privacy policy", app_info.privacy_policy_url or "Not provided", False)
            add_field(embed, "Terms of service", app_info.terms_of_service_url or "Not provided", False)
        embed.set_footer(text="ONYX • Prefix Commands Only")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Utility(bot))
