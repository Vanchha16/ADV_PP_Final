"""Validate and normalise uploaded product images."""
import io

from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "gif"}
MAX_SIDE = 1200


class ImageError(ValueError):
    pass


def process_upload(file_storage):
    """Return (bytes, mime) of a resized JPEG, or raise ImageError."""
    name = (file_storage.filename or "").lower()
    if "." not in name or name.rsplit(".", 1)[1] not in ALLOWED_EXT:
        raise ImageError("Image must be PNG, JPG, WEBP or GIF.")
    try:
        img = Image.open(file_storage.stream)
        img.load()
    except (UnidentifiedImageError, OSError):
        raise ImageError("That file is not a valid image.")
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85, optimize=True)
    return out.getvalue(), "image/jpeg"
