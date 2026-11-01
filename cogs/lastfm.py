import os
import aiohttp
import discord
from discord import app_commands
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

    lastfm = app_commands.Group(name="lastfm", description="Last.fm account tools")

    @lastfm.command(name="link", description="Link your Last.fm username.")
    async def link(self, interaction: discord.Interaction, username: str):
        try:
            data = await self.request("user.getinfo", username)
            actual = data["user"]["name"]
        except (RuntimeError, ValueError, KeyError, aiohttp.ClientError) as exc:
            return await interaction.response.send_message(f"Couldn't link that account: {exc}", ephemeral=True)
        await self.bot.db.execute("INSERT INTO lastfm_users VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username", (interaction.user.id, actual))
        await interaction.response.send_message(f"Linked your Last.fm account: **{actual}**", ephemeral=True)

    @lastfm.command(name="nowplaying", description="Show your currently playing or most recent track.")
    async def nowplaying(self, interaction: discord.Interaction, member: discord.User = None):
        member = member or interaction.user
        row = await self.bot.db.fetchone("SELECT username FROM lastfm_users WHERE user_id=?", (member.id,))
        if not row: return await interaction.response.send_message("That user hasn't linked a Last.fm account.", ephemeral=True)
        try:
            data = await self.request("user.getrecenttracks", row["username"])
            track = data["recenttracks"]["track"][0]
            artist = track["artist"].get("#text", "Unknown artist")
            album = track.get("album", {}).get("#text", "")
            title = track.get("name", "Unknown track")
            playing = track.get("@attr", {}).get("nowplaying") == "true"
            embed = discord.Embed(title="🎧 Now playing" if playing else "🎵 Recently played", description=f"**{title}**\nby {artist}", color=discord.Color.from_rgb(186, 85, 211))
            if album: embed.add_field(name="Album", value=album)
            embed.set_footer(text=f"Last.fm • {row['username']}")
            images = track.get("image", [])
            if images and images[-1].get("#text"): embed.set_thumbnail(url=images[-1]["#text"])
            await interaction.response.send_message(embed=embed)
        except (RuntimeError, ValueError, KeyError, IndexError, aiohttp.ClientError) as exc:
            await interaction.response.send_message(f"Last.fm couldn't return a track: {exc}", ephemeral=True)

    @lastfm.command(name="unlink", description="Unlink your Last.fm account.")
    async def unlink(self, interaction: discord.Interaction):
        await self.bot.db.execute("DELETE FROM lastfm_users WHERE user_id=?", (interaction.user.id,))
        await interaction.response.send_message("Your Last.fm account has been unlinked.", ephemeral=True)

async def setup(bot): await bot.add_cog(LastFM(bot))
