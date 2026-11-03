import base64
import json
import logging
import uuid
from datetime import datetime, timezone

import discord
from discord.ext import commands

log = logging.getLogger("bot.backup")


def pack_overwrites(channel):
    packed = []
    for target, overwrite in channel.overwrites.items():
        kind = "role" if isinstance(target, discord.Role) else "member"
        allow, deny = overwrite.pair()
        packed.append({
            "kind": kind, "id": target.id,
            "allow": allow.value, "deny": deny.value
        })
    return packed


class ServerBackup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS onyx_server_backups (
                backup_id TEXT PRIMARY KEY,
                owner_id BIGINT NOT NULL,
                source_guild_id BIGINT NOT NULL,
                created_at TEXT NOT NULL,
                data TEXT NOT NULL
            )
        """)

    @commands.group(
        name="backup", invoke_without_command=True,
        help="Create or restore a server backup using its unique ID."
    )
    @commands.guild_only()
    @commands.has_guild_permissions(administrator=True)
    async def backup(self, ctx):
        await self.create_backup(ctx)

    @backup.command(name="create", help="Save a server backup and DM its unique ID.")
    async def backup_create(self, ctx):
        await self.create_backup(ctx)

    async def create_backup(self, ctx):
        guild = ctx.guild
        backup_id = uuid.uuid4().hex
        await ctx.send("Creating your backup and saving it in ONYX's database...")

        roles = [{
            "id": r.id, "name": r.name, "permissions": r.permissions.value,
            "colour": r.colour.value, "hoist": r.hoist,
            "mentionable": r.mentionable, "position": r.position
        } for r in sorted(guild.roles, key=lambda x: x.position)
          if not r.is_default() and not r.managed]

        channels = []
        for ch in sorted(guild.channels, key=lambda x: (x.position, x.id)):
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
                image = await emoji.url.read()
                emojis.append({
                    "id": emoji.id, "name": emoji.name,
                    "image": base64.b64encode(image).decode("ascii")
                })
            except Exception:
                log.exception("Could not export emoji %s", emoji.name)

        member_roles = {
            str(m.id): [r.id for r in m.roles if not r.is_default() and not r.managed]
            for m in guild.members
            if any(not r.is_default() and not r.managed for r in m.roles)
        }

        backup_data = {
            "format_version": 3,
            "backup_id": backup_id,
            "created_by_user_id": ctx.author.id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_guild_id": guild.id,
            "guild": {
                "id": guild.id, "name": guild.name,
                "description": guild.description,
                "verification_level": guild.verification_level.value,
                "default_notifications": guild.default_notifications.value,
                "explicit_content_filter": guild.explicit_content_filter.value,
                "afk_timeout": guild.afk_timeout,
                "system_channel_id": guild.system_channel.id if guild.system_channel else None,
                "rules_channel_id": guild.rules_channel.id if guild.rules_channel else None,
                "public_updates_channel_id": guild.public_updates_channel.id if guild.public_updates_channel else None,
                "afk_channel_id": guild.afk_channel.id if guild.afk_channel else None
            },
            "roles": roles, "channels": channels,
            "emojis": emojis, "member_roles": member_roles
        }

        try:
            await self.bot.db.execute(
                """INSERT INTO onyx_server_backups
                   (backup_id, owner_id, source_guild_id, created_at, data)
                   VALUES (?, ?, ?, ?, ?)""",
                (backup_id, ctx.author.id, guild.id,
                 backup_data["created_at"],
                 json.dumps(backup_data, ensure_ascii=False, separators=(",", ":")))
            )
        except Exception:
            log.exception("Could not store backup %s", backup_id)
            return await ctx.send("I couldn't save the backup to ONYX's database. Check the Render logs.")

        try:
            await ctx.author.send(
                f"ONYX backup saved for **{discord.utils.escape_markdown(guild.name)}**.\n"
                f"Your unique Backup ID (tap the code block to copy):\n```\n{backup_id}\n```\n"
                f"Saved {len(roles)} roles, {len(channels)} channels, and {len(emojis)} emojis.\n\n"
                "No JSON file is needed. Your backup is stored in ONYX's database.\n"
                "Create your new server, invite ONYX with Administrator permission, then run:\n"
                f",backup restore {backup_id}"
            )
        except discord.Forbidden:
            return await ctx.send(
                f"Backup saved, but I couldn't DM you. Your Backup ID is {backup_id}. "
                "Enable DMs from server members."
            )
        except discord.HTTPException:
            log.exception("Could not DM backup ID")
            return await ctx.send(f"Backup saved, but DM delivery failed. Your Backup ID is {backup_id}.")

        await ctx.send("Backup saved successfully! Check your DMs for the Backup ID.")

    @backup.command(name="restore", help="Restore a saved backup using its ID; no file upload needed.")
    async def backup_restore(self, ctx, backup_id: str):
        backup_id = backup_id.lower().strip()
        if len(backup_id) != 32 or any(c not in "0123456789abcdef" for c in backup_id):
            return await ctx.send("That Backup ID is invalid. Use the 32-character ID ONYX sent you.")

        row = await self.bot.db.fetchone(
            "SELECT owner_id, data FROM onyx_server_backups WHERE backup_id=?",
            (backup_id,)
        )
        if row is None:
            return await ctx.send("I couldn't find that Backup ID in ONYX's database.")
        if int(row["owner_id"]) != ctx.author.id:
            return await ctx.send("That backup belongs to a different Discord account.")

        try:
            data = json.loads(row["data"])
        except (TypeError, json.JSONDecodeError):
            log.exception("Backup %s has invalid stored data", backup_id)
            return await ctx.send("That saved backup is damaged and can't be restored.")

        if data.get("backup_id") != backup_id or data.get("created_by_user_id") != ctx.author.id:
            return await ctx.send("The backup ID or owner verification failed.")
        if data.get("format_version") != 3:
            return await ctx.send("This backup format isn't supported by this version of ONYX.")

        await ctx.send(
            f"Verified backup {backup_id}. **DESTRUCTIVE REBUILD:** ONYX will delete "
            "every existing channel and category in this server, then recreate the saved layout. "
            "Roles will not be deleted. Reply `confirm` within 30 seconds to continue."
        )

        def check(message):
            return (
                message.author.id == ctx.author.id
                and message.channel.id == ctx.channel.id
                and message.content.casefold().strip() == "confirm"
            )

        try:
            await self.bot.wait_for("message", timeout=30, check=check)
        except TimeoutError:
            return await ctx.send("Restore cancelled; confirmation timed out.")

        await ctx.send("Confirmation received. Starting the full channel rebuild...")
        result = await self.restore_into_guild(ctx.guild, data)

        skipped = result["skipped_items"]
        report = (
            f"**ONYX restore finished** for backup `{backup_id}`.\\n"
            f"Created: {result['roles']} roles, {result['channels']} channels, "
            f"{result['emojis']} emojis.\\n"
            f"Deleted old channels/categories: {result['deleted_channels']}.\\n"
            f"Skipped: {len(skipped)} items."
        )
        if skipped:
            report += "\\n\\n**Skipped items:**\\n" + "\\n".join(
                f"• {item}" for item in skipped[:35]
            )
            if len(skipped) > 35:
                report += f"\\n• ...and {len(skipped) - 35} more; see Render logs."
        else:
            report += "\\n\\nNo items were skipped."

        try:
            await ctx.author.send(report)
        except discord.HTTPException:
            log.exception("Could not DM restore report")
            log.warning("Restore report for %s: %s", backup_id, report)

    async def restore_into_guild(self, guild, data):
        result = {
            "roles": 0, "channels": 0, "emojis": 0,
            "deleted_channels": 0, "skipped_items": []
        }
        role_map = {}

        # Delete all existing channels first; child channels before categories.
        old_channels = list(guild.channels)
        old_channels.sort(key=lambda channel: isinstance(channel, discord.CategoryChannel))
        for old_channel in old_channels:
            try:
                await old_channel.delete(reason="ONYX backup restore: clean rebuild")
                result["deleted_channels"] += 1
            except discord.HTTPException as exc:
                log.exception("Could not delete old channel %s", old_channel.id)
                result["skipped_items"].append(
                    f"Could not delete #{old_channel.name} ({old_channel.id}): {exc}"
                )

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
                        reason="ONYX backup restore"
                    )
                    result["roles"] += 1
                except discord.HTTPException:
                    log.exception("Could not create role %s", item["name"])
                    result["skipped_items"].append(f"Role '{item['name']}': creation failed; see Render logs.")
                    continue
            role_map[int(item["id"])] = role

        async def get_overwrites(item):
            overwrites = {}
            for entry in item.get("overwrites", []):
                target = (
                    role_map.get(int(entry["id"])) if entry["kind"] == "role"
                    else guild.get_member(int(entry["id"]))
                )
                if target is not None:
                    overwrites[target] = discord.PermissionOverwrite.from_pair(
                        discord.Permissions(int(entry["allow"])),
                        discord.Permissions(int(entry["deny"]))
                    )
            return overwrites

        channel_map = {}
        saved = data["channels"]

        for item in [x for x in saved if x["type"] == "category"]:
            category = discord.utils.get(guild.categories, name=item["name"])
            if category is None:
                try:
                    category = await guild.create_category(
                        item["name"], overwrites=await get_overwrites(item),
                        reason="ONYX backup restore"
                    )
                    result["channels"] += 1
                except discord.HTTPException:
                    log.exception("Could not create category %s", item["name"])
                    result["skipped_items"].append(f"Category '{item['name']}': creation failed; see Render logs.")
                    continue
            channel_map[int(item["id"])] = category

        for item in [x for x in saved if x["type"] != "category"]:
            category = channel_map.get(item.get("category_id"))
            existing = discord.utils.get(guild.channels, name=item["name"], category=category)
            if existing is not None:
                channel_map[int(item["id"])] = existing
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
                elif kind == "news":
                    channel = await guild.create_text_channel(
                        item["name"], news=True, **common
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
                elif kind == "forum" and hasattr(guild, "create_forum"):
                    channel = await guild.create_forum(
                        item["name"], topic=item.get("topic"),
                        nsfw=item.get("nsfw", False),
                        slowmode_delay=item.get("slowmode_delay", 0), **common
                    )
                else:
                    result["skipped_items"].append(f"Channel '{item['name']}' (type {item['type']}): unsupported.")
                    continue
                channel_map[int(item["id"])] = channel
                result["channels"] += 1
            except (discord.HTTPException, TypeError):
                log.exception("Could not create channel %s", item["name"])
                result["skipped_items"].append(f"Channel '{item['name']}': creation failed; see Render logs.")

        # Reapply original order after all channels exist, separately for each category.
        position_groups = {}
        for item in saved:
            restored = channel_map.get(int(item["id"]))
            if restored is not None:
                parent = item.get("category_id") or 0
                position_groups.setdefault(parent, []).append(
                    (int(item.get("position", 0)), restored)
                )

        for group in position_groups.values():
            for position, (_, channel) in enumerate(sorted(group, key=lambda pair: pair[0])):
                try:
                    await channel.edit(
                        position=position,
                        reason="ONYX backup restore: preserve original channel order"
                    )
                except discord.HTTPException:
                    log.exception("Could not set channel position for %s", channel.id)
                    result["skipped_items"].append(f"Channel '{channel.name}': original position could not be applied.")

        # Restore saved server-level settings where Discord permits it.
        gd = data.get("guild", {})
        try:
            edit = {
                "verification_level": discord.VerificationLevel(int(gd.get("verification_level", 0))),
                "default_notifications": discord.NotificationLevel(int(gd.get("default_notifications", 0))),
                "explicit_content_filter": discord.ContentFilter(int(gd.get("explicit_content_filter", 0))),
                "afk_timeout": int(gd.get("afk_timeout", 300))
            }
            for field in ("system_channel_id", "rules_channel_id", "public_updates_channel_id", "afk_channel_id"):
                old_id = gd.get(field)
                edit[field.replace("_id", "")] = channel_map.get(int(old_id)) if old_id else None
            await guild.edit(reason="ONYX backup restore", **edit)
        except (discord.HTTPException, TypeError, ValueError):
            log.exception("Some guild settings could not be restored")
            result["skipped_items"].append("Some server-level settings could not be restored; see Render logs.")

        for item in data.get("emojis", []):
            if discord.utils.get(guild.emojis, name=item["name"]):
                continue
            try:
                await guild.create_custom_emoji(
                    name=item["name"],
                    image=base64.b64decode(item["image"], validate=True),
                    reason="ONYX backup restore"
                )
                result["emojis"] += 1
            except (discord.HTTPException, ValueError, KeyError):
                log.exception("Could not restore emoji %s", item.get("name"))
                result["skipped_items"].append(f"Emoji '{item.get('name', 'unknown')}': creation failed; see Render logs.")

        for user_id, old_role_ids in data.get("member_roles", {}).items():
            member = guild.get_member(int(user_id))
            if member is None:
                continue
            add_roles = [
                role_map[int(rid)] for rid in old_role_ids
                if int(rid) in role_map and role_map[int(rid)] not in member.roles
            ]
            if add_roles:
                try:
                    await member.add_roles(*add_roles, reason="ONYX backup restore")
                except discord.HTTPException:
                    log.exception("Could not restore member roles for %s", user_id)
                    result["skipped_items"].append(f"Member {user_id}: one or more roles could not be assigned.")

        return result


async def setup(bot):
    await bot.add_cog(ServerBackup(bot))
