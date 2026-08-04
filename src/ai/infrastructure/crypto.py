"""API Key 的静态加密。

主密钥来自环境变量 ``PALACE_AI_MASTER_KEY``（或本机旁路文件），密文存在
ops.db。两者永远不在同一个位置：拿到数据库文件解不开，拿到主密钥也没有密文。

本机（``PALACE_ENV!=production``）若未配置环境变量，启动时会自动在程序旁
写入 ``.palace_ai_master_key``（已 gitignore）并注入进程环境——桌面用户不必
手搓 docker-compose。生产环境仍强制显式配置，禁止静默落盘。

用 AES-256-GCM 而不是 Fernet，图的是 AAD——把密文和它所属的供应商 id
绑定。没有这层绑定，攻击者可以把 A 供应商的密文行整个搬到 B 供应商，
系统会照样解密成功，然后拿着 A 的 key 去请求 B 声明的 base_url，
等于把密钥送到攻击者指定的服务器。
"""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MASTER_KEY_ENV = "PALACE_AI_MASTER_KEY"
MASTER_KEY_FILENAME = ".palace_ai_master_key"
NONCE_BYTES = 12

logger = logging.getLogger(__name__)


class CryptoError(RuntimeError):
    """密钥配置或解密失败。消息里绝不包含任何密钥内容。"""


def generate_master_key() -> str:
    """生成一枚可直接写进 .env 的主密钥。"""
    return base64.b64encode(AESGCM.generate_key(bit_length=256)).decode("ascii")


def master_key_file_path() -> Path:
    """本机旁路主密钥文件（与 ops.db 分离：在程序根，不在 data/）。"""
    from src.shared.paths import writable_root

    return writable_root() / MASTER_KEY_FILENAME


def _is_production() -> bool:
    return (os.environ.get("PALACE_ENV") or "local").strip().lower() == "production"


def ensure_local_master_key() -> str | None:
    """本机缺省时生成/加载主密钥并写入 ``os.environ``；生产环境不自动生成。

    返回当前可用的主密钥字符串；生产且未配置时返回 ``None``。
    """
    existing = os.environ.get(MASTER_KEY_ENV, "").strip()
    if existing:
        return existing
    if _is_production():
        return None

    path = master_key_file_path()
    try:
        if path.is_file():
            raw = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
            if raw:
                os.environ[MASTER_KEY_ENV] = raw
                return raw
    except OSError:
        logger.exception("读取本机主密钥文件失败：%s", path)

    key = generate_master_key()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(key + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        logger.info("已生成本机 AI 主密钥文件 %s", path.name)
    except OSError:
        logger.exception("写入本机主密钥文件失败：%s", path)
        # 仍注入进程，本会话可用；重启后需再 ensure
    os.environ[MASTER_KEY_ENV] = key
    return key


def _missing_key_message() -> str:
    if _is_production():
        return (
            f"未配置 {MASTER_KEY_ENV}，无法保存或使用 API Key。"
            "生成方式：python -c \"from src.ai.infrastructure.crypto import generate_master_key;"
            " print(generate_master_key())\"，然后写入服务器 .env 并加进"
            " docker-compose 的 environment 块。"
        )
    return (
        f"未配置 {MASTER_KEY_ENV}，无法保存或使用 API Key。"
        f"本机可重启 Loci（将自动写入 {MASTER_KEY_FILENAME}），"
        "或手动执行：python -m cli.ops genkey"
    )


def _load_master_key(master_key: str | None = None) -> bytes:
    raw = master_key if master_key is not None else os.environ.get(MASTER_KEY_ENV, "")
    if not raw:
        raise CryptoError(_missing_key_message())
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise CryptoError(f"{MASTER_KEY_ENV} 不是合法的 base64") from exc
    if len(key) not in (16, 24, 32):
        raise CryptoError(f"{MASTER_KEY_ENV} 长度非法（需 16/24/32 字节，实际 {len(key)}）")
    return key


def encrypt_secret(plaintext: str, *, aad: str, master_key: str | None = None) -> bytes:
    """加密一枚 API Key。返回 nonce + 密文（含认证标签）。"""
    if not plaintext:
        raise CryptoError("待加密内容为空")
    key = _load_master_key(master_key)
    nonce = os.urandom(NONCE_BYTES)
    blob = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad.encode("utf-8"))
    return nonce + blob


def decrypt_secret(payload: bytes, *, aad: str, master_key: str | None = None) -> str:
    """解密。AAD 不匹配会失败——这正是防"密文搬家"的那道锁。"""
    if not payload or len(payload) <= NONCE_BYTES:
        raise CryptoError("密文损坏或为空")
    key = _load_master_key(master_key)
    nonce, blob = payload[:NONCE_BYTES], payload[NONCE_BYTES:]
    try:
        return AESGCM(key).decrypt(nonce, blob, aad.encode("utf-8")).decode("utf-8")
    except InvalidTag as exc:
        raise CryptoError(
            "解密失败：主密钥不匹配，或密文与所属供应商记录对不上。"
            "若刚轮换过主密钥，需要重新录入所有 API Key。"
        ) from exc


def mask_secret(plaintext: str) -> str:
    """给 UI 展示用的末四位。永远不回显完整密钥。"""
    tail = plaintext[-4:] if len(plaintext) >= 4 else plaintext
    return f"****{tail}"
