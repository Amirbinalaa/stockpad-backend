import base64
import binascii
import re
from typing import Optional, Tuple

from django.core.files.base import ContentFile

DATA_URL_PATTERN = re.compile(
    r"^data:image/(?P<fmt>[a-zA-Z0-9+.-]+);base64,(?P<payload>.+)$",
    re.DOTALL,
)

MIME_TO_EXT = {
    "jpeg": "jpg",
    "jpg": "jpg",
    "png": "png",
    "gif": "gif",
    "webp": "webp",
}


def normalize_reset_token(token: Optional[str]) -> str:
    if not token:
        return ""
    return str(token).strip()


def normalize_reset_email(email: Optional[str]) -> str:
    if not email:
        return ""
    return str(email).strip()


def parse_data_url(data_url: str) -> Tuple[bytes, str]:
    match = DATA_URL_PATTERN.match((data_url or "").strip())
    if not match:
        raise ValueError("Invalid image data URL.")
    fmt = match.group("fmt").lower()
    ext = MIME_TO_EXT.get(fmt, fmt if len(fmt) <= 5 else "png")
    try:
        raw = base64.b64decode(match.group("payload"), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Could not decode image data.") from exc
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Image must be under 2MB.")
    return raw, ext


def content_file_from_data_url(data_url: str, name_prefix: str = "profile") -> ContentFile:
    raw, ext = parse_data_url(data_url)
    return ContentFile(raw, name=f"{name_prefix}.{ext}")
