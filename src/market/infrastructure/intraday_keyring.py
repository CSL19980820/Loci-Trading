"""盘中留存带的数据密钥（DEK）管理。

威胁模型（写清楚，否则又是一次自欺）：

- **防**：设备失窃、硬盘被拆、未加密备份泄露、误发云盘、分享包误带盘中数据。
- **不防**：本机已登录用户的任意进程、内存 dump、有管理员权限的攻击者。

为什么这次不会重蹈 ``.palace_ai_master_key`` 的覆辙（见 ADR-014）：

1. 那次是**主密钥明文躺在被加密数据旁边**，等于没加密。这次 DEK 经 Windows DPAPI
   （``CryptProtectData`` + entropy）包裹，与密文**不在同一爆炸半径**。
2. 那次加密的是 LLM Key，解不开**功能直接不可用**，于是被迫回退明文。这次加密的是
   **可重建/可丢弃的盘中缓存**，解不开最坏是丢 60 天快照，不阻断任何主体功能。

非 Windows（容器部署）没有 DPAPI。此时**不假装加密**：明确降级为不加密并如实标注
``protection="none"``，由调用方决定要不要继续。悄悄用一个明文 keyfile 冒充加密，
比不加密更危险。
"""
from __future__ import annotations

import base64
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

#: DPAPI 的 entropy。换值等于让旧密文永久不可读，因此它必须是常量。
DPAPI_ENTROPY = b"loci-intraday-archive-v1"

#: AES-256。DuckDB 的 ``add_parquet_key`` 接受 16 / 24 / 32 字节。
KEY_BYTES = 32

#: DEK 文件名。放在留存带根目录下，随目录一起被分享包排除。
KEY_FILENAME = ".dek"


class KeyringError(RuntimeError):
    """DEK 无法建立或读取。"""


@dataclass(frozen=True)
class KeyMaterial:
    """一次取密钥的结果。``key`` 为 ``None`` 表示本机不具备加密条件。"""

    key: bytes | None
    protection: str
    detail: str

    @property
    def encrypted(self) -> bool:
        return self.key is not None

    def base64_key(self) -> str:
        if self.key is None:
            raise KeyringError("当前没有可用密钥，不能取 base64")
        return base64.b64encode(self.key).decode("ascii")

    def describe(self) -> dict[str, object]:
        return {
            "encrypted": self.encrypted,
            "protection": self.protection,
            "detail": self.detail,
        }


def _dpapi():
    """返回 win32crypt 模块；不可用时返回 None（不抛，调用方要如实降级）。"""
    try:
        import win32crypt
    except Exception:
        return None
    return win32crypt


def dpapi_available() -> bool:
    return _dpapi() is not None


def _wrap(raw: bytes) -> bytes:
    crypt = _dpapi()
    if crypt is None:
        raise KeyringError("本机没有 DPAPI，不能包裹 DEK")
    return bytes(crypt.CryptProtectData(raw, "loci-intraday", DPAPI_ENTROPY, None, None, 0))


def _unwrap(blob: bytes) -> bytes:
    crypt = _dpapi()
    if crypt is None:
        raise KeyringError("本机没有 DPAPI，不能解开 DEK")
    try:
        return bytes(crypt.CryptUnprotectData(blob, DPAPI_ENTROPY, None, None, 0)[1])
    except Exception as exc:
        raise KeyringError(
            "DEK 解不开：DPAPI 按「当前 Windows 用户」加密，换用户或换机器就读不了。"
            "已加密的历史快照将无法读取，只能删掉重新开始积累。"
        ) from exc


def load_or_create_key(root: Path, *, allow_plaintext: bool = True) -> KeyMaterial:
    """取留存带的 DEK；不存在就生成一把并用 DPAPI 包好落盘。

    ``allow_plaintext=False`` 时，没有 DPAPI 直接抛错而不是降级——给「宁可不落盘也
    不要明文」的调用方用。
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / KEY_FILENAME
    if not dpapi_available():
        if not allow_plaintext:
            raise KeyringError("本机没有 DPAPI，且调用方拒绝明文留存")
        return KeyMaterial(
            key=None,
            protection="none",
            detail="本机没有 DPAPI（非 Windows 或缺 pywin32）：快照将以明文落盘",
        )
    if path.exists():
        blob = path.read_bytes()
        if not blob:
            raise KeyringError(f"DEK 文件为空：{path}（删掉它会让已有密文永久不可读）")
        return KeyMaterial(key=_unwrap(blob), protection="dpapi", detail=str(path))
    raw = secrets.token_bytes(KEY_BYTES)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(_wrap(raw))
    os.replace(tmp, path)
    return KeyMaterial(key=raw, protection="dpapi", detail=f"新建 DEK：{path}")


__all__ = [
    "DPAPI_ENTROPY",
    "KEY_BYTES",
    "KEY_FILENAME",
    "KeyMaterial",
    "KeyringError",
    "dpapi_available",
    "load_or_create_key",
]
