# Assemblage

**Type what you're modelling. Get a reference board.**

Assemblage is a Blender extension that searches the web for reference images,
uses an on-device AI model to rank them and pick the most useful ones, and
lays them out as a board: inside Blender, or as a PureRef file.

![A reference board built by Assemblage](docs/board.png)

## Install

1. Download the zip for your system from the
   [latest release](../../releases/latest) (Windows or macOS).
2. Drag the zip into Blender and confirm.
3. Press **N** in the 3D viewport and open the **Assemblage** tab.

The first time, click **Download AI Model (608 MB)**. It downloads once,
is checked against a fingerprint, and runs entirely on your computer.

## Use

1. Type what you're modelling. **Be specific**: "black mesh office chair"
   finds better references than "chair".
2. Click **Search**. Images are downloaded, filtered (too small, blurry,
   duplicates), and ranked by the AI, best first. The best few are ticked.
3. Untick anything you don't want, tick anything it missed.
4. **Send to Blender** lays the board out in a side viewport, far from your
   model. **Send to PureRef** saves a .pur file and opens it.

## Requirements

- Blender 5.2 or newer
- Windows (64-bit) or macOS 14+ on Apple Silicon
- Internet access enabled in Blender (Preferences > System > Network)

## How it decides what's a good reference

Each image is scored with CLIP on two questions: is it the thing you asked for,
and does it look like a useful reference (a clear product-style shot rather than
a wide scene, collage or watermarked stock image)? The phrases and weights were
chosen by measuring them against hand-labelled searches, not by guesswork.
See `scoring.py`.

## Privacy and images

Your search terms go to DuckDuckGo and Wikimedia Commons, and images are
downloaded from the sites they're hosted on. Nothing else leaves your computer.
Images belong to their owners: use them as references, not in published work.

## Licence

GPL-3.0-or-later. Third-party code and models are credited in `NOTICE`.
