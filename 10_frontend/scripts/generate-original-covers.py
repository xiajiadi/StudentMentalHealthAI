"""Reproducible original abstract SVG covers; no external artwork input.

All paths, palettes and compositions are authored for this project. No logos,
embedded raster data, remote resources, fonts or text. Decorative only.
"""
from pathlib import Path
import math

PALETTES = [
    ("#204ac7", "#34bce0", "#d990e9", "#f68dc6"),
    ("#247a91", "#52cfb3", "#c7f18c", "#6fbfea"),
    ("#7545ca", "#bb64da", "#f99178", "#ffd075"),
    ("#2368c5", "#70b7ee", "#ffe695", "#af9cec"),
    ("#126d6e", "#4ec7a7", "#9bd4e6", "#c6eab2"),
    ("#394baa", "#a487e0", "#ebadd1", "#80d1e4"),
    ("#ab588a", "#f2a788", "#f4d7b0", "#e0a1d8"),
]


def cover(index: int) -> str:
    a, b, c, d = PALETTES[index % len(PALETTES)]
    phase = (index // len(PALETTES)) * 0.8 + index * 0.18
    y = round(230 + math.sin(phase) * 160)
    rise = round(80 + math.cos(phase) * 130)
    mirror = "translate(1200 0) scale(-1 1)" if index % 2 else ""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 628" width="1200" height="628">
<defs>
 <linearGradient id="base" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{a}"/><stop offset=".6" stop-color="{b}"/><stop offset="1" stop-color="{a}"/></linearGradient>
 <linearGradient id="ribbon" x1="0" y1="0" x2="1" y2=".5"><stop stop-color="{c}"/><stop offset=".55" stop-color="{d}"/><stop offset="1" stop-color="{b}"/></linearGradient>
 <radialGradient id="glow"><stop stop-color="{d}" stop-opacity=".9"/><stop offset="1" stop-color="{d}" stop-opacity="0"/></radialGradient>
 <filter id="soft" x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur stdDeviation="18"/></filter>
</defs>
<rect width="1200" height="628" fill="url(#base)"/>
<g transform="{mirror}">
 <ellipse cx="{220 + index * 23 % 750}" cy="{95 + index * 37 % 420}" rx="460" ry="310" fill="url(#glow)"/>
 <path d="M-150 {y} C180 {y-rise},370 {y+210},610 {y+65} S1040 {y-175},1350 {y+55} L1350 {y+230} C980 {y+150},805 {y+340},520 {y+210} S110 {y+110},-150 {y+200}Z" fill="url(#ribbon)" opacity=".88" filter="url(#soft)"/>
 <path d="M-100 {y+55} C220 {y-70},400 {y+230},680 {y+110} S1000 {y-55},1300 {y+75}" fill="none" stroke="{c}" stroke-width="{50 + index % 4 * 12}" opacity=".28" filter="url(#soft)"/>
 <path d="M-80 {y+85} C230 {y-35},430 {y+250},700 {y+135} S1020 {y-20},1320 {y+100}" fill="none" stroke="{d}" stroke-width="12" opacity=".2"/>
</g>
</svg>\n'''


def main():
    output = Path(__file__).resolve().parents[1] / "public/assets/psynova/original-covers"
    output.mkdir(parents=True, exist_ok=True)
    for index in range(28):
        (output / f"flow-{index + 1:02d}.svg").write_text(cover(index), encoding="utf-8")


if __name__ == "__main__":
    main()
