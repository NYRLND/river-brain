"""Render site/icon-{180,192,512}.png from the same geometry as site/icon.svg.
Run: python scripts/make_icons.py   (needs matplotlib)"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, PathPatch
from matplotlib.path import Path as MPath

SITE = Path(__file__).resolve().parents[1] / "site"


def wave(dy):
    # Same cubic Béziers as icon.svg: M96 214 c40-34 80-34 120 0 s80 34 120 0 60-34 80-17
    pts = [(96, 214), (136, 180), (176, 180), (216, 214), (256, 248), (296, 248), (336, 214),
           (376, 180), (396, 180), (416, 197)]
    return MPath([(x, y + dy) for x, y in pts], [MPath.MOVETO] + [MPath.CURVE4] * 9)


def render(size: int, full_bleed: bool):
    dpi = 100
    fig = plt.figure(figsize=(size / dpi, size / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 512)
    ax.set_ylim(512, 0)
    ax.axis("off")
    fig.patch.set_alpha(0)
    px = lambda w: w * size / 512 * 72 / dpi  # SVG px at 512 → points at this size
    if full_bleed:  # iOS applies its own rounded mask
        ax.add_patch(plt.Rectangle((0, 0), 512, 512, color="#1c5cab"))
    else:
        ax.add_patch(FancyBboxPatch((0, 0), 512, 512, boxstyle="round,pad=0,rounding_size=112", color="#1c5cab"))
    for dy, color in ((0, "#ffffff"), (84, "#9ec5f4"), (168, "#5598e7")):
        ax.add_patch(PathPatch(wave(dy), fill=False, edgecolor=color, lw=px(30), capstyle="round"))
    arrow = MPath([(256, 70), (256, 154), (226, 124), (256, 154), (286, 124)],
                  [MPath.MOVETO, MPath.LINETO, MPath.MOVETO, MPath.LINETO, MPath.LINETO])
    ax.add_patch(PathPatch(arrow, fill=False, edgecolor="#ffffff", lw=px(26), capstyle="round", joinstyle="round"))
    fig.savefig(SITE / f"icon-{size}.png", dpi=dpi, transparent=not full_bleed)
    plt.close(fig)


if __name__ == "__main__":
    render(180, full_bleed=True)   # apple-touch-icon
    render(192, full_bleed=False)
    render(512, full_bleed=False)
    print("wrote", *sorted(p.name for p in SITE.glob("icon-*.png")))
