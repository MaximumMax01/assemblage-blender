"""Prepare a release: stable zip names + the extension listing Blender reads.

Developer tool. Run from the repo root AFTER building the zips into dist/:
    python3 tools/make_repo.py
    python3 tools/make_repo.py --blender "C:\\Program Files\\Blender Foundation\\Blender 5.3\\blender.exe"

It does three things:
1. Copies the built zips to dist/upload/ with names that never change
   (assemblage-windows_x64.zip, assemblage-macos_arm64.zip), so links like
   .../releases/latest/download/assemblage-windows_x64.zip keep working
   across versions.
2. Asks Blender to write the extension listing (index.json) for them.
3. Points every download address in that listing at this version's GitHub
   release files, and saves it as docs/index.json for GitHub Pages.

Blender reads docs/index.json to install by drag and drop and to offer
updates. The zips themselves stay in GitHub Releases, so the repository's
history doesn't fill up with 40 MB files.
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlparse

REPO = "MaximumMax01/assemblage-blender"
DEFAULT_BLENDER = {
    "darwin": "/Applications/Blender.app/Contents/MacOS/Blender",
    "win32": r"C:\Program Files\Blender Foundation\Blender 5.3\blender.exe",
}.get(sys.platform, "blender")


def stable_name(path):
    """assemblage-1.0.0-windows_x64.zip -> assemblage-windows_x64.zip"""
    match = re.search(r"-(windows_x64|macos_arm64|macos_x64|linux_x64)\.zip$", path)
    if not match:
        raise SystemExit(f"Can't tell which platform {os.path.basename(path)} is for.")
    return f"assemblage-{match.group(1)}.zip"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", default=DEFAULT_BLENDER, help="path to the Blender program")
    parser.add_argument("--dist", default="dist")
    args = parser.parse_args()

    # A tiny regex instead of a TOML library: works on any Python 3.
    with open("blender_manifest.toml", encoding="utf-8") as f:
        version = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M).group(1)
    built = sorted(glob.glob(os.path.join(args.dist, f"assemblage-{version}-*.zip")))
    if not built:
        sys.exit(f"No zips for version {version} in {args.dist}/. Build them first.")

    # 1. Stable names, in dist/upload/ (the files you attach to the release)
    upload = os.path.join(args.dist, "upload")
    shutil.rmtree(upload, ignore_errors=True)
    os.makedirs(upload)
    for path in built:
        shutil.copy2(path, os.path.join(upload, stable_name(path)))
        print(f"  {os.path.basename(path)}  ->  upload/{stable_name(path)}")

    # 2. Let Blender write the listing. It works in a scratch folder so that
    #    only our zips are in it (it lists every zip it finds).
    with tempfile.TemporaryDirectory() as scratch:
        for name in os.listdir(upload):
            shutil.copy2(os.path.join(upload, name), scratch)
        result = subprocess.run(
            [args.blender, "--command", "extension", "server-generate", f"--repo-dir={scratch}"],
            capture_output=True, text=True)
        index_path = os.path.join(scratch, "index.json")
        if result.returncode != 0 or not os.path.exists(index_path):
            sys.exit("Blender couldn't write the listing:\n" + result.stdout + result.stderr)
        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)

    # 3. Download addresses -> this version's release files on GitHub.
    #    A fixed version (not "latest") on purpose: the listing also records
    #    each file's size and fingerprint, which only match this exact file.
    base = f"https://github.com/{REPO}/releases/download/v{version}/"
    for entry in index.get("data", []):
        filename = os.path.basename(urlparse(entry["archive_url"]).path)
        entry["archive_url"] = base + filename
        print(f"  listing: {entry.get('platforms', ['all'])} -> {entry['archive_url']}")

    os.makedirs("docs", exist_ok=True)
    with open(os.path.join("docs", "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)
        f.write("\n")

    print(f"""
Done. Next:
  1. On GitHub, edit (or create) the release with tag v{version}.
     Attach the files in {upload}/ (delete any old-named zips first).
  2. git add docs/index.json && git commit -m "Listing for v{version}" && git push
     Do this AFTER the files are on the release: the listing points at them.
  3. Test: drag the button on https://{REPO.split('/')[0].lower()}.github.io/{REPO.split('/')[1]}/ into Blender.""")


if __name__ == "__main__":
    main()
