import hashlib
import os
import time
from urllib.parse import urlencode

import aiohttp
import discord
from discord.ext import commands


API_URL = "https://ws.audioscrobbler.com/2.0/"
AUTH_URL = "https://www.last.fm/api/auth/"
API_KEY = os.getenv("LASTFM_API_KEY", "").strip()
API_SECRET = os.getenv("LASTFM_SHARED_SECRET", "").strip()
COLOR = discord.Color.from_rgb(186, 85, 211)
PERIODS = {
    "overall": "Overall",
    "7day": "Last 7 days",
    "1month": "Last month",
    "3month": "Last 3 months",
    "6month": "Last 6 months",
    "12month": "Last 12 months",
}
PERIOD_ALIASES = {
    "all": "overall", "week": "7day", "7d": "7day",
    "month": "1month", "3m": "3month", "6m": "6month",
    "year": "12month", "12m": "12month",
}


class LastFMError(Exception):
    pass


class LastFM(commands.Cog):
    """Last.fm account linking, listening stats, and music discovery."""

    def __init__(self, bot):
        self.bot = bot
        self.http = None

    async def cog_load(self):
        self.http = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20),
            headers={"User-Agent": "ONYX-Discord-Bot/1.0 (Last.fm integration)"}
        )
        # These tables are created here so existing PostgreSQL and SQLite
        # installations are migrated without replacing database.py.
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS lastfm_auth_pending (
                user_id BIGINT PRIMARY KEY,
                token TEXT NOT NULL,
                created_at BIGINT NOT NULL
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS lastfm_auth_sessions (
                user_id BIGINT PRIMARY KEY,
                username TEXT NOT NULL,
                session_key TEXT NOT NULL,
                connected_at BIGINT NOT NULL
            )
        """)

    async def cog_unload(self):
        if self.http and not self.http.closed:
            await self.http.close()

    def ensure_configured(self, authentication=False):
        if not API_KEY:
            raise LastFMError("`LASTFM_API_KEY` is missing from Render environment variables.")
        if authentication and not API_SECRET:
            raise LastFMError("`LASTFM_SHARED_SECRET` is missing from Render environment variables.")

    @staticmethod
    def signature(params, secret):
        raw = "".join(
            f"{key}{params[key]}"
            for key in sorted(params)
            if key not in {"format", "callback", "api_sig"}
        ) + secret
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    async def api(self, method, params=None, authenticated=False):
        self.ensure_configured(authentication=authenticated)
        payload = dict(params or {})
        payload["method"] = method
        payload["api_key"] = API_KEY
        payload["format"] = "json"

        if authenticated:
            if not API_SECRET:
                raise LastFMError("`LASTFM_SHARED_SECRET` is not configured.")
            payload["api_sig"] = self.signature(payload, API_SECRET)

        if not self.http or self.http.closed:
            self.http = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=20),
                headers={"User-Agent": "ONYX-Discord-Bot/1.0 (Last.fm integration)"}
            )

        try:
            async with self.http.get(API_URL, params=payload) as response:
                data = await response.json(content_type=None)
                if response.status != 200:
                    raise LastFMError(f"Last.fm returned HTTP {response.status}.")
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise LastFMError("Couldn't reach Last.fm right now. Please try again shortly.") from exc

        if not isinstance(data, dict):
            raise LastFMError("Last.fm returned an unexpected response.")
        if "error" in data:
            message = data.get("message", "Last.fm request failed.")
            raise LastFMError(f"{message} (Last.fm error {data['error']})")
        return data

    async def account_for(self, discord_user):
        row = await self.bot.db.fetchone(
            "SELECT username FROM lastfm_auth_sessions WHERE user_id=?",
            (discord_user.id,)
        )
        if row:
            return row["username"], True

        # Backward compatibility with accounts linked using the old username-only flow.
        row = await self.bot.db.fetchone(
            "SELECT username FROM lastfm_users WHERE user_id=?",
            (discord_user.id,)
        )
        if row:
            return row["username"], False
        return None, False

    async def resolve_account(self, ctx, member=None):
        member = member or ctx.author
        username, authenticated = await self.account_for(member)
        if not username:
            if member.id == ctx.author.id:
                await ctx.send(
                    f"You haven't connected Last.fm yet. Use `{ctx.prefix}lastfm connect`."
                )
            else:
                await ctx.send(f"{member.display_name} hasn't connected a Last.fm account.")
            return None, None, None
        return username, authenticated, member

    @staticmethod
    def image_url(item):
        images = item.get("image", []) if isinstance(item, dict) else []
        for image in reversed(images):
            url = image.get("#text")
            if url:
                return url
        return None

    @staticmethod
    def safe_int(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def clean(value, fallback="Unknown"):
        if value is None or str(value).strip() == "":
            return fallback
        return str(value)

    async def send_error(self, ctx, exc):
        await ctx.send(f"⚠️ {exc}")

    async def fetch_recent_track(self, username):
        data = await self.api("user.getRecentTracks", {"user": username, "limit": 1})
        tracks = data.get("recenttracks", {}).get("track", [])
        if isinstance(tracks, dict):
            tracks = [tracks]
        if not tracks:
            raise LastFMError("No recent tracks were found for this account.")
        return tracks[0]

    def track_embed(self, track, username, title=None):
        artist_data = track.get("artist", {})
        artist = artist_data.get("#text") if isinstance(artist_data, dict) else artist_data
        album_data = track.get("album", {})
        album = album_data.get("#text") if isinstance(album_data, dict) else album_data
        playing = track.get("@attr", {}).get("nowplaying") == "true"
        name = self.clean(track.get("name"), "Unknown track")
        artist = self.clean(artist, "Unknown artist")
        embed = discord.Embed(
            title=title or ("🎧 Now Playing" if playing else "🎵 Last Played"),
            description=f"**[{name}]({track.get('url', 'https://www.last.fm')})**\nby **{artist}**",
            color=COLOR
        )
        if album:
            embed.add_field(name="Album", value=album, inline=True)
        if not playing and track.get("date", {}).get("uts"):
            timestamp = self.safe_int(track["date"]["uts"])
            if timestamp:
                embed.add_field(
                    name="Played",
                    value=discord.utils.format_dt(
                        discord.utils.utcnow().fromtimestamp(timestamp, tz=discord.utils.utcnow().tzinfo),
                        "R"
                    ),
                    inline=True
                )
        image = self.image_url(track)
        if image:
            embed.set_thumbnail(url=image)
        embed.set_footer(text=f"Last.fm • {username}")
        return embed

    async def top_list(self, ctx, method, key, label, member, period, limit):
        username, _, member = await self.resolve_account(ctx, member)
        if not username:
            return
        period = PERIOD_ALIASES.get(period.casefold(), period.casefold())
        if period not in PERIODS:
            return await ctx.send(
                "Period must be `overall`, `7day`, `1month`, `3month`, `6month`, or `12month`."
            )
        limit = max(1, min(limit, 10))
        try:
            data = await self.api(method, {"user": username, "period": period, "limit": limit})
            entries = data.get(key, {}).get(key[:-1] if key.endswith("s") else key, [])
            # Last.fm response collection keys are singular per method.
            if not entries:
                singular = {"toptracks": "track", "topartists": "artist", "topalbums": "album"}[key]
                entries = data.get(key, {}).get(singular, [])
            if isinstance(entries, dict):
                entries = [entries]
            if not entries:
                return await ctx.send("Last.fm didn't return any chart entries for that period.")
            lines = []
            for index, item in enumerate(entries[:limit], 1):
                name = self.clean(item.get("name"))
                plays = self.safe_int(item.get("playcount"))
                if key == "toptracks":
                    artist_data = item.get("artist", {})
                    artist = artist_data.get("name") if isinstance(artist_data, dict) else artist_data
                    name = f"{name} — {self.clean(artist)}"
                lines.append(f"`{index:02}` **{name}** · {plays:,} plays")
            embed = discord.Embed(
                title=f"{label} • {member.display_name}",
                description="\n".join(lines),
                color=COLOR
            )
            embed.set_footer(text=f"Last.fm • {username} • {PERIODS[period]}")
            if entries:
                image = self.image_url(entries[0])
                if image:
                    embed.set_thumbnail(url=image)
            await ctx.send(embed=embed)
        except LastFMError as exc:
            await self.send_error(ctx, exc)

    @commands.group(name="lastfm", invoke_without_command=True, help="Last.fm account and music commands.")
    async def lastfm(self, ctx):
        embed = discord.Embed(
            title="ONYX • Last.fm",
            description=(
                f"`{ctx.prefix}lastfm connect` — connect your Last.fm account\n"
                f"`{ctx.prefix}lastfm finish` — finish authorization after approving\n"
                f"`{ctx.prefix}lastfm logout` — disconnect your account\n"
                f"`{ctx.prefix}lastfm account` — view your connection\n"
                f"`{ctx.prefix}lastfm nowplaying [@member]`\n"
                f"`{ctx.prefix}lastfm recent [@member] [limit]`\n"
                f"`{ctx.prefix}lastfm toptracks [@member] [period]`\n"
                f"`{ctx.prefix}lastfm topartists [@member] [period]`\n"
                f"`{ctx.prefix}lastfm topalbums [@member] [period]`\n"
                f"`{ctx.prefix}lastfm profile [@member]`\n"
                f"`{ctx.prefix}lastfm artist <name>`\n"
                f"`{ctx.prefix}lastfm album <artist> | <album>`\n"
                f"`{ctx.prefix}lastfm track <artist> | <track>`\n"
                f"`{ctx.prefix}lastfm compare @member`"
            ),
            color=COLOR
        )
        embed.set_footer(text="Periods: overall, 7day, 1month, 3month, 6month, 12month")
        await ctx.send(embed=embed)

    @lastfm.command(name="connect", help="Start secure Last.fm authorization.")
    async def connect(self, ctx):
        try:
            self.ensure_configured(authentication=True)
            data = await self.api("auth.getToken", authenticated=True)
            token = data.get("token")
            if not token:
                raise LastFMError("Last.fm didn't return an authorization token.")
            await self.bot.db.execute(
                "INSERT INTO lastfm_auth_pending (user_id,token,created_at) VALUES (?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET token=excluded.token, created_at=excluded.created_at",
                (ctx.author.id, token, int(time.time()))
            )
            url = AUTH_URL + "?" + urlencode({"api_key": API_KEY, "token": token})
            embed = discord.Embed(
                title="Connect your Last.fm account",
                description=(
                    f"[Authorize ONYX on Last.fm]({url})\n\n"
                    "1. Open the link and sign in to Last.fm.\n"
                    "2. Approve ONYX.\n"
                    f"3. Return to Discord and run `{ctx.prefix}lastfm finish`.\n\n"
                    "This authorization token expires after about 60 minutes."
                ),
                color=COLOR
            )
            try:
                await ctx.author.send(embed=embed)
                await ctx.send("I've sent your Last.fm authorization link to your DMs.")
            except discord.Forbidden:
                await ctx.send(embed=embed)
        except LastFMError as exc:
            await self.send_error(ctx, exc)

    @lastfm.command(name="finish", help="Complete Last.fm authorization after approving ONYX.")
    async def finish(self, ctx):
        self.ensure_configured(authentication=True)
        row = await self.bot.db.fetchone(
            "SELECT token,created_at FROM lastfm_auth_pending WHERE user_id=?",
            (ctx.author.id,)
        )
        if not row:
            return await ctx.send(f"No pending authorization found. Start with `{ctx.prefix}lastfm connect`.")
        if int(time.time()) - int(row["created_at"]) > 3600:
            await self.bot.db.execute("DELETE FROM lastfm_auth_pending WHERE user_id=?", (ctx.author.id,))
            return await ctx.send("That authorization expired. Run `,lastfm connect` again.")
        try:
            data = await self.api("auth.getSession", {"token": row["token"]}, authenticated=True)
            session = data.get("session", {})
            username = session.get("name")
            session_key = session.get("key")
            if not username or not session_key:
                raise LastFMError("Last.fm didn't return a valid account session.")
            await self.bot.db.execute(
                "INSERT INTO lastfm_auth_sessions (user_id,username,session_key,connected_at) "
                "VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                "username=excluded.username,session_key=excluded.session_key,connected_at=excluded.connected_at",
                (ctx.author.id, username, session_key, int(time.time()))
            )
            await self.bot.db.execute("DELETE FROM lastfm_auth_pending WHERE user_id=?", (ctx.author.id,))
            # Keep legacy username lookup in sync for compatibility.
            await self.bot.db.execute(
                "INSERT INTO lastfm_users (user_id,username) VALUES (?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
                (ctx.author.id, username)
            )
            await ctx.send(f"✅ Your Last.fm account **{username}** is now connected to ONYX.")
        except LastFMError as exc:
            await self.send_error(ctx, exc)

    @lastfm.command(name="logout", aliases=["disconnect", "unlink"], help="Disconnect your Last.fm account from ONYX.")
    async def logout(self, ctx):
        await self.bot.db.execute("DELETE FROM lastfm_auth_sessions WHERE user_id=?", (ctx.author.id,))
        await self.bot.db.execute("DELETE FROM lastfm_auth_pending WHERE user_id=?", (ctx.author.id,))
        await self.bot.db.execute("DELETE FROM lastfm_users WHERE user_id=?", (ctx.author.id,))
        await ctx.send("Your Last.fm account has been disconnected from ONYX.")

    @lastfm.command(name="account", help="Show the Last.fm account connected to your Discord account.")
    async def account(self, ctx):
        username, authenticated = await self.account_for(ctx.author)
        if not username:
            return await ctx.send(f"No Last.fm account connected. Use `{ctx.prefix}lastfm connect`.")
        embed = discord.Embed(title="Last.fm Connection", color=COLOR)
        embed.add_field(name="Username", value=f"[{username}](https://www.last.fm/user/{username})")
        embed.add_field(name="Connection", value="Authorized session" if authenticated else "Username-only legacy link")
        embed.add_field(name="Discord account", value=ctx.author.mention)
        await ctx.send(embed=embed)

    @lastfm.command(name="status", help="Check whether your Last.fm connection is available.")
    async def status(self, ctx):
        username, authenticated = await self.account_for(ctx.author)
        if not username:
            return await ctx.send("Your Last.fm account isn't connected.")
        try:
            await self.api("user.getInfo", {"user": username})
            await ctx.send(f"✅ Last.fm is responding for **{username}**. Connection type: {'authorized' if authenticated else 'username-only'}.")
        except LastFMError as exc:
            await self.send_error(ctx, exc)

    @lastfm.command(name="link", help="Legacy option: link a public Last.fm username without authorization.")
    async def link(self, ctx, username: str):
        try:
            data = await self.api("user.getInfo", {"user": username})
            actual = data.get("user", {}).get("name")
            if not actual:
                raise LastFMError("That Last.fm user wasn't found.")
            await self.bot.db.execute(
                "INSERT INTO lastfm_users (user_id,username) VALUES (?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
                (ctx.author.id, actual)
            )
            await ctx.send(f"Linked public Last.fm profile **{actual}**. Use `,lastfm connect` for an authorized connection.")
        except LastFMError as exc:
            await self.send_error(ctx, exc)

    @lastfm.command(name="nowplaying", aliases=["np"], help="Show your or another member's current/most recent track.")
    async def nowplaying(self, ctx, member: discord.Member = None):
        username, _, _ = await self.resolve_account(ctx, member)
        if not username:
            return
        try:
            track = await self.fetch_recent_track(username)
            await ctx.send(embed=self.track_embed(track, username))
        except LastFMError as exc:
            await self.send_error(ctx, exc)

    @lastfm.command(name="recent", aliases=["recenttracks"], help="Show recent tracks: recent [member] [limit].")
    async def recent(self, ctx, member: discord.Member = None, limit: int = 5):
        username, _, member = await self.resolve_account(ctx, member)
        if not username:
            return
        limit = max(1, min(limit, 10))
        try:
            data = await self.api("user.getRecentTracks", {"user": username, "limit": limit})
            tracks = data.get("recenttracks", {}).get("track", [])
            if isinstance(tracks, dict):
                tracks = [tracks]
            if not tracks:
                return await ctx.send("No recent tracks were found.")
            lines = []
            for index, track in enumerate(tracks[:limit], 1):
                artist_data = track.get("artist", {})
                artist = artist_data.get("#text") if isinstance(artist_data, dict) else artist_data
                marker = " 🎧" if track.get("@attr", {}).get("nowplaying") == "true" else ""
                lines.append(f"`{index:02}` **{self.clean(track.get('name'))}** — {self.clean(artist)}{marker}")
            embed = discord.Embed(title=f"Recent Tracks • {member.display_name}", description="\n".join(lines), color=COLOR)
            embed.set_footer(text=f"Last.fm • {username}")
            image = self.image_url(tracks[0])
            if image:
                embed.set_thumbnail(url=image)
            await ctx.send(embed=embed)
        except LastFMError as exc:
            await self.send_error(ctx, exc)

    @lastfm.command(name="toptracks", aliases=["top_tracks"], help="Show top tracks. Optional period: overall, 7day, 1month, 3month, 6month, 12month.")
    async def toptracks(self, ctx, member: discord.Member = None, period: str = "overall", limit: int = 10):
        await self.top_list(ctx, "user.getTopTracks", "toptracks", "Top Tracks", member, period, limit)

    @lastfm.command(name="topartists", aliases=["top_artists"], help="Show top artists for a period.")
    async def topartists(self, ctx, member: discord.Member = None, period: str = "overall", limit: int = 10):
        await self.top_list(ctx, "user.getTopArtists", "topartists", "Top Artists", member, period, limit)

    @lastfm.command(name="topalbums", aliases=["top_albums"], help="Show top albums for a period.")
    async def topalbums(self, ctx, member: discord.Member = None, period: str = "overall", limit: int = 10):
        await self.top_list(ctx, "user.getTopAlbums", "topalbums", "Top Albums", member, period, limit)

    @lastfm.command(name="profile", help="Show Last.fm listening profile statistics.")
    async def profile(self, ctx, member: discord.Member = None):
        username, _, member = await self.resolve_account(ctx, member)
        if not username:
            return
        try:
            data = await self.api("user.getInfo", {"user": username})
            user = data.get("user", {})
            embed = discord.Embed(
                title=f"Last.fm Profile • {username}",
                url=user.get("url"),
                color=COLOR
            )
            image = self.image_url(user)
            if image:
                embed.set_thumbnail(url=image)
            embed.add_field(name="Scrobbles", value=f"{self.safe_int(user.get('playcount')):,}", inline=True)
            embed.add_field(name="Registered", value=user.get("registered", {}).get("#text", "Unknown"), inline=True)
            embed.add_field(name="Country", value=self.clean(user.get("country"), "Not set"), inline=True)
            embed.add_field(name="Listeners", value=f"{self.safe_int(user.get('subscriber')):,} subscriber status", inline=True)
            embed.set_footer(text=f"Linked to {member.display_name}'s Discord account")
            await ctx.send(embed=embed)
        except LastFMError as exc:
            await self.send_error(ctx, exc)

    @lastfm.command(name="artist", help="Look up an artist: ,lastfm artist <artist name>.")
    async def artist(self, ctx, *, name: str):
        try:
            data = await self.api("artist.getInfo", {"artist": name})
            artist = data.get("artist", {})
            stats = artist.get("stats", {})
            bio = artist.get("bio", {}).get("summary", "No biography available.")
            bio = bio.replace("<a href=", "[source link](")
            embed = discord.Embed(title=artist.get("name", name), url=artist.get("url"), description=bio[:3500], color=COLOR)
            embed.add_field(name="Listeners", value=f"{self.safe_int(stats.get('listeners')):,}", inline=True)
            embed.add_field(name="Playcount", value=f"{self.safe_int(stats.get('playcount')):,}", inline=True)
            image = self.image_url(artist)
            if image:
                embed.set_thumbnail(url=image)
            await ctx.send(embed=embed)
        except LastFMError as exc:
            await self.send_error(ctx, exc)

    @lastfm.command(name="album", help="Look up an album: ,lastfm album <artist> | <album>.")
    async def album(self, ctx, *, query: str):
        parts = [part.strip() for part in query.split("|", 1)]
        if len(parts) != 2 or not all(parts):
            return await ctx.send("Use `,lastfm album Artist Name | Album Name`.")
        try:
            data = await self.api("album.getInfo", {"artist": parts[0], "album": parts[1]})
            album = data.get("album", {})
            tracks = album.get("tracks", {}).get("track", [])
            if isinstance(tracks, dict):
                tracks = [tracks]
            embed = discord.Embed(title=album.get("name", parts[1]), url=album.get("url"), description=f"by **{album.get('artist', parts[0])}**", color=COLOR)
            embed.add_field(name="Listeners", value=f"{self.safe_int(album.get('listeners')):,}", inline=True)
            embed.add_field(name="Playcount", value=f"{self.safe_int(album.get('playcount')):,}", inline=True)
            if tracks:
                embed.add_field(name="Tracks", value="\n".join(f"`{i}.` {t.get('name', 'Unknown')}" for i, t in enumerate(tracks[:15], 1)), inline=False)
            image = self.image_url(album)
            if image:
                embed.set_thumbnail(url=image)
            await ctx.send(embed=embed)
        except LastFMError as exc:
            await self.send_error(ctx, exc)

    @lastfm.command(name="track", help="Look up a track: ,lastfm track <artist> | <track>.")
    async def track(self, ctx, *, query: str):
        parts = [part.strip() for part in query.split("|", 1)]
        if len(parts) != 2 or not all(parts):
            return await ctx.send("Use `,lastfm track Artist Name | Track Name`.")
        try:
            data = await self.api("track.getInfo", {"artist": parts[0], "track": parts[1]})
            track = data.get("track", {})
            embed = discord.Embed(
                title=track.get("name", parts[1]),
                url=track.get("url"),
                description=f"by **{track.get('artist', {}).get('name', parts[0])}**",
                color=COLOR
            )
            embed.add_field(name="Listeners", value=f"{self.safe_int(track.get('listeners')):,}", inline=True)
            embed.add_field(name="Playcount", value=f"{self.safe_int(track.get('playcount')):,}", inline=True)
            album = track.get("album", {}).get("title")
            if album:
                embed.add_field(name="Album", value=album, inline=False)
            if track.get("wiki", {}).get("summary"):
                embed.add_field(name="About", value=track["wiki"]["summary"][:1000], inline=False)
            image = self.image_url(track.get("album", {}))
            if image:
                embed.set_thumbnail(url=image)
            await ctx.send(embed=embed)
        except LastFMError as exc:
            await self.send_error(ctx, exc)

    @lastfm.command(name="compare", help="Compare your top artists with another member.")
    async def compare(self, ctx, member: discord.Member):
        if member.id == ctx.author.id:
            return await ctx.send("Mention someone else to compare listening tastes.")
        first, _, _ = await self.resolve_account(ctx, ctx.author)
        second, _, _ = await self.resolve_account(ctx, member)
        if not first or not second:
            return
        try:
            first_data, second_data = await self.api("user.getTopArtists", {"user": first, "limit": 50}), await self.api("user.getTopArtists", {"user": second, "limit": 50})
            def names(data):
                items = data.get("topartists", {}).get("artist", [])
                if isinstance(items, dict):
                    items = [items]
                return {item.get("name", "").casefold(): item.get("name", "") for item in items}
            a, b = names(first_data), names(second_data)
            shared = sorted(set(a) & set(b))
            union = set(a) | set(b)
            score = round((len(shared) / len(union)) * 100) if union else 0
            embed = discord.Embed(title="🎶 Last.fm Taste Comparison", color=COLOR)
            embed.description = f"**{ctx.author.display_name}** and **{member.display_name}** share **{score}%** of their top-50 artist lists."
            embed.add_field(name=f"Shared artists ({len(shared)})", value=", ".join(a[x] for x in shared[:20]) or "No overlap in the top 50.", inline=False)
            embed.set_footer(text="Based on top artists, not a definitive measure of musical compatibility.")
            await ctx.send(embed=embed)
        except LastFMError as exc:
            await self.send_error(ctx, exc)


async def setup(bot):
    await bot.add_cog(LastFM(bot))
