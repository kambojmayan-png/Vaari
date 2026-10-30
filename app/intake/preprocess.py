"""Image preprocessing before any register reader (pilot Part 5).

Runs on every register page before it reaches a reader, whichever reader it
is. The stored page (what staff see beside the form) keeps its colours; only
the copy sent to the reader is changed:

1. **Rotation.** EXIF orientation is applied when the upload is cleaned
   (``app/storage/sanitize.py``). A page photographed sideways with no EXIF
   hint can be turned by the operator with the upload's ``rotate`` field
   (90, 180 or 270 degrees clockwise); that turn is applied to the stored page too.
2. **Size.** The long side is brought into 1000 to 2000 pixels: big phone
   photos are shrunk (smaller upload, same legibility), small scans are enlarged.
   Images under 400 pixels are left alone; they are too small to help.
3. **Contrast.** The page is turned to greyscale and its levels stretched
   (1% cut at each end), which lifts faint pencil and ballpoint on grey paper.
"""

import io
from dataclasses import dataclass

from PIL import Image, ImageOps

MAX_LONG_SIDE = 2000
MIN_LONG_SIDE = 1000
TOO_SMALL = 400
VALID_TURNS = (0, 90, 180, 270)


@dataclass(frozen=True)
class PreprocessInfo:
    original_size: tuple[int, int]
    size: tuple[int, int]
    resized: bool
    contrast_before: tuple[int, int]
    contrast_after: tuple[int, int]


def rotate_clockwise(jpeg: bytes, degrees: int) -> bytes:
    """Turn a stored page by 90, 180 or 270 degrees clockwise (0 returns it unchanged)."""
    if degrees not in VALID_TURNS:
        raise ValueError("rotate must be 0, 90, 180 or 270")
    if degrees == 0:
        return jpeg
    with Image.open(io.BytesIO(jpeg)) as img:
        turned = img.rotate(-degrees, expand=True)
        buf = io.BytesIO()
        turned.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def preprocess_for_reader(image: bytes) -> tuple[bytes, PreprocessInfo]:
    """Return (JPEG bytes for the reader, what was done)."""
    with Image.open(io.BytesIO(image)) as src:
        img = ImageOps.exif_transpose(src)
        original = img.size
        gray = img.convert("L")

    before = gray.getextrema()
    long_side = max(gray.size)
    target = None
    if long_side > MAX_LONG_SIDE:
        target = MAX_LONG_SIDE
    elif TOO_SMALL <= long_side < MIN_LONG_SIDE:
        target = MIN_LONG_SIDE
    if target is not None:
        scale = target / long_side
        gray = gray.resize((max(1, round(gray.width * scale)), max(1, round(gray.height * scale))), Image.LANCZOS)

    stretched = ImageOps.autocontrast(gray, cutoff=1)
    after = stretched.getextrema()

    buf = io.BytesIO()
    stretched.save(buf, format="JPEG", quality=90)
    return buf.getvalue(), PreprocessInfo(
        original_size=original,
        size=stretched.size,
        resized=target is not None,
        contrast_before=before,
        contrast_after=after,
    )
