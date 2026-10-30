"""Strip metadata and re-encode every uploaded image before it is saved (pilot item B7).

Phone photos carry EXIF metadata, often including the GPS position, the phone
model and the time. The evidence position Vaari keeps is the one the driver's
phone reports to the API, with its accuracy; the copy inside the photo is not
needed and is a privacy risk. So every image is decoded, turned upright from
its EXIF orientation, converted to plain RGB and saved again as JPEG with no
EXIF, XMP, ICC profile or comments. The same input always gives the same
output bytes, so exact-duplicate detection still works on the stored file.
"""

import io

from PIL import Image, ImageOps, UnidentifiedImageError

from app.errors import VaariError

MAX_PIXELS = 40_000_000  # about 7700 x 5200: larger than any phone camera; stops decompression bombs
JPEG_QUALITY = 88


def _invalid(message: str) -> VaariError:
    return VaariError(
        error_code="VALIDATION_ERROR",
        message=message,
        http_status=422,
        details={"field": "photo"},
    )


def sanitize_image(raw: bytes) -> bytes:
    """Return clean JPEG bytes for an uploaded JPEG, PNG or WebP. Raises 422 on a bad image."""
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(raw)) as img:
            if img.width * img.height > MAX_PIXELS:
                raise _invalid("Image is too large in pixels.")
            img.load()
            upright = ImageOps.exif_transpose(img)
            if upright.mode in ("RGBA", "LA", "PA") or (upright.mode == "P" and "transparency" in upright.info):
                rgba = upright.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.getchannel("A"))
                clean = background
            else:
                clean = upright.convert("RGB")
            # A fresh image object carries no info dict, so nothing from the original is written.
            out_img = Image.new("RGB", clean.size)
            out_img.paste(clean)
    except VaariError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError) as exc:
        raise _invalid("Uploaded file is not a readable image.") from exc

    buf = io.BytesIO()
    out_img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=False, progressive=False)
    return buf.getvalue()
