# ONYX Moderation Package

This is the new package boundary for the moderation-system refactor.

## Migration safety

Step 1 is structure-only. The existing extensions remain in their current
locations and continue to load unchanged:

- `cogs/moderation.py`
- `cogs/moderation_plus.py`
- `cogs/jail.py`
- `cogs/permission_refresh.py`

The current `main.py` loader scans only `cogs/*.py`; it does not recursively
load this package. Do not change the loader or delete the original files until
all commands, cog lookups, database initialization, and background tasks have
been migrated and tested.

## Planned modules

- `moderation.py` — member and channel moderation commands
- `mute_system.py` — mute-role setup and mute services
- `jail_system.py` — jail records, role restoration, and expiration worker
- `moderation_history.py` — warnings, cases, staff notes, and history
- `permissions.py` — moderation permission setup and repair

The package will become one extension entry point (`cogs.moderation`) once the
migration is complete. Internal modules should not each define an extension
`setup(bot)` function; this avoids accidentally registering the same commands
multiple times.
