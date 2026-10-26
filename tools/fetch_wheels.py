"""Download every wheel the extension bundles, for every platform we ship.

Works on Windows and Mac with any Python 3 that has pip:
    Mac:      python3 tools/fetch_wheels.py
    Windows:  python tools\\fetch_wheels.py
Then paste the printed `wheels = [...]` block into blender_manifest.toml.
"""

import os
import subprocess
import sys

BLENDER_PYTHON = "3.13"  # Blender 5.2's Python version

# Every package listed explicitly, and --no-deps below: we decide exactly
# what ships. (Blender already includes NumPy, so it must never be bundled.)
PACKAGES = [
    "pillow==12.3.0",
    "onnxruntime==1.30.0",
    # onnxruntime's own dependencies (NumPy left out on purpose: Blender has it)
    "flatbuffers==25.12.19",
    "packaging==26.3",
    "protobuf==7.36.1",
]

PLATFORMS = {
    "windows-x64": "win_amd64",
    "macos-arm64": "macosx_14_0_arm64",  # macOS 14+: onnxruntime 1.30 needs it
}


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    wheels = os.path.join(root, "wheels")
    for blender_name, pip_tag in PLATFORMS.items():
        print(f"--- {blender_name} ---")
        subprocess.run(
            [sys.executable, "-m", "pip", "download", *PACKAGES,
             "--only-binary=:all:", "--no-deps",
             "--python-version", BLENDER_PYTHON, "--platform", pip_tag,
             "-d", wheels],
            check=True,  # stop with an error if any download fails
        )

    files = sorted(f for f in os.listdir(wheels) if f.endswith(".whl"))
    print("\nPaste into blender_manifest.toml:\n")
    print(f"platforms = {list(PLATFORMS)}".replace("'", '"'))
    print("wheels = [")
    for name in files:
        print(f'  "./wheels/{name}",')
    print("]")


if __name__ == "__main__":
    main()