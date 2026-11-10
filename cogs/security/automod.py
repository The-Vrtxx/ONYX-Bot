import re
from collections import defaultdict, deque
from time import monotonic
from datetime import timedelta

import discord
from discord.ext import commands

INVITE_RE = re.compile(r"(?:https?://)?(?:www\.)?(?:discord\.gg/|discord(?:app)?\.com/invite/)[A-Za-z0-9-]+", re.I)
URL_RE = re.compile(r"https?://\S+", re.I)

FILTERS = {
    "invites": ("Discord invites", 1, 60),
    "links": ("Links", 1, 60),
    "spam": ("Message spam", 5, 7),
    "repeats": ("Repeated messages", 3, 30),
}
PUNISHMENTS = {"delete", "warn", "timeout", "jail"}


class FilterSystem(commands.Cog):
    """Per-server message filters with independent thresholds and punishments."""

    def __init__(self, bot):
        self.bot = bot
        self.activity = defaultdict(deque)
        self.last_message = {}

    async def cog_load(self):
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_filter_settings (
                guild_id BIGINT NOT NULL,
                filter_name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                threshold INTEGER NOT NULL,
                window_seconds INTEGER NOT NULL,
                punishment TEXT NOT NULL DEFAULT 'delete',
                timeout_seconds INTEGER NOT NULL DEFAULT 600,
                PRIMARY KEY (guild_id, filter_name)
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_automod_events (
                guild_id BIGINT NOT NULL, filter_name TEXT NOT NULL,
                user_id BIGINT, channel_id BIGINT, punishment TEXT NOT NULL,
                success INTEGER NOT NULL DEFAULT 0, result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    async def setting(self, guild_id, name):
        row = await self.bot.db.fetchone(
            "SELECT * FROM onyx_filter_settings WHERE guild_id=? AND filter_name=?",
            (guild_id, name),
        )
        if row:
            return row
        _, threshold, window = FILTERS[name]
        await self.bot.db.execute("""
            INSERT INTO onyx_filter_settings
                (guild_id,filter_name,enabled,threshold,window_seconds,punishment,timeout_seconds)
            VALUES (?,?,0,?,?,'delete',600)
            ON CONFLICT(guild_id,filter_name) DO NOTHING
        """, (guild_id, name, threshold, window))
        return await self.bot.db.fetchone(
            "SELECT * FROM onyx_filter_settings WHERE guild_id=? AND filter_name=?",
            (guild_id, name),
        )

    async def save_setting(self, guild_id, name, enabled, threshold, window, punishment, duration):
        current = await self.setting(guild_id, name)
        await self.bot.db.execute("""
            INSERT INTO onyx_filter_settings
                (guild_id,filter_name,enabled,threshold,window_seconds,punishment,timeout_seconds)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(guild_id,filter_name) DO UPDATE SET
                enabled=excluded.enabled, threshold=excluded.threshold,
                window_seconds=excluded.window_seconds, punishment=excluded.punishment,
                timeout_seconds=excluded.timeout_seconds
        """, (
            guild_id, name, int(enabled),
            threshold if threshold is not None else int(current["threshold"]),
            window if window is not None else int(current["window_seconds"]),
            punishment if punishment is not None else current["punishment"],
            duration if duration is not None else int(current["timeout_seconds"]),
        ))

    @staticmethod
    def parse_options(raw):
        tokens = raw.split()
        result = {}
        i = 0
        while i < len(tokens):
            if not tokens[i].startswith("--") or i + 1 >= len(tokens):
                return None
            key, value = tokens[i][2:].lower(), tokens[i + 1].lower()
            if key not in {"do", "threshold", "window", "duration"} or key in result:
                return None
            if key == "do":
                result[key] = value
            else:
                try:
                    result[key] = int(value)
                except ValueError:
                    return None
            i += 2
        return result

    @commands.command(name="filter", help="Configure ONYX message filters and punishments.")
    @commands.has_guild_permissions(manage_guild=True)
    async def filter_command(self, ctx, filter_name: str = None, state: str = None, *, options: str = ""):
        p = ctx.prefix
        if not filter_name or filter_name.lower() in {"help", "list"}:
            return await self.send_help(ctx)
        filter_name = filter_name.lower()
        if filter_name == "status":
            return await self.send_status(ctx)
        if filter_name not in FILTERS:
            return await ctx.send("Available filters: `invites`, `links`, `spam`, `repeats`. Use `,filter help`.")
        state = (state or "").lower()
        if state not in {"on", "off"}:
            return await ctx.send(f"Use `{p}filter {filter_name} on` or `{p}filter {filter_name} off`.")

        opts = self.parse_options(options)
        if opts is None:
            return await ctx.send("Options: `--do delete|warn|timeout|jail`, `--threshold N`, `--window SECONDS`, `--duration SECONDS`.")
        punishment = opts.get("do")
        threshold, window, duration = opts.get("threshold"), opts.get("window"), opts.get("duration")
        if punishment is not None and punishment not in PUNISHMENTS:
            return await ctx.send("Punishment must be `delete`, `warn`, `timeout`, or `jail`.")
        if threshold is not None and not 1 <= threshold <= 50:
            return await ctx.send("Threshold must be between 1 and 50.")
        if window is not None and not 1 <= window <= 300:
            return await ctx.send("Window must be between 1 and 300 seconds.")
        if duration is not None and not 1 <= duration <= 40320:
            return await ctx.send("Timeout duration must be 1–40,320 seconds (28 days).")

        await self.save_setting(ctx.guild.id, filter_name, state == "on", threshold, window, punishment, duration)
        cfg = await self.setting(ctx.guild.id, filter_name)
        text = (
            f"**{FILTERS[filter_name][0]} filter {'enabled' if state == 'on' else 'disabled'}.**\n"
            f"Punishment: `{cfg['punishment']}` • Threshold: `{cfg['threshold']}` "
            f"• Window: `{cfg['window_seconds']}s`"
        )
        if cfg["punishment"] == "timeout":
            text += f" • Timeout: `{cfg['timeout_seconds']}s`"
        if cfg["punishment"] == "jail":
            text += "\nRequires `,setup jail` and ONYX's highest role above the Jailed role."
        await ctx.send(text)

    async def send_help(self, ctx):
        p = ctx.prefix
        embed = discord.Embed(
            title="ONYX • Filter System",
            description=(
                f"`{p}filter status` — view all filters\n"
                f"`{p}filter invites on --do jail` — jail members posting invites\n"
                f"`{p}filter links on --do delete` — delete posted links\n"
                f"`{p}filter spam on --threshold 5 --window 7 --do timeout`\n"
                f"`{p}filter repeats on --threshold 3 --window 30 --do warn`\n"
                f"`{p}filter invites off` — disable a filter\n\n"
                "**Filters:** `invites`, `links`, `spam`, `repeats`\n"
                "**Punishments:** `delete`, `warn`, `timeout`, `jail`\n"
                "**Options:** `--do`, `--threshold`, `--window`, `--duration` (timeout seconds)"
            ),
            color=discord.Color.from_rgb(44, 38, 67),
        )
        await ctx.send(embed=embed)

    async def send_status(self, ctx):
        embed = discord.Embed(title="ONYX • Filter Status", color=discord.Color.from_rgb(44, 38, 67))
        for name, (label, _, _) in FILTERS.items():
            cfg = await self.setting(ctx.guild.id, name)
            value = (
                f"Status: **{'Enabled' if cfg['enabled'] else 'Disabled'}**\n"
                f"Punishment: `{cfg['punishment']}`\n"
                f"Threshold: `{cfg['threshold']}` in `{cfg['window_seconds']}s`"
            )
            if cfg["punishment"] == "timeout":
                value += f"\nTimeout: `{cfg['timeout_seconds']}s`"
            embed.add_field(name=label, value=value, inline=False)
        await ctx.send(embed=embed)

    def detect(self, message, cfg):
        name, content = cfg["filter_name"], message.content or ""
        now = monotonic()
        if name in {"invites", "links"}:
            matched = bool(INVITE_RE.search(content)) if name == "invites" else bool(URL_RE.search(content))
            if not matched:
                return False, None
            key = (message.guild.id, message.author.id, name)
            bucket = self.activity[key]
            bucket.append(now)
            while bucket and now - bucket[0] > int(cfg["window_seconds"]):
                bucket.popleft()
            label = "Discord invite" if name == "invites" else "Link"
            return len(bucket) >= int(cfg["threshold"]), label
        if name == "spam":
            key = (message.guild.id, message.author.id, name)
            bucket = self.activity[key]
            bucket.append(now)
            while bucket and now - bucket[0] > int(cfg["window_seconds"]):
                bucket.popleft()
            return len(bucket) >= int(cfg["threshold"]), "Message spam"
        if name == "repeats":
            key = (message.guild.id, message.author.id)
            normalized = " ".join(content.casefold().split())
            previous = self.last_message.get(key)
            if normalized and previous == normalized:
                bucket = self.activity[(message.guild.id, message.author.id, name)]
                bucket.append(now)
                while bucket and now - bucket[0] > int(cfg["window_seconds"]):
                    bucket.popleft()
                return len(bucket) >= int(cfg["threshold"]), "Repeated messages"
            self.last_message[key] = normalized
        return False, None

    async def notify(self, message, text):
        try:
            await message.channel.send(text, delete_after=8, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

    async def punish(self, message, cfg, reason):
        member, guild = message.author, message.guild
        try:
            await message.delete()
        except discord.Forbidden:
            return False, "Missing Manage Messages permission."
        except discord.HTTPException:
            return False, "Discord refused to delete the message."

        action = cfg["punishment"]
        if action == "delete":
            return True, "Message deleted."
        if action == "warn":
            await self.notify(message, f"{member.mention}, your message was removed by the **{reason}** filter.")
            return True, "Message deleted; member notified."
        if action == "timeout":
            if not guild.me.guild_permissions.moderate_members:
                await self.notify(message, "ONYX needs Moderate Members to apply this filter's timeout.")
                return False, "Missing Moderate Members permission."
            try:
                await member.timeout(
                    discord.utils.utcnow() + timedelta(seconds=int(cfg["timeout_seconds"])),
                    reason=f"ONYX filter: {reason}",
                )
            except discord.HTTPException:
                await self.notify(message, "ONYX couldn't apply the timeout. Check permissions and role hierarchy.")
                return False, "Timeout failed due to permissions or role hierarchy."
            await self.notify(message, f"{member.mention} was timed out by the **{reason}** filter.")
            return True, "Message deleted and member timed out."
        if action == "jail":
            jail_cog = self.bot.get_cog("Jail")
            if jail_cog is None:
                await self.notify(message, "The ONYX jail system isn't loaded; no jail punishment was applied.")
                return False, "Jail system unavailable."
            ok, detail = await jail_cog.jail_member(
                guild, member, self.bot.user, f"Automatic filter punishment: {reason}"
            )
            await self.notify(message, f"{member.mention}: {detail}")
            return ok, detail
        return False, "Unknown punishment."

    async def log_action(self, guild, member, cfg, reason, result):
        row = await self.bot.db.fetchone(
            "SELECT log_channel_id FROM guild_settings WHERE guild_id=?", (guild.id,)
        )
        channel = guild.get_channel(int(row["log_channel_id"])) if row and row["log_channel_id"] else None
        if not channel:
            return
        embed = discord.Embed(
            title="ONYX • Filter Triggered",
            description=(
                f"Member: {member.mention} (`{member.id}`)\n"
                f"Filter: **{FILTERS[cfg['filter_name']][0]}**\n"
                f"Detection: {reason}\nPunishment: `{cfg['punishment']}`\nResult: {result}"
            ),
            color=discord.Color.orange(),
        )
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot or not isinstance(message.author, discord.Member):
            return
        if message.author.guild_permissions.manage_messages or message.author.guild_permissions.administrator:
            return
        ignored = await self.bot.db.fetchone(
            "SELECT 1 FROM automod_ignored WHERE guild_id=? AND channel_id=?",
            (message.guild.id, message.channel.id),
        )
        if ignored:
            return
        rows = await self.bot.db.fetchall(
            "SELECT * FROM onyx_filter_settings WHERE guild_id=? AND enabled=1",
            (message.guild.id,),
        )
        for cfg in rows:
            detected, reason = self.detect(message, cfg)
            if not detected:
                continue
            ok, result = await self.punish(message, cfg, reason)
            await self.bot.db.execute("""
                INSERT INTO onyx_automod_events (
                    guild_id,filter_name,user_id,channel_id,punishment,success,result,created_at
                ) VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
            """, (message.guild.id, cfg["filter_name"], message.author.id,
                  message.channel.id, cfg["punishment"], int(bool(ok)), str(result)[:500]))
            await self.log_action(message.guild, message.author, cfg, reason, result)
            key = (message.guild.id, message.author.id, cfg["filter_name"])
            if cfg["filter_name"] in {"spam", "repeats"}:
                self.activity[key].clear()
            break

    @commands.command(name="automod", help="Legacy alias notice for the new filter system.")
    @commands.has_guild_permissions(manage_guild=True)
    async def automod_legacy(self, ctx, *, args: str = ""):
        await ctx.send(f"AutoMod has been replaced. Use `{ctx.prefix}filter help` to configure filters.")


async def setup(bot):
    await bot.add_cog(FilterSystem(bot))
