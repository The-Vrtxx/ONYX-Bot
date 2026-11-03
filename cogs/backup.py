
import base64
import io
import json
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

log = logging.getLogger("bot.backup")


def pack_overwrites(channel):
    result = []
    for target, overwrite in channel.overwrites.items():
        kind = "role" if isinstance(target, discord.Role) else "member"
        allow, deny = overwrite.pair()
        result.append({"kind": kind, "id": target.id,
                       "allow": allow.value, "deny": deny.value})
    return result


class ServerBackup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="backup", help="DM a server backup and restore script.")
    @commands.guild_only()
    @commands.has_guild_permissions(administrator=True)
    async def backup(self, ctx):
        await ctx.send("Creating your backup. I'll DM you the files shortly.")
        guild = ctx.guild

        roles = [{
            "id": r.id, "name": r.name, "permissions": r.permissions.value,
            "colour": r.colour.value, "hoist": r.hoist,
            "mentionable": r.mentionable, "position": r.position
        } for r in sorted(guild.roles, key=lambda x: x.position)
          if not r.is_default() and not r.managed]

        channels = []
        for ch in guild.channels:
            item = {
                "id": ch.id, "name": ch.name, "type": str(ch.type),
                "position": ch.position, "category_id": ch.category_id,
                "overwrites": pack_overwrites(ch)
            }
            if isinstance(ch, (discord.TextChannel, discord.ForumChannel)):
                item.update(topic=ch.topic, nsfw=ch.nsfw,
                            slowmode_delay=ch.slowmode_delay)
            if isinstance(ch, (discord.VoiceChannel, discord.StageChannel)):
                item.update(bitrate=ch.bitrate, user_limit=ch.user_limit)
            channels.append(item)

        emojis = []
        for emoji in guild.emojis:
            try:
                data = await emoji.url.read()
                emojis.append({
                    "id": emoji.id, "name": emoji.name,
                    "image": base64.b64encode(data).decode("ascii")
                })
            except Exception:
                log.exception("Could not export emoji %s", emoji.name)

        member_roles = {
            str(m.id): [r.id for r in m.roles if not r.is_default() and not r.managed]
            for m in guild.members
            if any(not r.is_default() and not r.managed for r in m.roles)
        }

        backup = {
            "format_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "guild": {
                "id": guild.id, "name": guild.name,
                "description": guild.description,
                "verification_level": guild.verification_level.value,
                "default_notifications": guild.default_notifications.value,
                "explicit_content_filter": guild.explicit_content_filter.value,
                "afk_timeout": guild.afk_timeout,
                "system_channel_id": guild.system_channel_id,
                "rules_channel_id": guild.rules_channel_id,
                "public_updates_channel_id": guild.public_updates_channel_id,
                "afk_channel_id": guild.afk_channel_id
            },
            "roles": roles, "channels": channels,
            "emojis": emojis, "member_roles": member_roles,
            "limitations": [
                "Messages/history, integrations, managed roles, boosts and vanity URLs are not restorable.",
                "Member role assignments only apply to matching users already in the destination server.",
                "Some Discord-managed settings require manual setup."
            ]
        }

        json_bytes = json.dumps(backup, indent=2, ensure_ascii=False).encode("utf-8")
        script_bytes = RESTORE_SCRIPT.encode("utf-8")
        try:
            await ctx.author.send(
                content=(
                    f"**ONYX backup: {discord.utils.escape_markdown(guild.name)}**\n"
                    f"Saved {len(roles)} roles, {len(channels)} channels, and {len(emojis)} emojis.\n\n"
                    "**Restore instructions:** Keep both attachments together. Create a new server, "
                    "invite a bot with Manage Roles, Manage Channels, Manage Emojis and Stickers, "
                    "and View Channels. Set `DISCORD_TOKEN` and `TARGET_GUILD_ID`, install "
                    "`discord.py` using `pip install -U discord.py`, then run "
                    "`python onyx_restore_server.py`. The bot's highest role must be above "
                    "the roles it creates. The script will not delete existing server content."
                ),
                files=[
                    discord.File(io.BytesIO(json_bytes), filename=f"onyx_backup_{guild.id}.json"),
                    discord.File(io.BytesIO(script_bytes), filename="onyx_restore_server.py")
                ]
            )
        except discord.Forbidden:
            return await ctx.send("I couldn't DM you. Enable DMs from server members and run `,backup` again.")
        except discord.HTTPException:
            log.exception("Backup DM delivery failed")
            return await ctx.send("Backup data was created, but Discord could not deliver the DM attachments.")

        await ctx.send("Backup complete! Check your DMs for both files.")


