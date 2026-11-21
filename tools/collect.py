"""Collect a labelling set: exactly the images the add-on would rank for a search.

Developer tool. Run from the repo root:
    python3 tools/collect.py office chair
Writes _labels/office-chair/ with the images that pass the add-on's own
filters, plus subject.txt so later tools know what was searched.

Same search, same download, same filters as the add-on, so what you label is
what the ranking really sees (download.py's test mode skips the filters).
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import download  # noqa: E402
import filters  # noqa: E402
import search  # noqa: E402


def main():
    subject = " ".join(sys.argv[1:]).strip()
    if not subject:
        sys.exit("usage: python3 tools/collect.py <what to search for>")
    slug = re.sub(r"[^a-z0-9]+", "-", subject.lower()).strip("-")
    # above: slug is a safe folder name for the subject, e.g. "office chair" -> "office-chair"  
    folder = os.path.join("_labels", slug)
    if os.path.exists(folder):
        sys.exit(f"{folder} already exists. Delete it first if you want a fresh set: "
                 "a labelled set should never be quietly replaced.")
    os.makedirs(folder)

    hits, problems = search.search_all(subject)
    print(f"{len(hits)} results" + (f" ({'; '.join(problems)})" if problems else ""))
    downloaded, failed = download.download_all(
        hits, folder, on_progress=lambda n, total: print(f"  downloading {n}/{total}", end="\r"))
    kept, rejected = filters.filter_all(downloaded)
    for item, _reason in rejected:
        os.remove(item["path"])  # the add-on never ranks these, so neither do we

    with open(os.path.join(folder, "subject.txt"), "w", encoding="utf-8") as f:
        f.write(subject + "\n")
    print(f"\n{len(kept)} images kept in {folder} "
          f"({len(rejected)} filtered out, {len(failed)} failed to download)")


if __name__ == "__main__":
    main()
