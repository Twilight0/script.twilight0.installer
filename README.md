# Scripted Addon Installer (`script.twilight0.installer`)

A standalone bootstrap and on-demand installer for Twilight0 Kodi addons and repositories.

## Features
- **1-Action Single Zip Install:** The user installs this `.zip` from Kodi's "Install from zip file".
- **Immediate Autorun via Service Extension:** Automatically launches upon installation to download, unpack, and activate the core environment.
- **Automated Default Bootstrap:**
  1. Installs `repository.twilight0` (main repository).
  2. Installs `repository.twilight0.libs` (libraries repository).
  3. Resolves and installs all required dependencies (including `ResolveURL`, `Tulip`, artwork, and mirrors).
  4. Installs and enables `plugin.video.alivegr`.
  5. Refreshes the local addon database (`UpdateLocalAddons`) and activates each addon via JSON-RPC.
- **Persistent Program Menu:**
  - **Option 1:** Install Twilight0 Repositories & AliveGR (Default Setup)
  - **Option 2:** Install Twilight0 Repositories & Dev ToolBox
  - **Option 3:** Browse & Install Other Twilight0 Addons... (interactive catalog browser)

## Files
- `addon.xml`: Declares service and executable script extension points.
- `service.py`: Autorun service triggered on installation / startup.
- `main.py`: Interactive manual menu in Programs.
- `installer.py`: Network manifest parser, dependency tree walker, and zip extractor.
