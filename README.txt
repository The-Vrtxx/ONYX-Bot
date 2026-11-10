ONYX replacement files

This package contains complete replacement files and package marker files only.
Extract the contents into the ROOT of your existing ONYX-Bot repository, keeping
the folder structure and allowing the files to overwrite matching files.

What this update changes:
- Loads every cog recursively from cogs/ and its category folders.
- Supports ,reload with full paths such as ,reload administration.shh and
  ,reload leveling.levels. ,reload by itself reloads all discovered cogs.
- Makes ,shh bot-owner-only.
- Fixes the Prestige emblem asset path for cogs/leveling/levels.py.
- Updates the jail setup error message to the new moderation folder.
- Adds Python package __init__.py files for all cog folders.
- Keeps Python cache files ignored by Git.

After replacing the files, commit/push the changes to the main branch and let
Render redeploy. This package does not include your environment variables,
database, or asset images; keep those as they are.

Validation: all Python source files in the supplied repository ZIP compiled
successfully. This is a syntax check, not a live Discord/Render test.
