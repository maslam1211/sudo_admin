"""Upload rules for ad images (banner, marquee, popup).

The server enforces format, file size and minimum dimensions. The aspect ratio
is a recommendation: the admin page shows a fit preview and warns when an image
will be cropped, but the upload is still allowed.

manage_ads.html reads AD_IMAGE_RULES through json_script, so the browser check
and the server check always use the same numbers. Change them here only.
"""

from __future__ import annotations

from typing import Optional

from PIL import Image, UnidentifiedImageError

MB = 1024 * 1024

ALLOWED_FORMATS = {
    'JPEG': 'JPG',
    'PNG': 'PNG',
    'GIF': 'GIF',
    'WEBP': 'WEBP',
}

AD_IMAGE_RULES = {
    'banner': {
        'label': 'Banner',
        'width': 1200,
        'height': 600,
        'min_width': 800,
        'min_height': 400,
        'max_bytes': 5 * MB,
    },
    'marquee': {
        'label': 'Marquee',
        'width': 1200,
        'height': 300,
        'min_width': 600,
        'min_height': 150,
        'max_bytes': 5 * MB,
    },
    'popup': {
        'label': 'Popup',
        'width': 1080,
        'height': 1350,
        'min_width': 600,
        'min_height': 750,
        'max_bytes': 5 * MB,
    },
}

# How far (as a fraction) the image's ratio may differ from the recommended
# ratio before the page warns that the app will crop it.
RATIO_TOLERANCE = 0.08


def rules_for_browser() -> dict:
    return {
        'types': AD_IMAGE_RULES,
        'formats': sorted(ALLOWED_FORMATS.values()),
        'ratio_tolerance': RATIO_TOLERANCE,
    }


def _size_text(num_bytes: int) -> str:
    return f'{num_bytes / MB:.1f} MB'


def validate_ad_image(ad_type: str, upload) -> Optional[str]:
    """Return an error message for an uploaded image, or None if it is fine."""
    rules = AD_IMAGE_RULES.get(ad_type)
    if rules is None:
        return 'Unknown ad type.'

    size = int(getattr(upload, 'size', 0) or 0)
    if size <= 0:
        return 'The image file is empty.'
    if size > rules['max_bytes']:
        return (
            f"The image is {_size_text(size)}. {rules['label']} images must be "
            f"{_size_text(rules['max_bytes'])} or smaller."
        )

    try:
        upload.seek(0)
        with Image.open(upload) as img:
            fmt = (img.format or '').upper()
            width, height = img.size
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        return 'This file is not a readable image. Use JPG, PNG, GIF or WEBP.'
    finally:
        upload.seek(0)

    if fmt not in ALLOWED_FORMATS:
        return f'{fmt or "This"} images are not supported. Use JPG, PNG, GIF or WEBP.'

    if width < rules['min_width'] or height < rules['min_height']:
        return (
            f"The image is {width}×{height}px, which is too small and will look blurry. "
            f"{rules['label']} images need at least {rules['min_width']}×{rules['min_height']}px "
            f"(recommended {rules['width']}×{rules['height']}px)."
        )
    return None
