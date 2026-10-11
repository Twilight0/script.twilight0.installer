# -*- coding: utf-8 -*-
"""
Installer Engine for Twilight0 Addons & Repositories
Fetches remote manifests, resolves dependencies, downloads zip archives,
extracts to special://home/addons, updates local addon registry, and enables addons.
"""
import gzip
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

import xbmc
import xbmcgui
import xbmcvfs

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Kodi/Twilight0-Installer"

REPO_TWILIGHT0_BASE = "https://raw.githubusercontent.com/Twilight0/repository.twilight0/master/repo_dir/"
REPO_TWILIGHT0_XML_GZ = REPO_TWILIGHT0_BASE + "addons.xml.gz"

REPO_LIBS_BASE = "https://raw.githubusercontent.com/Twilight0/repository.twilight0.libs/master/repo_dir/"
REPO_LIBS_XML_GZ = REPO_LIBS_BASE + "addons.xml.gz"

REPO_SMRZIPS_BASE = "https://raw.githubusercontent.com/Gujal00/smrzips/master/zips/"
REPO_SMRZIPS_XML = "https://raw.githubusercontent.com/Gujal00/smrzips/master/addons.xml"

KODI_MIRRORS_BASE = "https://mirrors.kodi.tv/addons/"

KODI_CODENAMES = {
    19: "matrix",
    20: "nexus",
    21: "omega",
    22: "piers",
}


def execute_jsonrpc(method, params=None):
    """Execute Kodi JSONRPC command safely."""
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "id": 1
    }
    if params:
        payload["params"] = params
    try:
        raw = xbmc.executeJSONRPC(json.dumps(payload))
        return json.loads(raw).get("result", {})
    except Exception as e:
        xbmc.log(f"[Twilight0Installer] JSONRPC Error: {e}", xbmc.LOGERROR)
        return {}


def is_addon_installed(addon_id):
    """Check if an addon exists in the addons directory."""
    addons_dir = xbmcvfs.translatePath("special://home/addons/")
    path = os.path.join(addons_dir, addon_id)
    return os.path.isdir(path)


def activate_and_reload_addon(addon_id):
    """
    Triggers Kodi's CAddonMgr::EnableAddon event to force CLangInfo to load
    newly extracted strings.po translation tables into active memory.
    Cycles false -> true with proper async delays and verification.
    """
    # 1. Update local registry so Kodi's background worker discovers and indexes the folder
    xbmc.executebuiltin("UpdateLocalAddons")
    time.sleep(0.5)

    # 2. Disable first to ensure an event transition occurs
    execute_jsonrpc("Addons.SetAddonEnabled", {"addonid": addon_id, "enabled": False})
    time.sleep(0.4)

    # 3. Enable addon and give Kodi time to initialize the addon manifest and language tables
    execute_jsonrpc("Addons.SetAddonEnabled", {"addonid": addon_id, "enabled": True})
    time.sleep(0.5)

    # 4. Verify enabled status; retry enable if Kodi was busy during first call
    check = execute_jsonrpc("Addons.GetAddonDetails", {"addonid": addon_id, "properties": ["enabled"]})
    if not check.get("addon", {}).get("enabled", False):
        xbmc.log(f"[Twilight0Installer] Addon {addon_id} still disabled, retrying SetAddonEnabled...", xbmc.LOGWARNING)
        time.sleep(0.3)
        execute_jsonrpc("Addons.SetAddonEnabled", {"addonid": addon_id, "enabled": True})
        time.sleep(0.3)

    # 5. Refresh language subsystem
    try:
        lang_res = execute_jsonrpc("Settings.GetSettingValue", {"setting": "locale.language"})
        if "value" in lang_res:
            current_lang = lang_res["value"]
            execute_jsonrpc("Settings.SetSettingValue", {"setting": "locale.language", "value": current_lang})
    except Exception:
        pass


def get_current_kodi_codename():
    """Detect current Kodi codename (omega, nexus, etc.)."""
    build_str = xbmc.getInfoLabel("System.BuildVersion") or ""
    m = re.search(r"(\d+)\.", build_str)
    major = int(m.group(1)) if m else 21
    return KODI_CODENAMES.get(major, "omega")


