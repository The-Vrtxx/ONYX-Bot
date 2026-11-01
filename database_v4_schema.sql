CREATE TABLE IF NOT EXISTS guild_settings (
 guild_id INTEGER PRIMARY KEY, prefix TEXT NOT NULL DEFAULT ',', log_channel_id INTEGER, welcome_channel_id INTEGER,
 welcome_message TEXT DEFAULT 'Welcome {mention} to **{server}**!',
 goodbye_message TEXT DEFAULT '{user} has left {server}.',
 automod_enabled INTEGER DEFAULT 0, block_invites INTEGER DEFAULT 0,
 block_links INTEGER DEFAULT 0, spam_limit INTEGER DEFAULT 5,
 spam_window INTEGER DEFAULT 7, levelup_channel_id INTEGER,
 xp_enabled INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS mod_cases (
 id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,
 user_id INTEGER NOT NULL, moderator_id INTEGER NOT NULL,
 action TEXT NOT NULL, reason TEXT NOT NULL,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS warn_settings (
 guild_id INTEGER PRIMARY KEY, threshold INTEGER DEFAULT 3,
 action TEXT DEFAULT 'timeout'
);
CREATE TABLE IF NOT EXISTS role_panels (
 guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
 message_id INTEGER NOT NULL, role_id INTEGER NOT NULL,
 PRIMARY KEY (guild_id, message_id, role_id)
);
CREATE TABLE IF NOT EXISTS embed_templates (
 guild_id INTEGER NOT NULL, name TEXT NOT NULL,
 title TEXT NOT NULL, description TEXT NOT NULL,
 color TEXT DEFAULT '5865F2',
 PRIMARY KEY (guild_id, name)
);
CREATE TABLE IF NOT EXISTS shh_whitelist (
 guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
 PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS shh_settings (
 guild_id INTEGER PRIMARY KEY, role_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS warnings (
 id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,
 user_id INTEGER NOT NULL, moderator_id INTEGER NOT NULL,
 reason TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS levels (
 guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
 xp INTEGER DEFAULT 0, level INTEGER DEFAULT 0,
 PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS level_rewards (
 guild_id INTEGER NOT NULL, level INTEGER NOT NULL, role_id INTEGER NOT NULL,
 PRIMARY KEY (guild_id, level)
);
CREATE TABLE IF NOT EXISTS self_roles (
 guild_id INTEGER NOT NULL, role_id INTEGER NOT NULL,
 PRIMARY KEY (guild_id, role_id)
);
CREATE TABLE IF NOT EXISTS custom_commands (
 guild_id INTEGER NOT NULL, name TEXT NOT NULL, response TEXT NOT NULL,
 PRIMARY KEY (guild_id, name)
);
CREATE TABLE IF NOT EXISTS lastfm_users (
 user_id INTEGER PRIMARY KEY, username TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS automod_ignored (
 guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
 PRIMARY KEY (guild_id, channel_id)
);
