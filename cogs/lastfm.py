import os
import aiohttp
import discord
from discord.ext import commands

API_KEY = os.getenv("LASTFM_API_KEY")

class LastFM(commands.Cog):
    def __init__(self, bot): self.bot = bot

    async def request(self, method, username):
        if not API_KEY: raise RuntimeError("LASTFM_API_KEY is not configured in .env")
        params = {"method": method, "user": username, "api_key": API_KEY, "format": "json"}
        async with aiohttp.ClientSession() as session:
            async with session.get("https://ws.audioscrobbler.com/2.0/", params=params, timeout=15) as response:
                data = await response.json(content_type=None)
                if response.status != 200 or "error" in data:
                    raise ValueError(data.get("message", "Last.fm request failed"))
                return data

    @commands.group(name="lastfm", invoke_without_command=True)
    async def lastfm(self, ctx):
        await ctx.send(f"Use `{ctx.prefix}lastfm link <username>`, `{ctx.prefix}lastfm nowplaying [@member]`, or `{ctx.prefix}lastfm unlink`.")

    @lastfm.command(name="link", help="Link your Last.fm username.")
    async def link(self, ctx: commands.Context, username: str):
        try:
            data = await self.request("user.getinfo", username)
            actual = data["user"]["name"]
        except (RuntimeError, ValueError, KeyError, aiohttp.ClientError) as exc:
            return await ctx.send(f"Couldn't link that account: {exc}",)
        await self.bot.db.execute("INSERT INTO lastfm_users VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username", (ctx.author.id, actual))
        await ctx.send(f"Linked your Last.fm account: **{actual}**",)

    @lastfm.command(name="nowplaying", help="Show your currently playing or most recent track.")
    async def nowplaying(self, ctx: commands.Context, member: discord.User = None):
        member = member or ctx.author
        row = await self.bot.db.fetchone("SELECT username FROM lastfm_users WHERE user_id=?", (member.id,))
        if not row: return await ctx.send("That user hasn't linked a Last.fm account.",)
        try:
            data = await self.request("user.getrecenttracks", row["username"])
            track = data["recenttracks"]["track"][0]
            artist = track["artist"].get("#text", "Unknown artist")
            album = track.get("album", {}).get("#text", "")
            title = track.get("name", "Unknown track")
            playing = track.get("@attr", {}).get("nowplaying") == "true"
            embed = discord.Embed(title="🎧 Now playing" if playing else "🎵 Recently played", help=f"**{title}**\nby {artist}", color=discord.Color.from_rgb(186, 85, 211))
            if album: embed.add_field(name="Album", value=album)
            embed.set_footer(text=f"Last.fm • {row['username']}")
            images = track.get("image", [])
            if images and images[-1].get("#text"): embed.set_thumbnail(url=images[-1]["#text"])
            await ctx.send(embed=embed)
        except (RuntimeError, ValueError, KeyError, IndexError, aiohttp.ClientError) as exc:
            await ctx.send(f"Last.fm couldn't return a track: {exc}",)

    @lastfm.command(name="unlink", help="Unlink your Last.fm account.")
    async def unlink(self, ctx: commands.Context):
        await self.bot.db.execute("DELETE FROM lastfm_users WHERE user_id=?", (ctx.author.id,))
        await ctx.send("Your Last.fm account has been unlinked.",)

async def setup(bot): await bot.add_cog(LastFM(bot))