def download_and_extract_zip(zip_url, target_addon_id, dp=None, dp_start=10, dp_end=90):
    """Download a zip archive from a URL and extract it to special://home/addons."""
    addons_dest = xbmcvfs.translatePath("special://home/addons/")
    temp_dir = xbmcvfs.translatePath("special://temp/")
    local_zip = os.path.join(temp_dir, f"{target_addon_id}.zip")

    try:
        req = urllib.request.Request(zip_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            total_size = int(resp.headers.get("content-length", 0))
            downloaded = 0
            chunk_size = 32 * 1024

            with open(local_zip, "wb") as f:
                while True:
                    if dp and dp.iscanceled():
                        return False
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if dp and total_size > 0:
                        pct = dp_start + int(((downloaded / float(total_size)) * (dp_end - dp_start) * 0.8))
                        dp.update(pct, f"Downloading [COLOR FF00D4FF]{target_addon_id}[/COLOR]...\n{downloaded // 1024} KB / {total_size // 1024} KB")

        if dp:
            dp.update(int(dp_start + (dp_end - dp_start) * 0.85), f"Extracting [COLOR FF00D4FF]{target_addon_id}[/COLOR]...")

        with zipfile.ZipFile(local_zip, "r") as zf:
            zf.extractall(addons_dest)

        # Cleanup temp file
        try:
            if os.path.exists(local_zip):
                os.remove(local_zip)
        except Exception:
            pass

        return True
    except Exception as e:
        xbmc.log(f"[Twilight0Installer] Failed to download/extract {target_addon_id} from {zip_url}: {e}", xbmc.LOGERROR)
        if dp:
            dp.update(dp_end, f"[COLOR FFFF5555]Error installing {target_addon_id}[/COLOR]")
        return False


def fetch_remote_repo_addons(xml_url, base_url, compressed=True):
    """Parse remote addons.xml (or .gz) and return dict mapping addon_id -> metadata."""
    addons = {}
    try:
        req = urllib.request.Request(xml_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
            if compressed:
                data = gzip.decompress(data)
        root = ET.fromstring(data)
        for addon_elem in root.findall("addon"):
            a_id = addon_elem.attrib.get("id")
            version = addon_elem.attrib.get("version")
            name = addon_elem.attrib.get("name", a_id)

            # Dependencies
            deps = []
            requires_elem = addon_elem.find("requires")
            if requires_elem is not None:
                for imp in requires_elem.findall("import"):
                    dep_id = imp.attrib.get("addon")
                    optional = imp.attrib.get("optional", "false").lower() == "true"
                    if dep_id and not dep_id.startswith("xbmc.") and not optional:
                        deps.append(dep_id)

            # Zip URL
            zip_url = f"{base_url}{a_id}/{a_id}-{version}.zip"

            addons[a_id] = {
                "id": a_id,
                "version": version,
                "name": name,
                "deps": deps,
                "zip_url": zip_url,
                "base_url": base_url
            }
    except Exception as e:
        xbmc.log(f"[Twilight0Installer] Error parsing repo at {xml_url}: {e}", xbmc.LOGERROR)
    return addons


import glob
import sqlite3


def get_all_available_addons():
    """Retrieve combined catalog of addons from Twilight0 repo, libs, and smrzips."""
    catalog = {}
    catalog.update(fetch_remote_repo_addons(REPO_TWILIGHT0_XML_GZ, REPO_TWILIGHT0_BASE, compressed=True))
    catalog.update(fetch_remote_repo_addons(REPO_LIBS_XML_GZ, REPO_LIBS_BASE, compressed=True))
    catalog.update(fetch_remote_repo_addons(REPO_SMRZIPS_XML, REPO_SMRZIPS_BASE, compressed=False))
    return catalog


def calculate_dependency_chain(root_addon_id, catalog=None):
    """
    Inspect the dependency chain prior to installation and return:
    (full_chain_set, missing_dependencies_set)
    """
    addons_dir = xbmcvfs.translatePath("special://home/addons/")
    installed_on_disk = set()
    if os.path.isdir(addons_dir):
        for d in os.listdir(addons_dir):
            if os.path.isfile(os.path.join(addons_dir, d, "addon.xml")):
                installed_on_disk.add(d)

    # Locate Kodi's active Addons DB
    db_pattern = xbmcvfs.translatePath("special://masterprofile/Database/Addons*.db")
    db_files = sorted(glob.glob(db_pattern), reverse=True)
    db_conn = sqlite3.connect(db_files[0]) if db_files else None

    to_visit = [root_addon_id]
    visited = set()
    full_chain = []

    while to_visit:
        curr = to_visit.pop(0)
        if curr in visited:
            continue
        visited.add(curr)
        full_chain.append(curr)

        deps = []
        # First check Addons DB for dependency metadata
        if db_conn:
            try:
                c = db_conn.cursor()
                c.execute("SELECT metadata FROM addons WHERE addonID=? ORDER BY id DESC LIMIT 1", (curr,))
                row = c.fetchone()
                if row and row[0]:
                    meta = json.loads(row[0].decode("utf-8", errors="replace") if isinstance(row[0], bytes) else row[0])
                    for d in meta.get("dependencies", []):
                        dep_id = d.get("addonId")
                        optional = d.get("optional", False)
                        if dep_id and not dep_id.startswith("xbmc.") and not dep_id.startswith("kodi.") and not optional:
                            deps.append(dep_id)
            except Exception:
                pass

        # Fallback to catalog if not found in db or db returned no deps
        if not deps and catalog and curr in catalog:
            deps.extend(catalog[curr].get("deps", []))

        for dep in deps:
            if dep not in visited and dep not in to_visit:
                to_visit.append(dep)

    if db_conn:
        try:
            db_conn.close()
        except Exception:
            pass

    missing = [a for a in full_chain if a not in installed_on_disk]
    xbmc.log(f"[Twilight0Installer] Dependency chain for {root_addon_id}: {len(full_chain)} total, {len(missing)} missing.", xbmc.LOGINFO)
    return set(full_chain), set(missing)





def ensure_twilight0_repo(catalog, dp=None):
    """
    Step 1: Install repository.twilight0 by downloading and extracting its zip,
    updating local addons, and enabling it via JSON-RPC.
    """
    if is_addon_installed("repository.twilight0"):
        # Make sure it is enabled
        execute_jsonrpc("Addons.SetAddonEnabled", {"addonid": "repository.twilight0", "enabled": True})
        return True

    repo_item = catalog.get("repository.twilight0")
    if not repo_item:
        xbmc.log("[Twilight0Installer] repository.twilight0 not found in catalog", xbmc.LOGERROR)
        return False

    if dp:
        dp.update(10, "Installing [COLOR FF00D4FF]repository.twilight0[/COLOR]...")

    # Download and extract the repository zip
    success = download_and_extract_zip(repo_item["zip_url"], "repository.twilight0", dp, dp_start=10, dp_end=25)
    if not success:
        return False

    # Register local addon and enable it
    xbmc.executebuiltin("UpdateLocalAddons")
    time.sleep(0.5)
    execute_jsonrpc("Addons.SetAddonEnabled", {"addonid": "repository.twilight0", "enabled": True})
    time.sleep(0.5)

    # Force repository database refresh so Kodi indexes its addons
    xbmc.executebuiltin("UpdateAddonRepos")
    time.sleep(0.5)
    xbmc.log("[Twilight0Installer] repository.twilight0 successfully installed and enabled.", xbmc.LOGINFO)
    return True


def wait_for_addon_installed(addon_id, total_expected=1, missing_set=None, timeout_seconds=120):
    """
    Step 3: Real-time filesystem watcher in background (DialogProgressBG).
    Leaves the foreground completely unblocked so Kodi's modal dialogs can display and interact cleanly.
    Maps percentage (0-100%) as: current newly installed / total expected addons in dependency chain.
    """
    addons_dir = xbmcvfs.translatePath("special://home/addons/")
    target_dir = os.path.join(addons_dir, addon_id)
    target_xml = os.path.join(target_dir, "addon.xml")

    total_expected = max(1, total_expected)
    if missing_set is None:
        missing_set = set()

    # Snapshot existing folders before installation started
    try:
        initial_folders = set(
            d for d in os.listdir(addons_dir)
            if os.path.isdir(os.path.join(addons_dir, d))
        )
    except Exception:
        initial_folders = set()

    start_time = time.time()
    last_file_count = 0
    stable_cycles = 0

    xbmc.log(f"[Twilight0Installer] File watcher started for {addon_id} at {target_dir} (expected: {total_expected} new addons)", xbmc.LOGINFO)

    bg_dp = xbmcgui.DialogProgressBG()
    bg_dp.create("Scripted Addon Installer", f"Preparing {addon_id} (0/{total_expected})...")

    seen_new_folders = []

    try:
        while (time.time() - start_time) < timeout_seconds:
            elapsed = int(time.time() - start_time)

            # Discover any new folders appearing inside special://home/addons/
            latest_folder = None
            try:
                current_dirs = [
                    d for d in os.listdir(addons_dir)
                    if os.path.isdir(os.path.join(addons_dir, d))
                ]
                new_dirs = [d for d in current_dirs if d not in initial_folders]
                for nd in new_dirs:
                    if nd not in seen_new_folders:
                        seen_new_folders.append(nd)
                if seen_new_folders:
                    latest_folder = seen_new_folders[-1]
            except Exception:
                pass

            # Calculate progress percentage: current installed vs total expected
            current_installed_count = len(seen_new_folders)
            # Reserve 100% for the final completion confirmation
            pct = min(99, int((float(current_installed_count) / float(total_expected)) * 100))

            if latest_folder:
                heading = f"Installing: {latest_folder}"
                msg = f"Progress: {current_installed_count}/{total_expected} ({pct}%) [{elapsed}s]"
            else:
                heading = f"Installing {addon_id}..."
                msg = f"Waiting for Kodi installer... ({current_installed_count}/{total_expected}) [{elapsed}s]"

            bg_dp.update(pct, heading, msg)

            # Check if target addon folder and its addon.xml exist
            if os.path.isdir(target_dir) and os.path.isfile(target_xml):
                try:
                    current_files = sum(len(files) for _, _, files in os.walk(target_dir))
                except Exception:
                    current_files = 0

                if current_files > 0 and current_files == last_file_count:
                    stable_cycles += 1
                else:
                    stable_cycles = 0
                    last_file_count = current_files

                # Once target addon file count is stable for at least 3 checks (1.5s), unpacking is finished
                if stable_cycles >= 3:
                    final_count = len(seen_new_folders)
                    xbmc.log(f"[Twilight0Installer] Watcher: {addon_id} scaffold complete ({current_files} files). Total new components: {final_count}/{total_expected}", xbmc.LOGINFO)
                    bg_dp.update(100, f"{addon_id} installed successfully!", f"Completed {final_count}/{total_expected} component(s)")
                    time.sleep(0.5)
                    execute_jsonrpc("Addons.SetAddonEnabled", {"addonid": addon_id, "enabled": True})
                    return True

            time.sleep(0.5)
    finally:
        bg_dp.close()

    xbmc.log(f"[Twilight0Installer] Watcher timed out waiting for {addon_id}", xbmc.LOGWARNING)
    return False


def install_addon_via_builtin(target_addon_id, catalog, dp=None):
    """
    Install flow:
    1. Ensure repository.twilight0 is installed via zip extraction and enabled.
    2. Inspect dependency chain and count total missing dependencies prior to triggering InstallAddon.
    3. Close any foreground modal progress dialog so the UI is completely clear.
    4. Trigger Kodi's native InstallAddon(target_addon_id) builtin function.
    5. Run filewatcher with background indicator (DialogProgressBG) showing current/total progress.
    """
    # 1) Install repository.twilight0 via zip extraction and enable it
    ensure_twilight0_repo(catalog, dp)

    # 2) Inspect dependency chain prior to installation
    if dp:
        dp.update(25, f"Calculating dependencies for [COLOR FF00D4FF]{target_addon_id}[/COLOR]...")

    full_chain, missing_set = calculate_dependency_chain(target_addon_id, catalog)
    total_expected = len(missing_set) if missing_set else 1
    xbmc.log(f"[Twilight0Installer] Addon {target_addon_id}: {total_expected} components to install: {missing_set}", xbmc.LOGINFO)

    # 3) Close foreground modal progress dialog before calling InstallAddon
    if dp:
        try:
            dp.close()
        except Exception:
            pass

    # 4) Trigger built-in method
    xbmc.executebuiltin(f"InstallAddon({target_addon_id})")

    # 5) Run filewatcher in background tracking progress against total_expected
    return wait_for_addon_installed(target_addon_id, total_expected=total_expected, missing_set=missing_set, timeout_seconds=120)


def run_default_bootstrap(interactive=False):
    """
    Default 1-action workflow:
    Installs:
    1. repository.twilight0
    2. plugin.video.alivegr via Hybrid Builtin + Watcher
    """
    dp = xbmcgui.DialogProgress()
    dp.create("Scripted Addon Installer", "Connecting to Twilight0 Repository...")

    catalog = get_all_available_addons()
    if not catalog:
        dp.close()
        xbmcgui.Dialog().ok("Installer Error", "Unable to retrieve addon catalog from repository.")
        return False

    dp.update(15, "Setting up Twilight0 Repository...")
    ensure_twilight0_repo(catalog, dp)

    # Install AliveGR via built-in method (handles closing dp cleanly)
    if "plugin.video.alivegr" in catalog:
        install_addon_via_builtin("plugin.video.alivegr", catalog, dp)

    xbmc.executebuiltin("UpdateLocalAddons")
    time.sleep(0.3)
    xbmc.executebuiltin("ReloadSkin()")

    xbmcgui.Dialog().notification(
        "Scripted Addon Installer",
        "AliveGR & Twilight0 Repository installed!",
        xbmcgui.NOTIFICATION_INFO,
        4000
    )

    dialog = xbmcgui.Dialog()
    dialog.ok(
        "Installation Complete",
        "[COLOR FF55FF55]Twilight0 Repository and AliveGR have been installed and activated successfully![/COLOR]\n\n"
        "Translations and strings have been loaded through Kodi's Addon Manager."
    )

    return True


def install_devtoolbox_setup():
    """Install Twilight0 repository and Dev ToolBox via Builtin + Watcher."""
    dp = xbmcgui.DialogProgress()
    dp.create("Scripted Addon Installer", "Connecting to Twilight0 Repository...")

    catalog = get_all_available_addons()
    if not catalog:
        dp.close()
        xbmcgui.Dialog().ok("Installer Error", "Unable to retrieve addon catalog from repository.")
        return False

    dp.update(15, "Setting up Twilight0 Repository...")
    ensure_twilight0_repo(catalog, dp)

    dp.update(45, "Installing Dev ToolBox...")
    if "plugin.program.devtoolbox" in catalog:
        install_addon_via_builtin("plugin.program.devtoolbox", catalog, dp)

    dp.update(95, "Synchronizing Kodi GUI...")
    xbmc.executebuiltin("UpdateLocalAddons")
    time.sleep(0.3)
    xbmc.executebuiltin("ReloadSkin()")

    dp.close()

    dialog = xbmcgui.Dialog()
    dialog.ok(
        "Installation Complete",
        "[COLOR FF55FF55]Twilight0 Repository and Dev ToolBox have been installed and activated successfully![/COLOR]\n\n"
        "Translations and strings have been loaded through Kodi's Addon Manager."
    )
    return True


def show_interactive_installer_menu():
    """Interactive menu to select which addon(s) to install from the repo."""
    dialog = xbmcgui.Dialog()
    catalog = get_all_available_addons()
    if not catalog:
        dialog.ok("Installer Error", "Could not load repository catalog. Check your internet connection.")
        return

    # List all available addons
    addon_ids = sorted(catalog.keys())
    options = []
    for aid in addon_ids:
        info = catalog[aid]
        status = "[COLOR FF55FF55][Installed][/COLOR]" if is_addon_installed(aid) else "[COLOR FF8A9BA8](Available)[/COLOR]"
        options.append(f"{info['name']} ({aid}) {status}")

    header = "Twilight0 Scripted Installer - Select Addon to Install:"
    sel = dialog.select(header, options)
    if sel >= 0:
        chosen_id = addon_ids[sel]
        dp = xbmcgui.DialogProgress()
        dp.create("Installing Addon", f"Installing {chosen_id}...")

        success = install_addon_via_builtin(chosen_id, catalog, dp)
        dp.close()

        if success:
            xbmc.executebuiltin("ReloadSkin()")
            dialog.ok(
                "Installation Complete",
                f"[COLOR FF55FF55]{chosen_id} has been installed and activated successfully![/COLOR]\n\n"
                f"Translations and strings have been loaded through Kodi's Addon Manager."
            )
        else:
            dialog.ok("Error", f"Failed to install {chosen_id}. Check Kodi log for details.")
