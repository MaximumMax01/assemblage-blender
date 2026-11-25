# Assemblage

**Type what you're modelling. Get a reference board.**

Assemblage is a Blender extension that searches the web for reference images,
uses an on-device AI to rank them and pick the most useful ones, and
lays them out as a board: inside Blender, or as a PureRef file.

**[Download Assemblage](https://maximummax01.github.io/assemblage-blender/)**

## Install

1. Open the [download page](https://maximummax01.github.io/assemblage-blender/)
   and click the button for your computer. You can also get the zip for your
   system from the [latest release](../../releases/latest).
2. Drag the downloaded zip into Blender and click **Install**.
3. Press **N** in the 3D viewport and open the **Assemblage** tab.

In Safari, if the download unzips itself, right-click the button and choose
**Download Linked File**. Blender needs the zip itself.

The first time, click **Download AI Model (608 MB)**. It downloads once,
is checked against a fingerprint, and runs entirely on your computer.
Searching works without it.

### Get updates inside Blender (optional)

Add Assemblage's repository once, and Blender tells you when there's a new version:

1. In Blender, open **Preferences > Get Extensions**. Open the **Repositories**
   menu, click **+**, and choose **Add Remote Repository**.
2. Paste this address:
   ```
   https://maximummax01.github.io/assemblage-blender/index.json
   ```
3. Tick **Check for Updates on Start** and click **Create**.

Assemblage then appears in Get Extensions, ready to install or update.

Without the repository, update by downloading the newest version and
dragging it into Blender.

## Using it

1. **Type what you're modelling, and be specific.** "black mesh office chair"
   finds better references than "chair". If you want it shown somewhere real,
   say where: "drinking fountain on a hallway wall" brings back installed
   fountains instead of catalog photos on white.
   Don't know what it's called? Describe it ("rubber strip where office walls
   meet the floor"), click **Suggest Names**, then click the name you mean.
2. **Click Search.** Images are downloaded, filtered (too small, blurry,
   duplicates), and ranked by the AI, best first. The best few are ticked.
3. **Check the picks.** Untick anything you don't want, and tick anything it missed.
4. **Send the board.** **Send to Blender** lays the board out in a side
   viewport, far from your model. Use `Shift` + click to navigate.
   **Send to PureRef** saves a .pur file and opens it.

## Requirements

- Blender 5.2 or newer
- Windows (64-bit) or macOS 14+ on Apple Silicon
- Online access allowed in Blender (`Preferences > System > Network`). It's
  needed to search and to download the AI model. Blender asks the first time.

## How it decides what's a good reference

Each image is scored with CLIP on two questions: is it the thing you asked for,
and does it look like a useful reference (a clear product-style shot rather than
a wide scene, collage or watermarked stock image)? The phrases and weights were
chosen by measuring them against hand-labelled searches, not by guesswork.
See `scoring.py`.

## Privacy and images

Your search terms go to DuckDuckGo and Wikimedia Commons, and images are
downloaded from the sites they're hosted on. If you click **Suggest Names**,
your description is sent to Assemblage's server (a Cloudflare Worker running an
open AI model) to come up with names; it isn't stored. Nothing else leaves your
computer.

Images belong to their owners: use them as references, not in published work.

## License

GPL-3.0-or-later. Third-party code and models are credited in `NOTICE`.
