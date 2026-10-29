"""Download the CLIP model files once and verify their fingerprints.

Plain Python, no bpy: runs on the worker thread.
"""

import hashlib
import os
import urllib.request

try:
    from .search import USER_AGENT  # inside Blender (as part of the package)
except ImportError:
    from search import USER_AGENT   # run directly from PowerShell

# Where the files live: your GitHub release tagged "models-v1".
BASE_URL = "https://github.com/MaximumMax01/assemblage-blender/releases/tag/models-v1"

# name on disk -> SHA-256 fingerprint of the exact file we exported and tested
FILES = {
    "image": ("ViT-B-32_image_fp32.onnx",
              "03ca960e0cb732f7957f9345354c9c4208b1422eb3294a0318dee801ce9c6301"),
    "text": ("ViT-B-32_text_fp32.onnx",
             "a0cb603fcf6566a84f99e678462abf61dd99277de9c6d9c6f0fc2c447d920006"),
}
DOWNLOAD_MB = 608
CHUNK = 1024 * 1024  # read 1 MB at a time


def paths(folder):
    return {kind: os.path.join(folder, name) for kind, (name, _) in FILES.items()}


def is_installed(folder):
    # A file only gets its final name after its fingerprint has been checked
    # (see download), so "exists" already means "verified".
    return all(os.path.isfile(p) for p in paths(folder).values())


def download(folder, on_progress=None, timeout=30):
    """Fetch any missing model file, verify it, then give it its real name."""
    os.makedirs(folder, exist_ok=True)
    for name, expected in FILES.values():
        final = os.path.join(folder, name)
        if os.path.isfile(final):
            continue
        partial = final + ".part"
        request = urllib.request.Request(BASE_URL + name, headers={"User-Agent": USER_AGENT})
        fingerprint = hashlib.sha256()
        received = 0
        with urllib.request.urlopen(request, timeout=timeout) as response, open(partial, "wb") as f:
            total = int(response.headers.get("Content-Length") or 0)
            while True:
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                fingerprint.update(chunk)  # fingerprint as we go: no second pass
                received += len(chunk)
                if on_progress is not None:
                    on_progress(name, received, total)
        if fingerprint.hexdigest() != expected:
            os.remove(partial)
            raise ValueError(f"{name} failed its fingerprint check (damaged or not the "
                             "expected file); nothing was installed")
        os.replace(partial, final)  # only now does it count as installed
