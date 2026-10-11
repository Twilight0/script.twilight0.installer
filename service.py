# -*- coding: utf-8 -*-
"""
Autorun service entry point for script.twilight0.installer.
Triggers automatically on addon installation / startup.
Checks if bootstrap has completed; if not, performs automated bootstrap and marks done.
"""
import os
import xbmc
import xbmcaddon
import xbmcvfs

from main import main as show_main_menu


def run_service():
    addon = xbmcaddon.Addon("script.twilight0.installer")
    addon_data_dir = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    marker_file = os.path.join(addon_data_dir, ".installed_marker")

    if not os.path.isdir(addon_data_dir):
        os.makedirs(addon_data_dir, exist_ok=True)

    # Only show initial install prompt once upon installation
    if os.path.isfile(marker_file):
        xbmc.log("[Twilight0Installer] Initial setup prompt was already presented previously. Service idle.", xbmc.LOGINFO)
        return

    xbmc.log("[Twilight0Installer] Fresh install detected. Presenting setup selection dialog to user...", xbmc.LOGINFO)

    # Mark as presented so it doesn't pop up again on future Kodi startups
    try:
        with open(marker_file, "w") as f:
            f.write("prompted\n")
    except Exception:
        pass

    # Wait a brief moment for Kodi's GUI to stabilize post-zip install
    xbmc.sleep(1000)

    # Show the choice dialog to the user
    show_main_menu()


if __name__ == "__main__":
    run_service()
