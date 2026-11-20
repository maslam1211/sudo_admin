"""Custom sticker designs for QR generation.

An admin uploads a design image and drags a square box on it to mark where the
QR goes. The design is saved in Firestore `qr_designs` (image on Cloudinary),
and every QR generated with it is pasted into that box.

The box is stored as fractions of the image so it survives any resize:
  x, y  - top-left corner, as a fraction of image width / height
  size  - side of the square, as a fraction of image width
"""

from __future__ import annotations

import io
import logging
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import qrcode
import requests
from firebase_admin import firestore
from PIL import Image, ImageDraw, UnidentifiedImageError

logger = logging.getLogger(__name__)

COLLECTION = 'qr_designs'
MB = 1024 * 1024
MAX_UPLOAD_BYTES = 10 * MB
MIN_SIDE_PX = 600
ALLOWED_FORMATS = {'PNG', 'JPEG', 'MPO', 'WEBP'}  # MPO = JPEG saved by many phone cameras
PURPOSES = {'user': 'Vehicle sticker', 'multipurpose': 'Smart Tag'}
DEFAULT_WIDTH_MM = {'user': 100.0, 'multipurpose': 80.0}
MIN_QR_MM = 15.0  # smaller than this scans poorly from a phone


class DesignError(ValueError):
    pass


def parse_box(raw_x, raw_y, raw_size, image_w: int, image_h: int) -> Dict[str, float]:
    """Validate the dragged box and return it as fractions."""
    try:
        x, y, size = float(raw_x), float(raw_y), float(raw_size)
    except (TypeError, ValueError):
        raise DesignError('Drag the QR box onto the design first.')
    if not (0 < size <= 1):
        raise DesignError('The QR box size is not valid.')
    side_px = size * image_w
    if x < 0 or y < 0 or x * image_w + side_px > image_w + 1 or y * image_h + side_px > image_h + 1:
        raise DesignError('The QR box must sit fully inside the design.')
    return {'x': round(x, 5), 'y': round(y, 5), 'size': round(size, 5)}


