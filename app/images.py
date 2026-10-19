"""Image work with Pillow: page edits, upload cleanup, thumbnails and PDFs.

Everything takes and returns bytes, so `storage.py` stays in charge of where
they live and of encryption.

A page's edits are a recipe applied to the page as uploaded, never to the
result of a previous edit, so quality doesn't drop with each one:

    {"rotate": 90, "crop": {"x": .1, "y": .05, "w": .8, "h": .9},
     "filter": "scan", "reduce": true, "format": "pdf"}

Each key is optional and left out when it does nothing. `rotate` is clockwise
degrees and comes first; `crop` is a fraction of the rotated image, so it
doesn't depend on the size of the preview it was drawn on. Images are always
turned upright by their EXIF orientation before anything else, the same way
browsers show them."""

import io
from typing import List, Optional, Tuple

from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PyPdfError

# What the editor can open (and so render, thumbnail and convert).
READABLE_MIMES = {
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/avif", "image/tiff", "image/bmp",
}
# Pillow format a page is saved in when its edits keep the original format.
# Anything else (BMP) becomes PNG.
_SAVE_FORMATS = {
    "image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP", "image/gif": "GIF",
    "image/avif": "AVIF", "image/tiff": "TIFF",
}
FORMATS = {"png": "image/png", "pdf": "application/pdf"}
ROTATIONS = (0, 90, 180, 270)
FILTERS = ("scan",)

REDUCED_SIDE = 2000  # longest side after "reduce"
PREVIEW_SIDE = 2048  # what the editor draws the crop box on
THUMB_SIDE = 400  # grid cards are 90 px tall; this stays sharp on dense screens
A4_LONG_SIDE_INCHES = 11.69
JPEG_QUALITY = 90

# Uploads only these get cleaned up: what cameras and phones produce.
_UPLOAD_MIMES = {"image/jpeg", "image/png", "image/webp"}
_ORIENTATION_TAG = 0x0112


class ImageError(Exception):
    """The content can't be read as the image (or PDF) it claims to be."""


def is_readable(mime: str) -> bool:
    return mime in READABLE_MIMES


def _open(content: bytes, draft_side: Optional[int] = None) -> Image.Image:
    """The image upright (EXIF orientation applied) and fully loaded. With
    `draft_side`, a JPEG may be decoded at a reduced scale (much faster) as
    long as it stays at least that big."""
    try:
        im = Image.open(io.BytesIO(content))
        if draft_side:
            im.draft("RGB", (draft_side, draft_side))
        im.load()
        return ImageOps.exif_transpose(im)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageError(str(exc)) from exc


# --- edits ---------------------------------------------------------------------------


def check_edits(edits: dict) -> dict:
    """The edits normalized, with every key that does nothing left out. Raises
    ValueError when something is out of range."""
    edits = edits or {}
    result = {}
    rotate = edits.get("rotate") or 0
    if rotate not in ROTATIONS:
        raise ValueError("rotate")
    if rotate:
        result["rotate"] = rotate
    crop = edits.get("crop")
    if crop:
        try:
            box = {key: float(crop[key]) for key in ("x", "y", "w", "h")}
        except (KeyError, TypeError, ValueError):
            raise ValueError("crop")
        x, y, w, h = box["x"], box["y"], box["w"], box["h"]
        if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1.0001 and 0 < h <= 1.0001):
            raise ValueError("crop")
        # A box covering (almost) everything is no crop at all.
        if x > 0.001 or y > 0.001 or w < 0.999 or h < 0.999:
            result["crop"] = {key: round(value, 5) for key, value in box.items()}
    if edits.get("filter"):
        if edits["filter"] not in FILTERS:
            raise ValueError("filter")
        result["filter"] = edits["filter"]
    if edits.get("reduce"):
        result["reduce"] = True
    if edits.get("format"):
        if edits["format"] not in FORMATS:
            raise ValueError("format")
        result["format"] = edits["format"]
    return result


def _apply(im: Image.Image, edits: dict) -> Image.Image:
    """Rotation, crop and filter: everything but size and format."""
    if edits.get("rotate"):
        im = im.rotate(-edits["rotate"], expand=True)  # Pillow turns counterclockwise
    crop = edits.get("crop")
    if crop:
        width, height = im.size
        left = min(width - 1, round(crop["x"] * width))
        top = min(height - 1, round(crop["y"] * height))
        right = max(left + 1, min(width, round((crop["x"] + crop["w"]) * width)))
        bottom = max(top + 1, min(height, round((crop["y"] + crop["h"]) * height)))
        im = im.crop((left, top, right, bottom))
    if edits.get("filter") == "scan":
        # A photo of paper: drop the color cast and stretch the contrast, so the
        # page looks white and the ink black.
        im = ImageOps.autocontrast(ImageOps.grayscale(_flatten(im)), cutoff=1)
    return im


def output_mime(source_mime: str, edits: dict) -> str:
    if edits.get("format"):
        return FORMATS[edits["format"]]
    return source_mime if source_mime in _SAVE_FORMATS else "image/png"


def render(source: bytes, source_mime: str, edits: dict) -> Tuple[bytes, str]:
    """The page as its edits make it: (content, mime)."""
    im = _apply(_open(source), edits)
    if edits.get("reduce"):
        im.thumbnail((REDUCED_SIDE, REDUCED_SIDE))
    mime = output_mime(source_mime, edits)
    return encode(im, mime), mime


# --- encoding ----------------------------------------------------------------------------


def _flatten(im: Image.Image) -> Image.Image:
    """RGB or grayscale, transparency composited onto white (for JPEG and PDF)."""
    if im.mode in ("RGB", "L"):
        return im
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return im.convert("RGB")


