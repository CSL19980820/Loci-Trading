"""一次性：圆角外白底改透明，并重打包 loci.ico。"""
from __future__ import annotations

from collections import deque
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PNG = ROOT / "assets" / "loci-icon.png"
ICO = ROOT / "assets" / "loci.ico"


def flood_clear_white(img: Image.Image) -> int:
    px = img.load()
    assert px is not None
    w, h = img.size

    def is_bg(x: int, y: int) -> bool:
        r, g, b, a = px[x, y]
        return a > 0 and r >= 245 and g >= 245 and b >= 245

    queue: deque[tuple[int, int]] = deque()
    for start in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if is_bg(*start):
            queue.append(start)
    seen: set[tuple[int, int]] = set()
    while queue:
        x, y = queue.popleft()
        if (x, y) in seen or not (0 <= x < w and 0 <= y < h):
            continue
        if not is_bg(x, y):
            continue
        seen.add((x, y))
        px[x, y] = (0, 0, 0, 0)
        queue.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    return len(seen)


def main() -> None:
    img = Image.open(PNG).convert("RGBA")
    cleared = flood_clear_white(img)
    img.save(PNG, format="PNG")
    print(f"png transparent_pixels={cleared} corner={img.getpixel((0, 0))}")

    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    # Pillow ICO：用 sizes= 从大图缩放写入；append_images 只会留下一张废图
    img.save(ICO, format="ICO", sizes=sizes)
    print(f"ico written {ICO} bytes={ICO.stat().st_size}")

    touch = ROOT / "frontend" / "public" / "apple-touch-icon.png"
    img.resize((180, 180), Image.Resampling.LANCZOS).save(touch, format="PNG")
    print(f"apple-touch written {touch}")


if __name__ == "__main__":
    main()