RESTORE_SCRIPT = r"""
import os, json, base64
from pathlib import Path
import discord

# Keep this script beside onyx_backup_<server_id>.json.
# Install: python -m pip install -U discord.py
# Set DISCORD_TOKEN and TARGET_GUILD_ID, then run this script.

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("TARGET_GUILD_ID", "0") or 0)
backups = list(Path(__file__).parent.glob("onyx_backup_*.json"))
if not TOKEN or not GUILD_ID:
    raise SystemExit("Set DISCORD_TOKEN and TARGET_GUILD_ID first.")
if not backups:
    raise SystemExit("Backup JSON file not found beside this script.")
with backups[0].open(encoding="utf-8") as f:
    DATA = json.load(f)

intents = discord.Intents.default()
intents.members = True

class RestoreBot(discord.Client):
    async def on_ready(self):
        guild = self.get_guild(GUILD_ID)
        if guild is None:
            print("Bot is not in the target server, or TARGET_GUILD_ID is incorrect.")
            await self.close()
            return
        await self.restore(guild)
        print("Restore finished. Review the new server for anything requiring manual setup.")
        await self.close()

    async def restore(self, guild):
        role_map = {}
        for item in sorted(DATA["roles"], key=lambda x: x.get("position", 0)):
            role = discord.utils.get(guild.roles, name=item["name"])
            if role is None:
                try:
                    role = await guild.create_role(
                        name=item["name"],
                        permissions=discord.Permissions(item["permissions"]),
                        colour=discord.Colour(item.get("colour", 0)),
                        hoist=item.get("hoist", False),
                        mentionable=item.get("mentionable", False),
                        reason="ONYX backup restore"
                    )
                    print("Created role:", role.name)
                except discord.HTTPException as e:
                    print("Role skipped:", item["name"], e)
                    continue
            role_map[item["id"]] = role

        async def get_overwrites(item):
            result = {}
            for entry in item.get("overwrites", []):
                target = (role_map.get(entry["id"]) if entry["kind"] == "role"
                          else guild.get_member(entry["id"]))
                if target is not None:
                    result[target] = discord.PermissionOverwrite.from_pair(
                        discord.Permissions(entry["allow"]),
                        discord.Permissions(entry["deny"])
                    )
            return result

        channel_map = {}
        saved = DATA["channels"]
        for item in [x for x in saved if x["type"] == "category"]:
            category = discord.utils.get(guild.categories, name=item["name"])
            if category is None:
                try:
                    category = await guild.create_category(
                        item["name"], overwrites=await get_overwrites(item),
                        reason="ONYX backup restore"
                    )
                except discord.HTTPException as e:
                    print("Category skipped:", item["name"], e)
                    continue
            channel_map[item["id"]] = category

        for item in [x for x in saved if x["type"] != "category"]:
            category = channel_map.get(item.get("category_id"))
            existing = discord.utils.get(guild.channels, name=item["name"], category=category)
            if existing:
                channel_map[item["id"]] = existing
                continue
            common = {
                "category": category,
                "overwrites": await get_overwrites(item),
                "reason": "ONYX backup restore"
            }
            try:
                kind = item["type"]
                if kind == "text":
                    channel = await guild.create_text_channel(
                        item["name"], topic=item.get("topic"),
                        nsfw=item.get("nsfw", False),
                        slowmode_delay=item.get("slowmode_delay", 0), **common
                    )
                elif kind == "voice":
                    channel = await guild.create_voice_channel(
                        item["name"], bitrate=item.get("bitrate"),
                        user_limit=item.get("user_limit", 0), **common
                    )
                elif kind == "stage_voice":
                    channel = await guild.create_stage_channel(
                        item["name"], bitrate=item.get("bitrate"),
                        user_limit=item.get("user_limit", 0), **common
                    )
                elif kind == "forum":
                    channel = await guild.create_forum(
                        item["name"], topic=item.get("topic"),
                        nsfw=item.get("nsfw", False),
                        slowmode_delay=item.get("slowmode_delay", 0), **common
                    )
                else:
                    print("Unsupported channel type:", kind, item["name"])
                    continue
                channel_map[item["id"]] = channel
                print("Created channel:", channel.name)
            except (discord.HTTPException, TypeError) as e:
                print("Channel skipped:", item["name"], e)

        # Reapply saved roles to users already present in the destination server.
        for uid, old_roles in DATA.get("member_roles", {}).items():
            member = guild.get_member(int(uid))
            if member is None:
                continue
            add = [role_map[rid] for rid in old_roles
                   if rid in role_map and role_map[rid] not in member.roles]
            if add:
                try:
                    await member.add_roles(*add, reason="ONYX backup restore")
                except discord.HTTPException as e:
                    print("Could not restore roles for", member, e)

        for item in DATA.get("emojis", []):
            if discord.utils.get(guild.emojis, name=item["name"]):
                continue
            try:
                await guild.create_custom_emoji(
                    name=item["name"], image=base64.b64decode(item["image"]),
                    reason="ONYX backup restore"
                )
                print("Created emoji:", item["name"])
            except discord.HTTPException as e:
                print("Emoji skipped:", item["name"], e)

client = RestoreBot(intents=intents)
client.run(TOKEN)
"""

async def setup(bot):
    await bot.add_cog(ServerBackup(bot))