def encode(im: Image.Image, mime: str) -> bytes:
    if mime == "application/pdf":
        return images_to_pdf([im])
    fmt = _SAVE_FORMATS[mime]
    options = {}
    icc = im.info.get("icc_profile")
    if icc and fmt in ("JPEG", "PNG", "WEBP", "AVIF", "TIFF"):
        options["icc_profile"] = icc
    if fmt == "JPEG":
        im = _flatten(im)
        options.update(quality=JPEG_QUALITY, optimize=True)
    elif fmt in ("WEBP", "AVIF"):
        options["quality"] = JPEG_QUALITY
    elif fmt == "GIF" and im.mode not in ("P", "L"):
        im = im.convert("RGB").quantize()
    buf = io.BytesIO()
    im.save(buf, fmt, **options)
    return buf.getvalue()


def images_to_pdf(images: List[Image.Image]) -> bytes:
    """One page per image, each sized so its long side is an A4 page's."""
    writer = PdfWriter()
    for im in images:
        im = _flatten(im)
        buf = io.BytesIO()
        im.save(buf, "PDF", resolution=max(im.size) / A4_LONG_SIDE_INCHES)
        writer.append(PdfReader(io.BytesIO(buf.getvalue())))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# --- derived images ---------------------------------------------------------------------------


def preview(source: bytes) -> Tuple[bytes, str]:
    """What the editor draws on: upright, at most PREVIEW_SIDE, in a format every
    browser shows. Edits aren't applied: the editor applies them itself."""
    im = _open(source, draft_side=PREVIEW_SIDE)
    im.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE))
    if im.mode in ("RGBA", "LA", "PA", "P"):
        return encode(im, "image/png"), "image/png"
    return encode(im, "image/jpeg"), "image/jpeg"


def thumbnail(source: bytes, edits: dict) -> bytes:
    """A small WebP of the page as edited, for the document grid."""
    # A crop is a fraction of the full image, so decoding it smaller is fine:
    # leave room for the crop to still come out THUMB_SIDE wide.
    im = _open(source, draft_side=THUMB_SIDE * 2 if not edits.get("crop") else None)
    im = _apply(im, edits)
    im.thumbnail((THUMB_SIDE, THUMB_SIDE))
    if im.mode not in ("RGB", "RGBA", "L", "LA"):
        im = im.convert("RGBA")
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=80)
    return buf.getvalue()


def document_pdf(pages: List[Tuple[bytes, str]]) -> bytes:
    """One PDF from a document's pages: PDFs are merged as they are, images
    become one page each. Raises ImageError for anything else."""
    writer = PdfWriter()
    try:
        for content, mime in pages:
            if mime != "application/pdf":
                if not is_readable(mime):
                    raise ImageError(mime)
                content = images_to_pdf([_open(content)])
            writer.append(PdfReader(io.BytesIO(content)))
        out = io.BytesIO()
        writer.write(out)
    except PyPdfError as exc:
        raise ImageError(str(exc)) from exc
    return out.getvalue()


# --- uploads -------------------------------------------------------------------------------------


def strip_jpeg_metadata(data: bytes) -> bytes:
    """The JPEG without its EXIF/XMP (APP1), IPTC (APP13) and comment segments,
    without decoding it: the image data is copied as is, so nothing is lost.
    JFIF, the color profile (APP2) and Adobe's color transform (APP14) stay.
    Returns `data` untouched if it doesn't parse."""
    if not data.startswith(b"\xff\xd8"):
        return data
    out = [b"\xff\xd8"]
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            return data
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker == 0xDA:  # start of scan: the rest is image data
            out.append(data[i:])
            return b"".join(out)
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if length < 2 or i + 2 + length > len(data):
            return data
        if marker not in (0xE1, 0xED, 0xFE):
            out.append(data[i:i + 2 + length])
        i += 2 + length
    return data


def prepare_upload(content: bytes, mime: str, strip_metadata: bool, reduce: bool) -> bytes:
    """An uploaded photo made ready to keep: turned upright by its EXIF
    orientation (so it shows the right way up everywhere, not just in
    browsers), without metadata such as GPS position when `strip_metadata`, and
    no bigger than REDUCED_SIDE when `reduce`. Re-encodes only when the pixels
    have to change; a JPEG that only loses its metadata is copied losslessly.
    Anything that isn't a readable photo comes back untouched."""
    if mime not in _UPLOAD_MIMES:
        return content
    try:
        with Image.open(io.BytesIO(content)) as probe:
            exif = probe.getexif()
            orientation = exif.get(_ORIENTATION_TAG, 1)
            size = probe.size
            has_metadata = bool(exif) or any(
                key in probe.info for key in ("exif", "xmp", "XML:com.adobe.xmp", "comment")
            ) or (probe.format == "PNG" and bool(getattr(probe, "text", None)))
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return content

    rotated = orientation not in (0, 1)
    too_big = reduce and max(size) > REDUCED_SIDE
    if not rotated and not too_big:
        if not strip_metadata or not has_metadata:
            return content
        if mime == "image/jpeg":
            return strip_jpeg_metadata(content)
    try:
        im = _open(content)
    except ImageError:
        return content
    if too_big:
        im.thumbnail((REDUCED_SIDE, REDUCED_SIDE))
    options = {}
    if not strip_metadata:
        exif = im.getexif()  # exif_transpose already dropped the orientation tag
        if exif:
            options["exif"] = exif.tobytes()
    fmt = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}[mime]
    if im.info.get("icc_profile"):
        options["icc_profile"] = im.info["icc_profile"]
    if fmt == "JPEG":
        im = _flatten(im)
        options.update(quality=JPEG_QUALITY, optimize=True)
    elif fmt == "WEBP":
        options["quality"] = JPEG_QUALITY
    buf = io.BytesIO()
    im.save(buf, fmt, **options)
    return buf.getvalue()
