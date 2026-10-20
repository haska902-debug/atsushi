"""画像の読み込みと撮影日時の取得。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

try:  # iPhone の HEIC 写真に対応（任意）
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF_SUPPORTED = True
except ImportError:
    HEIF_SUPPORTED = False

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
if HEIF_SUPPORTED:
    IMAGE_EXTENSIONS |= {".heic", ".heif"}

EXIF_IFD = 0x8769
TAG_DATETIME_ORIGINAL = 36867
TAG_DATETIME_DIGITIZED = 36868
TAG_DATETIME = 306


def find_images(folder: Path, exclude: Path | None = None) -> list[Path]:
    exclude = exclude.resolve() if exclude else None
    found = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if exclude and exclude in path.resolve().parents:
            continue
        found.append(path)
    return found


def load_image(path: Path) -> Image.Image:
    """画像を開き、EXIF の回転情報を反映して返す。"""
    with Image.open(path) as img:
        img.load()
        return ImageOps.exif_transpose(img)


def _parse_exif_datetime(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, bytes):
        value = value.decode(errors="ignore")
    try:
        return datetime.strptime(str(value).strip("\x00 ")[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def taken_at(path: Path) -> datetime:
    """EXIF の撮影日時を返す。無ければファイルの更新日時を使う。"""
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            sub = exif.get_ifd(EXIF_IFD)
            for value in (
                sub.get(TAG_DATETIME_ORIGINAL),
                sub.get(TAG_DATETIME_DIGITIZED),
                exif.get(TAG_DATETIME),
            ):
                parsed = _parse_exif_datetime(value)
                if parsed:
                    return parsed
    except OSError:
        pass
    return datetime.fromtimestamp(path.stat().st_mtime)
