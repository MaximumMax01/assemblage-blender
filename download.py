"""Download search results to disk.

Plain Python with no bpy: runs on the worker thread, testable in PowerShell.
"""

import hashlib
import io
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image

if __package__:
    from .search import USER_AGENT
else:
    from search import USER_AGENT

MAX_BYTES = 15_000_000  # refuse anything over 15 MB
PER_HOST = 2            # at most 2 downloads from the same server at once

# One "2 at a time" gate per server, shared by all download threads.
_host_gates = defaultdict(lambda: threading.Semaphore(PER_HOST))
_gates_lock = threading.Lock()


def _gate(url):
    host = urllib.parse.urlparse(url).hostname or ""
    with _gates_lock:  # two threads creating the same host's gate at once would make two
        return _host_gates[host]


def _fetch(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with _gate(url), urllib.request.urlopen(request, timeout=timeout) as response:
            label = response.headers.get_content_type()
            if not (label.startswith("image/") or label == "application/octet-stream"):
                raise ValueError(f"not an image ({label})")
            data = response.read(MAX_BYTES + 1)  # read at most one byte past the limit
    except urllib.error.HTTPError as exc:
        # Servers usually explain a refusal in the response body: keep the first line.
        reason = exc.read(300).decode("utf-8", "replace").strip().splitlines()
        raise ValueError(f"HTTP {exc.code}" + (f": {reason[0][:120]}" if reason else "")) from None
    if len(data) > MAX_BYTES:
        raise ValueError("file too large")
    return data


def download_one(hit, folder, timeout=15):
    """Download one image and return the hit with a "path" added. Raises on failure."""
    url = hit["url"]
    if not url.startswith("https://"):
        raise ValueError("not an https link")
    data = _fetch(url, timeout)

    # Trust the bytes, not the label: servers often mislabel images, so let
    # Pillow identify the actual format.
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
    except Exception:
        raise ValueError("not a readable image") from None

    # Name the file after a hash of its URL: safe characters, same URL -> same name.
    stem = os.path.join(folder, hashlib.sha1(url.encode("utf-8")).hexdigest()[:16])
    if fmt in ("JPEG", "PNG"):
        path = stem + (".jpg" if fmt == "JPEG" else ".png")
        with open(path, "wb") as f:
            f.write(data)  # already a format everything downstream reads
    else:
        # WebP, AVIF, GIF...: convert once here, so filters, thumbnails and
        # boards only ever see JPEG.
        path = stem + ".jpg"
        img.convert("RGBA").convert("RGB").save(path, quality=92)
    return {**hit, "path": path}


def download_all(hits, folder, on_progress=None, max_workers=8):
    """Download every hit, 8 at a time (2 per server). Returns (downloaded, failed)."""
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

    from search import search_all

    query = " ".join(sys.argv[1:]) or "stage light"
    hits, problems = search_all(query)
    print(f"{len(hits)} results" + (f" ({'; '.join(problems)})" if problems else ""))
    start = time.perf_counter()
    done, failed = download_all(
        hits, "_test_downloads",
        on_progress=lambda n, total: print(f"  {n}/{total}", end="\r"),
    )
    elapsed = time.perf_counter() - start
    print(f"\nDownloaded {len(done)}/{len(hits)} in {elapsed:.1f} s")
    for url, reason in failed:
        print(f"  failed: {reason}  ({url[-50:]})")