def parse_width_mm(raw, purpose: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = DEFAULT_WIDTH_MM.get(purpose, 100.0)
    if not (20 <= value <= 300):
        raise DesignError('Print width must be between 20 and 300 mm.')
    return round(value, 1)


def read_design_image(upload) -> Image.Image:
    size = int(getattr(upload, 'size', 0) or 0)
    if size <= 0:
        raise DesignError('Choose a design image.')
    if size > MAX_UPLOAD_BYTES:
        raise DesignError(f'The design is {size / MB:.1f} MB. Use an image of 10 MB or less.')
    try:
        upload.seek(0)
        img = Image.open(upload)
        img.load()
    except (UnidentifiedImageError, OSError, ValueError):
        raise DesignError('This file is not a readable image. Use PNG or JPG.')
    finally:
        upload.seek(0)
    if (img.format or '').upper() not in ALLOWED_FORMATS:
        raise DesignError('Use a PNG, JPG or WEBP design.')
    img = upright(img)
    if min(img.size) < MIN_SIDE_PX:
        raise DesignError(
            f'The design is {img.size[0]}×{img.size[1]}px. Use at least {MIN_SIDE_PX}px on the short side so it prints sharp.'
        )
    return img


def upright(img):
    """Apply the EXIF rotation phones store, so pixels match what the browser showed."""
    from PIL import ImageOps
    try:
        return ImageOps.exif_transpose(img) or img
    except Exception:
        return img


def qr_side_mm(box: Dict[str, float], width_mm: float) -> float:
    return round(box['size'] * width_mm, 1)


def _design_doc(doc) -> Dict[str, Any]:
    data = doc.to_dict() or {}
    box = data.get('box') or {}
    return {
        'id': doc.id,
        'name': data.get('name') or 'Untitled design',
        'purpose': data.get('purpose') or 'user',
        'purpose_label': PURPOSES.get(data.get('purpose') or 'user', 'Vehicle sticker'),
        'image_url': data.get('imageUrl') or '',
        'image_w': int(data.get('imageWidth') or 0),
        'image_h': int(data.get('imageHeight') or 0),
        'box': {'x': float(box.get('x') or 0), 'y': float(box.get('y') or 0), 'size': float(box.get('size') or 0)},
        'width_mm': float(data.get('widthMm') or DEFAULT_WIDTH_MM.get(data.get('purpose') or 'user', 100.0)),
        'white_backing': data.get('whiteBacking', True) is not False,
        'is_default': bool(data.get('isDefault')),
    }


def list_designs(db) -> List[Dict[str, Any]]:
    try:
        docs = db.collection(COLLECTION).order_by('createdAt', direction=firestore.Query.DESCENDING).stream()
        return [_design_doc(d) for d in docs if not (d.to_dict() or {}).get('deleted')]
    except Exception as exc:
        logger.warning('qr designs list failed: %s', exc)
        return []


def get_design(db, design_id: str) -> Dict[str, Any]:
    snap = db.collection(COLLECTION).document(design_id).get()
    if not snap.exists or (snap.to_dict() or {}).get('deleted'):
        raise DesignError('That design no longer exists. Pick another one.')
    return _design_doc(snap)


def _upload_to_cloudinary(upload, design_id: str) -> str:
    import cloudinary.uploader
    upload.seek(0)
    result = cloudinary.uploader.upload(
        upload,
        folder='sudotag/qr_designs',
        public_id=design_id,
        overwrite=True,
        resource_type='image',
    )
    url = str(result.get('secure_url') or '')
    if not url:
        raise DesignError('The design could not be uploaded. Try again.')
    return url


def save_design(db, *, upload, name: str, purpose: str, box_raw: Tuple, width_mm_raw, white_backing: bool,
                admin_email: str) -> Dict[str, Any]:
    if purpose not in PURPOSES:
        raise DesignError('Pick Vehicle sticker or Smart Tag.')
    name = (name or '').strip()[:60]
    if not name:
        raise DesignError('Give the design a name.')
    img = read_design_image(upload)
    box = parse_box(*box_raw, img.size[0], img.size[1])
    width_mm = parse_width_mm(width_mm_raw, purpose)
    if qr_side_mm(box, width_mm) < MIN_QR_MM:
        raise DesignError(
            f'The QR would print at {qr_side_mm(box, width_mm)} mm. Make the box bigger (at least {MIN_QR_MM:.0f} mm) so phones can scan it.'
        )
    ref = db.collection(COLLECTION).document()
    url = _upload_to_cloudinary(upload, ref.id)
    ref.set({
        'name': name,
        'purpose': purpose,
        'imageUrl': url,
        'imageWidth': img.size[0],
        'imageHeight': img.size[1],
        'box': box,
        'widthMm': width_mm,
        'whiteBacking': bool(white_backing),
        'createdBy': admin_email or 'admin',
        'createdAt': firestore.SERVER_TIMESTAMP,
    })
    return _design_doc(ref.get())


def update_design(db, design_id: str, *, box_raw: Tuple, width_mm_raw, white_backing: bool, name: str = '') -> Dict[str, Any]:
    design = get_design(db, design_id)
    box = parse_box(*box_raw, design['image_w'] or 1000, design['image_h'] or 1000)
    width_mm = parse_width_mm(width_mm_raw, design['purpose'])
    if qr_side_mm(box, width_mm) < MIN_QR_MM:
        raise DesignError(f'The QR would print at {qr_side_mm(box, width_mm)} mm. Make the box bigger.')
    updates = {'box': box, 'widthMm': width_mm, 'whiteBacking': bool(white_backing), 'updatedAt': firestore.SERVER_TIMESTAMP}
    if (name or '').strip():
        updates['name'] = name.strip()[:60]
    db.collection(COLLECTION).document(design_id).update(updates)
    return get_design(db, design_id)


def delete_design(db, design_id: str) -> None:
    get_design(db, design_id)
    db.collection(COLLECTION).document(design_id).update({'deleted': True, 'deletedAt': firestore.SERVER_TIMESTAMP})


@lru_cache(maxsize=8)
def _fetch_image_bytes(url: str) -> bytes:
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    return resp.content


def load_design_image(design: Dict[str, Any]) -> Image.Image:
    try:
        data = _fetch_image_bytes(design['image_url'])
        return upright(Image.open(io.BytesIO(data))).convert('RGB')
    except Exception as exc:
        logger.warning('qr design image load failed: %s', exc)
        raise DesignError('Could not download the design image. Try again in a moment.')


def make_qr_modules(data: str) -> Image.Image:
    """QR with no quiet zone; the white backing in compose() provides it."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=0)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.make_image(fill_color='black', back_color='white').convert('RGB')


def compose(design_img: Image.Image, design: Dict[str, Any], qr_data: str) -> Image.Image:
    """Paste a QR for qr_data into the design's box."""
    w, h = design_img.size
    box = design['box']
    side = max(1, int(round(box['size'] * w)))
    left = int(round(box['x'] * w))
    top = int(round(box['y'] * h))
    side = min(side, w - left, h - top)

    out = design_img.copy()
    if design.get('white_backing', True):
        # A white square with a quiet zone of ~8% keeps the QR scannable on any artwork.
        ImageDraw.Draw(out).rectangle([left, top, left + side - 1, top + side - 1], fill='white')
        pad = max(2, int(side * 0.08))
    else:
        pad = 0
    inner = max(1, side - pad * 2)
    qr_img = make_qr_modules(qr_data).resize((inner, inner), Image.Resampling.NEAREST)
    out.paste(qr_img, (left + pad, top + pad))
    return out


def print_size_mm(design: Dict[str, Any], design_img: Image.Image) -> Tuple[float, float]:
    w, h = design_img.size
    width_mm = design['width_mm']
    return width_mm, round(width_mm * h / w, 2)


def dpi_for(design: Dict[str, Any], design_img: Image.Image) -> int:
    return max(72, int(round(design_img.size[0] / (design['width_mm'] / 25.4))))
