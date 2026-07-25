"""Decode and sanitize user-supplied still images before object storage."""

from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

_MEDIA_FORMATS = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}
_MIN_SIDE = 64
_MAX_SIDE = 8192


@dataclass(frozen=True)
class SanitizedSubmissionImage:
    data: bytes
    media_type: str
    extension: str
    sha256: str
    width: int
    height: int

    @property
    def size(self) -> int:
        return len(self.data)


def sanitize_submission_image(
    data: bytes,
    *,
    declared_media_type: str,
    max_input_bytes: int,
    max_pixels: int,
) -> SanitizedSubmissionImage:
    """Return a metadata-free still image in PNG or JPEG form.

    SVG, GIF, animated WebP, embedded executable content and EXIF metadata are not
    preserved. The output is a newly encoded raster image rather than the uploaded
    byte stream.
    """

    media_type = declared_media_type.strip().lower()
    expected_format = _MEDIA_FORMATS.get(media_type)
    if expected_format is None:
        raise ValueError("只支持 JPEG、PNG 或 WebP 宠物图片")
    if not data:
        raise ValueError("宠物图片不能为空")
    if len(data) > max_input_bytes:
        raise ValueError("宠物图片大小超过限制")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as probe:
                source_format = str(probe.format or "").upper()
                if source_format != expected_format:
                    raise ValueError("图片声明类型与实际格式不一致")
                if int(getattr(probe, "n_frames", 1)) != 1:
                    raise ValueError("暂不支持动画图片")
                probe.verify()

            with Image.open(BytesIO(data)) as source:
                source.load()
                image = ImageOps.exif_transpose(source)
                width, height = image.size
                if width < _MIN_SIDE or height < _MIN_SIDE:
                    raise ValueError(f"图片宽高不能小于 {_MIN_SIDE} 像素")
                if width > _MAX_SIDE or height > _MAX_SIDE:
                    raise ValueError(f"图片宽高不能超过 {_MAX_SIDE} 像素")
                if width * height > max_pixels:
                    raise ValueError("图片像素总量超过限制")

                has_alpha = image.mode in {"RGBA", "LA"} or (
                    image.mode == "P" and "transparency" in image.info
                )
                output = BytesIO()
                if has_alpha:
                    image.convert("RGBA").save(output, format="PNG", optimize=True)
                    output_media_type = "image/png"
                    extension = "png"
                else:
                    image.convert("RGB").save(
                        output,
                        format="JPEG",
                        quality=95,
                        optimize=True,
                        progressive=False,
                    )
                    output_media_type = "image/jpeg"
                    extension = "jpg"
    except ValueError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("图片像素规模存在安全风险") from exc
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError("宠物图片无法解码") from exc

    sanitized = output.getvalue()
    if not sanitized:
        raise ValueError("宠物图片编码失败")
    if len(sanitized) > max_input_bytes:
        raise ValueError("清理后的宠物图片大小超过限制")
    return SanitizedSubmissionImage(
        data=sanitized,
        media_type=output_media_type,
        extension=extension,
        sha256=hashlib.sha256(sanitized).hexdigest(),
        width=width,
        height=height,
    )
