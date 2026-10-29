"""Image search for Assemblage.

Plain Python with no bpy, so it can run on a background thread and be
tested outside Blender.
"""

import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# Wikimedia asks every API client to identify itself with contact details.
USER_AGENT = "Assemblage/0.1 (Blender reference-board add-on; contact: dazzled3d@gmail.com)"
WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
ALLOWED_MIME = {"image/jpeg", "image/png"}

# Stock sites (watermarked previews, useless as references) and AI-image sites.
# Matched on the link's real host name, so "notshutterstock.com" isn't caught by accident.
BLOCKED_HOSTS = {
    "shutterstock.com", "istockphoto.com", "gettyimages.com", "alamy.com",
    "dreamstime.com", "depositphotos.com", "123rf.com", "stock.adobe.com",
    "freepik.com", "vecteezy.com", "pond5.com", "bigstockphoto.com",
    "lexica.art", "openart.ai", "civitai.com", "prompthero.com",
    "nightcafe.studio", "playground.com", "midjourney.com",
}


def _blocked(url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in BLOCKED_HOSTS)


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


def search_web(query, limit=40):
    """Web image search through the ddgs package (DuckDuckGo, with Bing as backup).

    Unofficial: ddgs reads the search sites' own pages, so it can break or be
    rate-limited without warning. search_all() isolates its failures.
    """
    from ddgs import DDGS  # imported here: if the package is broken, only this source fails

    results = []
    for item in DDGS().images(query, max_results=limit, safesearch="moderate"):
        image_url = item.get("image") or ""
        if not image_url.startswith("https://") or _blocked(image_url):
            continue
        results.append({
            "title": item.get("title") or "",
            "url": image_url,
            "width": item.get("width"),
            "height": item.get("height"),
            "source": "web",
        })
    return results


def search_all(query):
    """Run every source at once. Returns (hits, problems).

    One source failing never sinks the search: its error goes into
    `problems` and the other sources' results still come back.
    """
    sources = {"Web search": search_web, "Wikimedia": search_wikimedia}
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        futures = {name: pool.submit(fn, query) for name, fn in sources.items()}

    lists, problems = [], []
    for name, future in futures.items():
        try:
            lists.append(future.result())
        except Exception as exc:
            problems.append(f"{name} unavailable ({type(exc).__name__})")

    # Interleave the sources (web 1, wiki 1, web 2, wiki 2, ...) and drop repeats.
    hits, seen = [], set()
    for i in range(max((len(x) for x in lists), default=0)):
        for results in lists:
            if i < len(results) and results[i]["url"] not in seen:
                seen.add(results[i]["url"])
                hits.append(results[i])
    return hits, problems
