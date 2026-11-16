
"""
ONYX Prestige Shop — retired Discord interface.

The ONYX shop, inventory, cosmetic previews, and equipment management
are now handled through the ONYX website.

This module is intentionally retained so existing extension discovery
does not break. It does not register Discord commands, create or modify
database tables, or delete existing cosmetic data.
"""


async def setup(bot):
    # Discord-side shop functionality has moved to the ONYX website.
    # Existing database records remain untouched.
    return
