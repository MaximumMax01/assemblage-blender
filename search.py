"""Image search for Assemblage.

Plain Python with no bpy, so it can run on a background thread and be
tested outside Blender.
"""

import json
import urllib.parse
import urllib.request

# Wikimedia asks every API client to identify itself with contact details.
USER_AGENT = "Assemblage/0.1 (Blender reference-board add-on; contact: maxwellolsen@gmail.com)"
WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
ALLOWED_MIME = {"image/jpeg", "image/png"}


def search_wikimedia(query, limit=20, width=1600, timeout=10):
    """Return up to `limit` image results from Wikimedia Commons."""
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": "6",       # namespace 6 = File: pages, i.e. images
        "gsrlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "url|size|mime",
        "iiurlwidth": str(width),  # ask for a resized copy, not the original
    }
    url = WIKIMEDIA_API + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.load(response)

    pages = data.get("query", {}).get("pages", [])
    pages.sort(key=lambda p: p.get("index", 0))  # keep the search ranking order

    results = []
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") not in ALLOWED_MIME:
            continue
        image_url = info.get("thumburl") or info.get("url")
        if not image_url or not image_url.startswith("https://"):
            continue
        results.append({
            "title": page.get("title", ""),
            "url": image_url,
            "width": info.get("width"),
            "height": info.get("height"),
            "source": "wikimedia",
        })
    return results


if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]) or "stage light"
    hits = search_wikimedia(query)
    print(f"{len(hits)} results for {query!r}")
    for hit in hits:
        print(f"{hit['width']}x{hit['height']}  {hit['title']}")