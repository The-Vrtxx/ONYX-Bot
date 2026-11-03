import base64
import json
import logging
import uuid
from datetime import datetime, timezone

import discord
from discord.ext import commands

log = logging.getLogger("bot.backup")
BACKUP_FORMAT_VERSION = 2
MAX_BACKUP_BYTES = 9 * 1024 * 1024


def pack_overwrites(channel):
    result = []
    for target, overwrite in channel.overwrites.items():
        kind = "role" if isinstance(target, discord.Role) else "member"
        allow, deny = overwrite.pair()
        result.append({
            "kind": kind,
            "id": target.id,
            "allow": allow.value,
            "deny": deny.value,
        })
    return result


def make_backup_id():
    # 128-bit random identifier; unique per backup, not per server.
    return uuid.uuid4().hex


class ServerBackup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(
        name="backup",
        invoke_without_command=True,
        help="Create or restore an ONYX server backup."
    )
    @commands.guild_only()
    @commands.has_guild_permissions(administrator=True)
    async def backup(self, ctx):
        await self.create_backup(ctx)

    @backup.command(name="create", help="Create a backup and DM its unique ID.")
    async def backup_create(self, ctx):
        await self.create_backup(ctx)

    async def create_backup(self, ctx):
        guild = ctx.guild
        backup_id = make_backup_id()
        await ctx.send("Creating your backup. I'll DM you the backup file and its unique ID.")

        roles = [{
            "id": r.id,
            "name": r.name,
            "permissions": r.permissions.value,
            "colour": r.colour.value,
            "hoist": r.hoist,
            "mentionable": r.mentionable,
            "position": r.position,
        } for r in sorted(guild.roles, key=lambda x: x.position)
          if not r.is_default() and not r.managed]

        channels = []
        for ch in guild.channels:
            item = {
                "id": ch.id,
                "name": ch.name,
                "type": str(ch.type),
                "position": ch.position,
                "category_id": ch.category_id,
                "overwrites": pack_overwrites(ch),
            }
            if isinstance(ch, (discord.TextChannel, discord.ForumChannel)):
                item.update(
                    topic=ch.topic,
                    nsfw=ch.nsfw,
                    slowmode_delay=ch.slowmode_delay,
                )
            if isinstance(ch, (discord.VoiceChannel, discord.StageChannel)):
                item.update(bitrate=ch.bitrate, user_limit=ch.user_limit)
            channels.append(item)

        emojis = []
        for emoji in guild.emojis:
            try:
                image_data = await emoji.url.read()
                emojis.append({
                    "id": emoji.id,
                    "name": emoji.name,
                    "image": base64.b64encode(image_data).decode("ascii"),
                })
            except Exception:
                log.exception("Could not export emoji %s", emoji.name)

        member_roles = {
            str(member.id): [
                role.id for role in member.roles
                if not role.is_default() and not role.managed
            ]
            for member in guild.members
            if any(not role.is_default() and not role.managed for role in member.roles)
        }

        backup_data = {
            "format_version": BACKUP_FORMAT_VERSION,
            "backup_id": backup_id,
            "created_by_user_id": ctx.author.id,
            "created_by_tag": str(ctx.author),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_guild_id": guild.id,
            "guild": {
                "id": guild.id,
                "name": guild.name,
                "description": guild.description,
                "verification_level": guild.verification_level.value,
                "default_notifications": guild.default_notifications.value,
                "explicit_content_filter": guild.explicit_content_filter.value,
                "afk_timeout": guild.afk_timeout,
                "system_channel_id": guild.system_channel.id if guild.system_channel else None,
                "rules_channel_id": guild.rules_channel.id if guild.rules_channel else None,
                "public_updates_channel_id": guild.public_updates_channel.id if guild.public_updates_channel else None,
                "afk_channel_id": guild.afk_channel.id if guild.afk_channel else None,
            },
            "roles": roles,
            "channels": channels,
            "emojis": emojis,
            "member_roles": member_roles,
            "limitations": [
                "Discord message history, integrations, managed roles, boosts, vanity URLs, and invite links are not restorable.",
                "Member role assignments can only be restored for users already in the destination server.",
                "Some Discord-managed settings may require manual setup.",
            ],
        }

        payload = json.dumps(backup_data, indent=2, ensure_ascii=False).encode("utf-8")
        if len(payload) > MAX_BACKUP_BYTES:
            return await ctx.send(
                "This backup is too large to DM as one Discord attachment. "
                "Try again after reducing the number/size of custom emojis."
            )

        try:
            await ctx.author.send(
                content=(
                    f"**ONYX backup created: {discord.utils.escape_markdown(guild.name)}**\n"
                    f"**Your unique Backup ID:**\n`{backup_id}`\n\n"
                    f"Saved {len(roles)} roles, {len(channels)} channels, and {len(emojis)} emojis.\n\n"
                    "**Keep this ID and the attached JSON file together.** "
                    "The ID is embedded in this exact backup file and is checked during restoration. "
                    "Only the Discord user who created this backup can use its ID to restore it.\n\n"
                    "**To restore:** Create a new server, invite ONYX with Administrator permission, "
                    "then upload this JSON file in the new server and run:\n"
                    f"`,backup restore {backup_id}`\n\n"
                    "ONYX will verify the ID and creator before rebuilding the server. "
                    "It will create missing content and will not delete existing channels or roles."
                ),
                file=discord.File(
                    fp=__import__("io").BytesIO(payload),
                    filename=f"onyx_backup_{backup_id}.json",
                ),
            )
        except discord.Forbidden:
            return await ctx.send(
                "I couldn't DM you. Enable DMs from server members, then run `,backup create` again."
            )
        except discord.HTTPException:
            log.exception("Backup DM delivery failed")
            return await ctx.send("The backup was prepared, but Discord could not deliver the DM.")

        await ctx.send("Backup complete! I've sent your unique Backup ID and JSON file by DM.")

    @backup.command(
        name="restore",
        help="Restore a backup by ID. Attach its matching ONYX JSON file."
    )
    async def backup_restore(self, ctx, backup_id: str):
        if not backup_id or len(backup_id) != 32:
            return await ctx.send("That Backup ID doesn't look valid. Use the 32-character ID from your ONYX DM.")

        if not ctx.message.attachments:
            return await ctx.send(
                "Attach the matching `onyx_backup_<ID>.json` file to your message:\n"
                f"`,backup restore {backup_id}`"
            )

        attachment = ctx.message.attachments[0]
        if not attachment.filename.lower().endswith(".json"):
            return await ctx.send("Please attach the ONYX backup `.json` file.")
        if attachment.size > MAX_BACKUP_BYTES:
            return await ctx.send("That backup file is too large for this restore command.")

        try:
            raw = await attachment.read()
            data = json.loads(raw.decode("utf-8"))
        except (discord.HTTPException, UnicodeDecodeError, json.JSONDecodeError):
            return await ctx.send("I couldn't read that backup file. Please attach the original ONYX JSON file.")

        # Bind the DM-issued ID to the exact backup document and its creator.
        if data.get("backup_id") != backup_id:
            return await ctx.send("**Backup ID mismatch.** That ID does not belong to the attached backup file.")
        if int(data.get("created_by_user_id", 0)) != ctx.author.id:
            return await ctx.send("You didn't create this backup, so you aren't authorized to restore it.")
        if data.get("format_version") not in (1, BACKUP_FORMAT_VERSION):
            return await ctx.send("This backup format isn't supported by this version of ONYX.")
        if not isinstance(data.get("roles"), list) or not isinstance(data.get("channels"), list):
            return await ctx.send("The backup file is missing required server data.")

        confirm = await ctx.send(
            f"**Restore verified.** Backup `{backup_id}` belongs to you.\n"
            f"This will create up to {len(data['roles'])} roles, "
            f"{len(data['channels'])} channels, and {len(data.get('emojis', []))} emojis "
            "in this server. Existing content will not be deleted.\n"
            "Reply `confirm` within 30 seconds to continue."
        )

        def check(message):
            return (
                message.author.id == ctx.author.id
                and message.channel.id == ctx.channel.id
                and message.content.casefold().strip() == "confirm"
            )

        try:
            await self.bot.wait_for("message", timeout=30.0, check=check)
        except TimeoutError:
            return await ctx.send("Restore cancelled because confirmation timed out.")

        await ctx.send("Starting restore. This can take a while on larger servers.")
        try:
            result = await self.restore_into_guild(ctx.guild, data)
        except Exception:
            log.exception("Unexpected restore failure for backup %s", backup_id)
            return await ctx.send(
                "The restore stopped because of an unexpected error. "
                "Check the Render logs for the traceback; items already created will remain."
            )

        await ctx.send(
            f"**Restore finished for backup `{backup_id}`.**\n"
            f"Created: {result['roles']} roles, {result['channels']} channels, "
            f"{result['emojis']} emojis.\n"
            f"Skipped/failed: {result['skipped']} items.\n"
            "Review channel order, member role assignments, and server settings manually."
        )

    async def restore_into_guild(self, guild, data):
        result = {"roles": 0, "channels": 0, "emojis": 0, "skipped": 0}
        role_map = {}

        # Reuse matching names; create missing roles.
        for item in sorted(data["roles"], key=lambda x: x.get("position", 0)):
            role = discord.utils.get(guild.roles, name=item["name"])
            if role is None:
                try:
                    role = await guild.create_role(
                        name=item["name"],
                        permissions=discord.Permissions(int(item["permissions"])),
                        colour=discord.Colour(int(item.get("colour", 0))),
                        hoist=bool(item.get("hoist", False)),
                        mentionable=bool(item.get("mentionable", False)),
                        reason="ONYX backup restore",
                    )
                    result["roles"] += 1
                except discord.HTTPException:
                    log.exception("Could not create role %s", item.get("name"))
                    result["skipped"] += 1
                    continue
            role_map[int(item["id"])] = role

        async def make_overwrites(item):
            overwrites = {}
            for entry in item.get("overwrites", []):
                if entry["kind"] == "role":
                    target = role_map.get(int(entry["id"]))
                else:
                    target = guild.get_member(int(entry["id"]))
                if target is not None:
                    overwrites[target] = discord.PermissionOverwrite.from_pair(
                        discord.Permissions(int(entry["allow"])),
                        discord.Permissions(int(entry["deny"])),
                    )
            return overwrites

        channel_map = {}
        saved_channels = data["channels"]

        # Categories first so child channels can be placed under them.
        for item in [x for x in saved_channels if x.get("type") == "category"]:
            category = discord.utils.get(guild.categories, name=item["name"])
            if category is None:
                try:
                    category = await guild.create_category(
                        item["name"],
                        overwrites=await make_overwrites(item),
                        reason="ONYX backup restore",
                    )
                    result["channels"] += 1
                except discord.HTTPException:
                    log.exception("Could not create category %s", item["name"])
                    result["skipped"] += 1
                    continue
            channel_map[int(item["id"])] = category

        for item in [x for x in saved_channels if x.get("type") != "category"]:
            category = channel_map.get(item.get("category_id"))
            existing = discord.utils.get(guild.channels, name=item["name"], category=category)
            if existing is not None:
                channel_map[int(item["id"])] = existing
                continue

            common = {
                "category": category,
                "overwrites": await make_overwrites(item),
                "reason": "ONYX backup restore",
            }
            try:
                kind = item.get("type")
                if kind == "text":
                    channel = await guild.create_text_channel(
                        item["name"],
                        topic=item.get("topic"),
                        nsfw=item.get("nsfw", False),
                        slowmode_delay=item.get("slowmode_delay", 0),
                        **common,
                    )
                elif kind == "voice":
                    channel = await guild.create_voice_channel(
                        item["name"],
                        bitrate=item.get("bitrate"),
                        user_limit=item.get("user_limit", 0),
                        **common,
                    )
                elif kind == "stage_voice":
                    channel = await guild.create_stage_channel(
                        item["name"],
                        bitrate=item.get("bitrate"),
                        user_limit=item.get("user_limit", 0),
                        **common,
                    )
                elif kind == "forum" and hasattr(guild, "create_forum"):
                    channel = await guild.create_forum(
                        item["name"],
                        topic=item.get("topic"),
                        nsfw=item.get("nsfw", False),
                        slowmode_delay=item.get("slowmode_delay", 0),
                        **common,
                    )
                elif kind == "news":
                    channel = await guild.create_text_channel(
                        item["name"], news=True, **common
                    )
                else:
                    result["skipped"] += 1
                    continue
                channel_map[int(item["id"])] = channel
                result["channels"] += 1
            except (discord.HTTPException, TypeError):
                log.exception("Could not create channel %s", item.get("name"))
                result["skipped"] += 1

        # Apply saved guild settings where the API permits it.
        guild_data = data.get("guild", {})
        try:
            edit_values = {
                "verification_level": discord.VerificationLevel(
                    int(guild_data.get("verification_level", 0))
                ),
                "default_notifications": discord.NotificationLevel(
                    int(guild_data.get("default_notifications", 0))
                ),
                "explicit_content_filter": discord.ContentFilter(
                    int(guild_data.get("explicit_content_filter", 0))
                ),
                "afk_timeout": int(guild_data.get("afk_timeout", 300)),
            }
            for field in (
                "system_channel_id", "rules_channel_id",
                "public_updates_channel_id", "afk_channel_id"
            ):
                old_id = guild_data.get(field)
                new_channel = channel_map.get(int(old_id)) if old_id else None
                target_field = field.replace("_id", "")
                edit_values[target_field] = new_channel
            await guild.edit(reason="ONYX backup restore", **edit_values)
        except (discord.HTTPException, TypeError, ValueError):
            log.exception("Some server-level settings could not be restored")
            result["skipped"] += 1

        # Restore custom emoji assets.
        for item in data.get("emojis", []):
            if discord.utils.get(guild.emojis, name=item["name"]):
                continue
            try:
                image_bytes = base64.b64decode(item["image"], validate=True)
                await guild.create_custom_emoji(
                    name=item["name"],
                    image=image_bytes,
                    reason="ONYX backup restore",
                )
                result["emojis"] += 1
            except (discord.HTTPException, ValueError, KeyError):
                log.exception("Could not restore emoji %s", item.get("name"))
                result["skipped"] += 1

        # Restore roles for members who already exist in the destination server.
        for user_id, old_role_ids in data.get("member_roles", {}).items():
            member = guild.get_member(int(user_id))
            if member is None:
                continue
            add_roles = [
                role_map[int(old_role_id)]
                for old_role_id in old_role_ids
                if int(old_role_id) in role_map
                and role_map[int(old_role_id)] not in member.roles
            ]
            if add_roles:
                try:
                    await member.add_roles(*add_roles, reason="ONYX backup restore")
                except discord.HTTPException:
                    log.exception("Could not restore member roles for %s", user_id)
                    result["skipped"] += 1

        return result


async def setup(bot):
    await bot.add_cog(ServerBackup(bot))
