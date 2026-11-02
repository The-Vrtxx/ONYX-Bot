"""Database layer for ONYX.

PostgreSQL is recommended for hosted multi-server deployments.
SQLite remains available for local development.
"""
import os
import asyncio
from pathlib import Path

import aiosqlite

POSTGRES_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS guild_settings (
 guild_id BIGINT PRIMARY KEY, prefix TEXT NOT NULL DEFAULT ',', log_channel_id BIGINT, welcome_channel_id BIGINT,
 welcome_message TEXT DEFAULT 'Welcome {mention} to **{server}**!',
 goodbye_message TEXT DEFAULT '{user} has left {server}.',
 automod_enabled INTEGER DEFAULT 0, block_invites INTEGER DEFAULT 0,
 block_links INTEGER DEFAULT 0, spam_limit INTEGER DEFAULT 5,
 spam_window INTEGER DEFAULT 7, levelup_channel_id BIGINT,
 xp_enabled INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS mod_cases (
 id BIGSERIAL PRIMARY KEY, guild_id BIGINT NOT NULL,
 user_id BIGINT NOT NULL, moderator_id BIGINT NOT NULL,
 action TEXT NOT NULL, reason TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS warn_settings (guild_id BIGINT PRIMARY KEY, threshold INTEGER DEFAULT 3, action TEXT DEFAULT 'timeout');
CREATE TABLE IF NOT EXISTS role_panels (guild_id BIGINT NOT NULL, channel_id BIGINT NOT NULL, message_id BIGINT NOT NULL, role_id BIGINT NOT NULL, PRIMARY KEY (guild_id, message_id, role_id));
CREATE TABLE IF NOT EXISTS embed_templates (guild_id BIGINT NOT NULL, name TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL, color TEXT DEFAULT '5865F2', PRIMARY KEY (guild_id, name));
CREATE TABLE IF NOT EXISTS shh_whitelist (guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL, PRIMARY KEY (guild_id, user_id));
CREATE TABLE IF NOT EXISTS shh_settings (guild_id BIGINT PRIMARY KEY, role_id BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS warnings (id BIGSERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL, moderator_id BIGINT NOT NULL, reason TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS levels (guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL, xp BIGINT DEFAULT 0, level INTEGER DEFAULT 0, PRIMARY KEY (guild_id, user_id));
CREATE TABLE IF NOT EXISTS level_rewards (guild_id BIGINT NOT NULL, level INTEGER NOT NULL, role_id BIGINT NOT NULL, PRIMARY KEY (guild_id, level));
CREATE TABLE IF NOT EXISTS self_roles (guild_id BIGINT NOT NULL, role_id BIGINT NOT NULL, PRIMARY KEY (guild_id, role_id));
CREATE TABLE IF NOT EXISTS custom_commands (guild_id BIGINT NOT NULL, name TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY (guild_id, name));
CREATE TABLE IF NOT EXISTS lastfm_users (user_id BIGINT PRIMARY KEY, username TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS automod_ignored (guild_id BIGINT NOT NULL, channel_id BIGINT NOT NULL, PRIMARY KEY (guild_id, channel_id));
CREATE TABLE IF NOT EXISTS onyx_autoresponses (guild_id BIGINT NOT NULL, trigger TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY (guild_id, trigger));
CREATE TABLE IF NOT EXISTS onyx_antiraid (guild_id BIGINT PRIMARY KEY, join_count INTEGER NOT NULL, window_seconds INTEGER NOT NULL, alert_channel_id BIGINT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS onyx_voicemaster (guild_id BIGINT PRIMARY KEY, trigger_channel_id BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS onyx_tickets (id BIGSERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, channel_id BIGINT NOT NULL UNIQUE, opener_id BIGINT NOT NULL, claimed_by BIGINT, status TEXT NOT NULL DEFAULT 'open', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, closed_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS onyx_ticket_panels (guild_id BIGINT PRIMARY KEY, channel_id BIGINT NOT NULL, message_id BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS onyx_mod_notes (id BIGSERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL, moderator_id BIGINT NOT NULL, note TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS onyx_security_settings (guild_id BIGINT PRIMARY KEY, alert_channel_id BIGINT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS onyx_temp_voice_rooms (guild_id BIGINT NOT NULL, channel_id BIGINT PRIMARY KEY, owner_id BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS onyx_antinuke_settings (
 guild_id BIGINT PRIMARY KEY, threshold INTEGER NOT NULL DEFAULT 3, window_seconds INTEGER NOT NULL DEFAULT 10,
 punishment TEXT NOT NULL DEFAULT 'none', log_channel_id BIGINT, jail_role_id BIGINT, enabled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS onyx_antinuke_whitelist (guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL, PRIMARY KEY (guild_id,user_id));
CREATE TABLE IF NOT EXISTS onyx_antinuke_staff_roles (guild_id BIGINT NOT NULL, role_id BIGINT NOT NULL, PRIMARY KEY (guild_id,role_id));
CREATE TABLE IF NOT EXISTS onyx_antinuke_events (
 id BIGSERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, actor_id BIGINT NOT NULL, action TEXT NOT NULL,
 detail TEXT NOT NULL, punishment TEXT NOT NULL DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS onyx_jail_settings (
 guild_id BIGINT PRIMARY KEY, role_id BIGINT NOT NULL, category_id BIGINT NOT NULL, channel_id BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS onyx_jails (
 guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL, saved_role_ids TEXT NOT NULL DEFAULT '[]',
 moderator_id BIGINT NOT NULL, reason TEXT NOT NULL, expires_at TIMESTAMP,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (guild_id,user_id)
);
"""

class ExecuteResult:
    def __init__(self, lastrowid=None):
        self.lastrowid = lastrowid

class Database:
    def __init__(self, path: str = "data/bot.sqlite3", database_url: str | None = None):
        self.path = path
        self.database_url = database_url or os.getenv("DATABASE_URL")
        self.conn = None
        self.backend = "postgres" if self.database_url else "sqlite"
        self._connection_lock = asyncio.Lock()

    async def connect(self):
        if self.backend == "postgres":
            import asyncpg
            url = self.database_url
            if url.startswith("postgres://"):
                url = "postgresql://" + url[len("postgres://"):]
            self.conn = await asyncpg.connect(url, command_timeout=60)
        else:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self.conn = await aiosqlite.connect(self.path)
            self.conn.row_factory = aiosqlite.Row
            await self.conn.execute("PRAGMA foreign_keys = ON")
            await self.conn.execute("PRAGMA journal_mode = WAL")

    async def initialize(self):
        if self.backend == "postgres":
            await self.conn.execute(POSTGRES_SCHEMA)
            await self.conn.execute("ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS prefix TEXT NOT NULL DEFAULT ','")
        else:
            old_schema = Path(__file__).with_name("database_v4_schema.sql")
            await self.conn.executescript(old_schema.read_text(encoding="utf-8"))
            columns = await (await self.conn.execute("PRAGMA table_info(guild_settings)")).fetchall()
            if not any(column["name"] == "prefix" for column in columns):
                await self.conn.execute("ALTER TABLE guild_settings ADD COLUMN prefix TEXT NOT NULL DEFAULT ','")
            await self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS onyx_autoresponses (guild_id INTEGER NOT NULL, trigger TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY (guild_id, trigger));
                CREATE TABLE IF NOT EXISTS onyx_antiraid (guild_id INTEGER PRIMARY KEY, join_count INTEGER NOT NULL, window_seconds INTEGER NOT NULL, alert_channel_id INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS onyx_voicemaster (guild_id INTEGER PRIMARY KEY, trigger_channel_id INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS onyx_tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL UNIQUE, opener_id BIGINT NOT NULL, claimed_by BIGINT, status TEXT NOT NULL DEFAULT 'open', created_at TEXT DEFAULT CURRENT_TIMESTAMP, closed_at TEXT);
                CREATE TABLE IF NOT EXISTS onyx_ticket_panels (guild_id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL, message_id INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS onyx_mod_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, moderator_id INTEGER NOT NULL, note TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS onyx_security_settings (guild_id INTEGER PRIMARY KEY, alert_channel_id INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS onyx_temp_voice_rooms (guild_id INTEGER NOT NULL, channel_id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS onyx_antinuke_settings (guild_id INTEGER PRIMARY KEY, threshold INTEGER NOT NULL DEFAULT 3, window_seconds INTEGER NOT NULL DEFAULT 10, punishment TEXT NOT NULL DEFAULT 'none', log_channel_id INTEGER, jail_role_id INTEGER, enabled INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS onyx_antinuke_whitelist (guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, PRIMARY KEY (guild_id,user_id));
                CREATE TABLE IF NOT EXISTS onyx_antinuke_staff_roles (guild_id INTEGER NOT NULL, role_id INTEGER NOT NULL, PRIMARY KEY (guild_id,role_id));
                CREATE TABLE IF NOT EXISTS onyx_antinuke_events (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, actor_id INTEGER NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, punishment TEXT NOT NULL DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS onyx_jail_settings (guild_id INTEGER PRIMARY KEY, role_id INTEGER NOT NULL, category_id INTEGER NOT NULL, channel_id INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS onyx_jails (guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, saved_role_ids TEXT NOT NULL DEFAULT '[]', moderator_id INTEGER NOT NULL, reason TEXT NOT NULL, expires_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (guild_id,user_id));
            """)
            await self.conn.commit()

    @staticmethod
    def _postgres_query(query: str) -> str:
        index = 0
        out = []
        for char in query:
            if char == "?":
                index += 1
                out.append(f"${index}")
            else:
                out.append(char)
        return "".join(out)

    async def execute(self, query, params=()):
        if self.backend == "postgres":
            q = self._postgres_query(query)
            async with self._connection_lock:
                if query.lstrip().upper().startswith("INSERT INTO MOD_CASES"):
                    q = q.rstrip().rstrip(";") + " RETURNING id"
                    new_id = await self.conn.fetchval(q, *params)
                    return ExecuteResult(lastrowid=new_id)
                if query.lstrip().upper().startswith("INSERT INTO ONYX_ANTINUKE_EVENTS"):
                    q = q.rstrip().rstrip(";") + " RETURNING id"
                    new_id = await self.conn.fetchval(q, *params)
                    return ExecuteResult(lastrowid=new_id)
                await self.conn.execute(q, *params)
            return ExecuteResult()
        cursor = await self.conn.execute(query, params)
        await self.conn.commit()
        return cursor

    async def fetchone(self, query, params=()):
        if self.backend == "postgres":
            async with self._connection_lock:
                return await self.conn.fetchrow(self._postgres_query(query), *params)
        cursor = await self.conn.execute(query, params)
        return await cursor.fetchone()

    async def fetchall(self, query, params=()):
        if self.backend == "postgres":
            async with self._connection_lock:
                return await self.conn.fetch(self._postgres_query(query), *params)
        cursor = await self.conn.execute(query, params)
        return await cursor.fetchall()

    async def close(self):
        if self.conn:
            if self.backend == "postgres":
                async with self._connection_lock:
                    await self.conn.close()
            else:
                await self.conn.close()
