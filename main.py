# -*- coding: utf-8 -*-
"""
Manual / Executable entry point for script.twilight0.installer.
Allows the user to launch the installer from Kodi Programs to either:
1. Re-run standard bootstrap (Install Repo + Dev Toolbox)
2. Open interactive addon browser/installer to install other addons from Twilight0 repo.
"""
import xbmcgui

from installer import run_default_bootstrap, install_devtoolbox_setup, show_interactive_installer_menu


def main():
    dialog = xbmcgui.Dialog()
    options = [
        "Install Twilight0 Repositories & AliveGR (Default Setup)",
        "Install Twilight0 Repositories & Dev ToolBox",
        "Browse & Install Other Twilight0 Addons..."
    ]
    sel = dialog.select("Scripted Addon Installer", options)
    if sel == 0:
        run_default_bootstrap(interactive=True)
    elif sel == 1:
        install_devtoolbox_setup()
    elif sel == 2:
        show_interactive_installer_menu()


if __name__ == "__main__":
    main()
