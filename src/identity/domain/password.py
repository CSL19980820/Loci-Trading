"""口令哈希：优先 Argon2id，缺依赖时回退标准库 scrypt。

为什么允许回退而不是硬依赖 ``argon2-cffi``：本仓有 PyInstaller 桌面分发形态，
多一个 C 扩展就多一份打包风险；而 ``hashlib.scrypt`` 是 CPython 自带、
RFC 7914 标准、内存硬（memory-hard），拿来做口令哈希是合格的。
装了 argon2-cffi 就自动升档，不用改代码。

产出的是 **PHC 风格自描述串**：``$algo$参数$salt$hash``。换算法不需要迁移，
旧串按自己的算法校验，登录成功时如果发现算法不是当前首选，就地重哈希。

绝不做的三件事：

1. 不截断口令（bcrypt 的 72 字节坑）；
2. 不加 pepper（单机/小规模部署收益低，密钥轮换的运维债很高）；
3. 校验失败不区分「用户不存在」与「口令错」——见 ``verify_dummy``。
"""
from __future__ import annotations

from hmac import compare_digest
import base64
import hashlib
import os

#: scrypt 参数。n=2**15 / r=8 / p=1 ≈ 32 MiB 内存、单次约 60-120ms，
#: 落在 OWASP「一次哈希 < 1 秒」的建议区间内，且不至于让并发登录打爆内存。
_SCRYPT_N = 1 << 15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_LEN = 32
_SALT_BYTES = 16

_ARGON2_ID = "argon2id"
_SCRYPT_ID = "scrypt"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(raw: str) -> bytes:
    return base64.b64decode(raw.encode("ascii"))


def _argon2_hasher():
    """拿到 argon2-cffi 的 PasswordHasher；未安装返回 None。"""
    try:
        from argon2 import PasswordHasher
        from argon2.profiles import RFC_9106_LOW_MEMORY
    except ImportError:
        return None
    return PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY)


def preferred_algo() -> str:
    return _ARGON2_ID if _argon2_hasher() is not None else _SCRYPT_ID


def hash_password(password: str) -> str:
    """返回自描述哈希串。调用方只需原样落库。"""
    if not password:
        raise ValueError("空口令不可哈希")
    hasher = _argon2_hasher()
    if hasher is not None:
        return hasher.hash(password)
    salt = os.urandom(_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_LEN,
        maxmem=_SCRYPT_N * _SCRYPT_R * 256,
    )
    params = f"n={_SCRYPT_N},r={_SCRYPT_R},p={_SCRYPT_P}"
    return f"${_SCRYPT_ID}${params}${_b64(salt)}${_b64(derived)}"


def _verify_scrypt(password: str, encoded: str) -> bool:
    parts = encoded.split("$")
    if len(parts) != 5:
        return False
    _, _algo, params, salt_b64, hash_b64 = parts
    try:
        parsed = dict(item.split("=", 1) for item in params.split(","))
        salt = _unb64(salt_b64)
        expected = _unb64(hash_b64)
        n = int(parsed["n"])
        r = int(parsed["r"])
        p = int(parsed["p"])
    except (ValueError, KeyError):
        return False
    try:
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
            maxmem=n * r * 256,
        )
    except ValueError:
        return False
    return compare_digest(derived, expected)


def verify_password(password: str, encoded: str | None) -> bool:
    """校验口令。``encoded`` 为空返回 False，但**调用方仍应先跑 dummy**。"""
    if not encoded or not password:
        return False
    if encoded.startswith("$argon2"):
        hasher = _argon2_hasher()
        if hasher is None:
            # 库被卸了但库里还是 argon2 串：宁可拒绝登录，也不能放行。
            return False
        try:
            return bool(hasher.verify(encoded, password))
        except Exception:
            return False
    if encoded.startswith(f"${_SCRYPT_ID}$"):
        return _verify_scrypt(password, encoded)
    return False


def needs_rehash(encoded: str | None) -> bool:
    """当前串是否该在下次登录成功时升档。"""
    if not encoded:
        return False
    hasher = _argon2_hasher()
    if hasher is not None:
        if not encoded.startswith("$argon2"):
            return True
        try:
            return bool(hasher.check_needs_rehash(encoded))
        except Exception:
            return False
    return False


_DUMMY_HASH: str | None = None


def verify_dummy(password: str) -> bool:
    """账号不存在时也跑一次同参数哈希，抹平时序侧信道。

        不这么做的话，「不存在的邮箱」会比「存在但口令错」快一个数量级，
        攻击者拿秒表就能枚举出全部注册邮箱。
        """
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("loci-timing-equalizer-0000")
    verify_password(password or "x", _DUMMY_HASH)
    return False


def algo_of(encoded: str | None) -> str:
    if not encoded:
        return ""
    if encoded.startswith("$argon2"):
        return _ARGON2_ID
    if encoded.startswith(f"${_SCRYPT_ID}$"):
        return _SCRYPT_ID
    return "unknown"
