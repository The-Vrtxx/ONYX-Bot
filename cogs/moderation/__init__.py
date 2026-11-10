"""ONYX moderation package.

Step 1 intentionally creates only the package boundary. Existing top-level
moderation extensions remain active until their commands and dependencies are
migrated in later steps.

The bot currently loads only cogs/*.py, so this package is not loaded as an
extension yet. When migration is complete, cogs.moderation will become the
single extension entry point and its setup(bot) function will register the
moderation cogs/services without duplicate command registration.
"""

__all__ = (
    "moderation",
    "mute_system",
    "jail_system",
    "moderation_history",
    "permissions",
)
