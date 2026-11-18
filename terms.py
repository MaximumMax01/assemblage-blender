"""Turn a plain description into the names the trade uses ("wall trim" ->
"rubber cove base"), via Assemblage's Cloudflare Worker.

Plain Python with no bpy: runs on the worker thread, testable in PowerShell.
Any failure raises; the caller falls back to searching the user's own words.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

if __package__:
    from .search import USER_AGENT
else:
    from search import USER_AGENT

# Replace with your deployed Worker's URL.
SUGGEST_URL = "https://assemblage-terms.assemblageaddon.workers.dev"
TIMEOUT = 8      # seconds; a slow answer is worse than none
MAX_INPUT = 300  # the Worker cuts longer text anyway

_cache = {}      # description -> terms, for this Blender session


def _normalise(text):
    return " ".join(text.lower().split())[:MAX_INPUT]


def suggest(text, url=SUGGEST_URL, timeout=TIMEOUT, model=None):
    """Return a list of {"term", "gloss"} dicts (1 to 5). Raises on any failure."""
    key = (_normalise(text), model)
    if not key[0]:
        raise ValueError("empty description")
    if key in _cache:
        return _cache[key]

    full_url = url + (f"?model={urllib.parse.quote(model)}" if model else "")
    body = json.dumps({"text": key[0]}).encode("utf-8")
    request = urllib.request.Request(full_url, data=body, method="POST", headers={
        "User-Agent": USER_AGENT, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        reason = {429: "too many requests, try again in a minute",
                  503: "daily limit reached or service down"}.get(exc.code, f"HTTP {exc.code}")
        raise RuntimeError(reason) from None

    terms = []
    for item in data.get("terms") or []:
        term = str(item.get("term", "")).strip()[:60]
        if term:
            terms.append({"term": term, "gloss": str(item.get("gloss", "")).strip()[:100]})
    if not terms:
        raise RuntimeError("no suggestions came back")
    _cache[key] = terms[:5]
    return _cache[key]


if __name__ == "__main__":
    import sys

    for t in suggest(" ".join(sys.argv[1:]) or "wall trim in an office"):
        print(f"{t['term']:<32} {t['gloss']}")
