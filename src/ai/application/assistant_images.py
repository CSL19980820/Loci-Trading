"""助手用户附图校验：仅允许 data:image 小图，供多模态 LLM。"""
from __future__ import annotations

from src.ai.domain.assistant import AssistantError
from src.ai.infrastructure.client import parse_data_image

MAX_IMAGES = 4
MAX_IMAGE_CHARS = 2_500_000  # ~1.8MB 二进制


def normalize_user_images(raw: list[str] | None) -> list[str]:
    """校验并裁剪附图列表；非法格式/过大则抛 AssistantError。"""
    if not raw:
        return []
    if len(raw) > MAX_IMAGES:
        raise AssistantError(f"最多上传 {MAX_IMAGES} 张图片")
    out: list[str] = []
    for item in raw:
        url = str(item or "").strip()
        if not url:
            continue
        if not parse_data_image(url):
            raise AssistantError("图片须为 data:image/(png|jpeg|webp|gif);base64 格式")
        if len(url) > MAX_IMAGE_CHARS:
            raise AssistantError("单张图片过大，请压缩后重试")
        out.append(url)
    return out


def images_from_metadata(metadata: dict | None) -> list[str]:
    """从消息 metadata 取出已校验形状的 images（宽松：坏项跳过）。"""
    if not isinstance(metadata, dict):
        return []
    raw = metadata.get("images")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        url = str(item or "").strip()
        if url and parse_data_image(url):
            out.append(url)
        if len(out) >= MAX_IMAGES:
            break
    return out
