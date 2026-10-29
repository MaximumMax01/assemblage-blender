"""Download search results to disk.

Plain Python with no bpy: runs on the worker thread, testable in PowerShell.
"""

import hashlib
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

if __package__:
    from .search import USER_AGENT
else:
    from search import USER_AGENT

EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png"}
MAX_BYTES = 15_000_000  # refuse anything over 15 MB


def download_one(hit, folder, timeout=15):
    """Download one image and return the hit with a "path" added. Raises on failure."""
    url = hit["url"]
    if not url.startswith("https://"):
        raise ValueError("not an https link")

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get_content_type()
        ext = EXTENSIONS.get(content_type)
        if ext is None:
            raise ValueError(f"not a JPEG or PNG ({content_type})")
        data = response.read(MAX_BYTES + 1)  # read at most one byte past the limit
        if len(data) > MAX_BYTES:
            raise ValueError("file too large")

    # Name the file after a hash of its URL: safe characters, same URL -> same name.
    name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ext
    path = os.path.join(folder, name)
    with open(path, "wb") as f:
        f.write(data)
    return {**hit, "path": path}


def download_all(hits, folder, on_progress=None, max_workers=4):
    """Download every hit, 4 at a time. Returns (downloaded, failed), in search order."""
    os.makedirs(folder, exist_ok=True)
    downloaded, failed = [], []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(download_one, hit, folder): hit for hit in hits}
        for count, future in enumerate(as_completed(futures), start=1):
            hit = futures[future]
            try:
                downloaded.append(future.result())
            except Exception as exc:
                failed.append((hit["url"], f"{type(exc).__name__}: {exc}"))
            if on_progress is not None:
                on_progress(count, len(hits))

    rank = {hit["url"]: i for i, hit in enumerate(hits)}
    downloaded.sort(key=lambda d: rank[d["url"]])  # back into search-ranking order
    return downloaded, failed


if __name__ == "__main__":
    import sys
    import time

    from search import search_wikimedia

    query = " ".join(sys.argv[1:]) or "stage light"
    hits = search_wikimedia(query)
    start = time.perf_counter()
    done, failed = download_all(
        hits, "_test_downloads",
        on_progress=lambda n, total: print(f"  {n}/{total}", end="\r"),
    )
    elapsed = time.perf_counter() - start
    print(f"\nDownloaded {len(done)}/{len(hits)} in {elapsed:.1f} s")
    for url, reason in failed:
        print(f"  failed: {reason}  ({url[-50:]})")