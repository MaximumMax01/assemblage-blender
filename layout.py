"""Justified-row layout, shared by the PureRef board and the Blender board.

Pure math: no bpy, no Pillow. Works in "canvas units" where y grows DOWNWARD
(like PureRef and screen coordinates).
"""

ROW_HEIGHT = 1000    # every image starts this tall
CANVAS_WIDTH = 4000  # full rows are scaled to exactly this width
GAP = 40             # space between images, and between rows
GROUP_GAP = 200      # extra space between groups (slots)


def justified_rows(items):
    """items: list of (aspect, group) where aspect = width / height.

    Returns one (center_x, center_y, width, height) per item, in the same order.
    Full rows span CANVAS_WIDTH; short rows are never enlarged; each group
    starts on a new row.
    """
    groups = []  # lists of item indices, one list per run of the same group
    for i, (_, group) in enumerate(items):
        if not groups or items[groups[-1][-1]][1] != group:
            groups.append([])
        groups[-1].append(i)

    rects = [None] * len(items)
    y = 0.0
    for g_index, indices in enumerate(groups):
        rows, current = [], []
        for i in indices:
            current.append(i)
            span = sum(items[j][0] * ROW_HEIGHT for j in current) + GAP * (len(current) - 1)
            if span >= CANVAS_WIDTH:  # row is full: close it
                rows.append(current)
                current = []
        if current:
            rows.append(current)

        for row in rows:
            content = sum(items[j][0] * ROW_HEIGHT for j in row)
            available = CANVAS_WIDTH - GAP * (len(row) - 1)
            scale = min(1.0, available / content) if content > 0 else 1.0
            height = ROW_HEIGHT * scale
            x = 0.0
            for j in row:
                width = items[j][0] * ROW_HEIGHT * scale
                rects[j] = (x + width / 2, y + height / 2, width, height)
                x += width + GAP
            y += height + GAP

        if g_index < len(groups) - 1:
            y += GROUP_GAP
    return rects
