"""Log Assemblage's download counts: one line per run in tools/downloads.csv.

Developer tool. Run from the repo root, once a day at the same time:
    python3 tools/downloads.py

GitHub counts every download of each release zip, including direct links,
and anyone can read the numbers (no login). That includes your own test
downloads, so set OWN_DOWNLOADS to how many of those you made.

The log lives in tools/, which the add-on build already leaves out.
"""

import csv
import datetime
import json
import os
import urllib.request

REPO = "MaximumMax01/assemblage-blender"
OWN_DOWNLOADS = 0  # your own test downloads, so the "real" number stays honest
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads.csv")


def fetch_counts():
    """{zip name: downloads}, added up over every published release."""
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/releases",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "assemblage-downloads"})
    with urllib.request.urlopen(request, timeout=15) as response:
        releases = json.load(response)
    counts = {}
    for release in releases:
        if release.get("draft"):
            continue  # drafts are private: only your own test downloads
        for asset in release.get("assets", []):
            counts[asset["name"]] = counts.get(asset["name"], 0) + asset["download_count"]
    return counts


def last_total():
    """The total from the previous run, or None on the first run."""
    if not os.path.exists(LOG):
        return None
    with open(LOG, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return int(rows[-1]["total"]) if rows else None


def main():
    counts = fetch_counts()
    total = sum(counts.values())
    previous = last_total()
    now = datetime.datetime.now().isoformat(timespec="minutes")

    new_file = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["time", "total", "not_counting_own", "per_zip"])
        writer.writerow([now, total, total - OWN_DOWNLOADS, json.dumps(counts)])

    for name, n in sorted(counts.items()):
        print(f"{n:>6}  {name}")
    print(f"{total:>6}  total ({total - OWN_DOWNLOADS} not counting your own {OWN_DOWNLOADS})")
    if previous is not None:
        print(f"{total - previous:>+6}  since the last time you ran this")


if __name__ == "__main__":
    main()
