"""Cursor 兼容的 ``mcp.json``（唯一配置面，不再写入 ops.db）。

把文件放在 ``data/mcp.json``（或由 ``PALACE_MCP_JSON`` / loci.config 指定），
形态与 Cursor 项目级 MCP 一致。前端运维页的增删改也会回写此文件。

```json
{
  "mcpServers": {
    "wudao-a-stock": {
      "url": "https://example.com/mcp",
      "headers": { "Authorization": "Bearer ${WUDAO_API_KEY}" },
      "proxy_url": "",
      "tools": [],
      "tools_synced_at": "",
      "disabled": false,
      "note": ""
    }
  }
}
```

``${ENV}`` 会在读取用于连接时从进程环境变量展开；写回文件时保留原文。
"""
from __future__ import annotations

import base64
import binascii
from copy import deepcopy
from contextlib import contextmanager
import json
import os
import re
from pathlib import Path
import tempfile
import threading
import time
from typing import Any

from src.ai import CryptoError, decrypt_secret, encrypt_secret, mask_secret
from src.shared.paths import mcp_json_path

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_MCP_JSON_LOCK_TIMEOUT_SECONDS = 5.0
_MCP_JSON_STALE_LOCK_SECONDS = 60.0
_MCP_JSON_THREAD_LOCK = threading.RLock()


class McpConfigError(RuntimeError):
    """mcp.json 不可安全读取、写入或解密时的明确失败。"""


def _target_path(path: Path | str | None) -> Path:
    return Path(path) if path else mcp_json_path()


@contextmanager
def _mcp_json_write_lock(target: Path):
    """串行化同机进程的读改写，避免丢失另一请求刚写入的 server。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_name(f".{target.name}.lock")
    marker = f"{os.getpid()}:{threading.get_ident()}:{time.monotonic_ns()}"
    deadline = time.monotonic() + _MCP_JSON_LOCK_TIMEOUT_SECONDS

    with _MCP_JSON_THREAD_LOCK:
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                try:
                    age = time.time() - lock_path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age >= _MCP_JSON_STALE_LOCK_SECONDS:
                    try:
                        lock_path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise McpConfigError("MCP 配置正被另一进程更新，请稍后重试")
                time.sleep(0.02)
            except OSError as exc:
                raise McpConfigError("无法锁定 MCP 配置文件") from exc
        try:
            os.write(descriptor, marker.encode("ascii"))
            yield
        finally:
            os.close(descriptor)
            try:
                if lock_path.read_text(encoding="ascii") == marker:
                    lock_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass


def _expand_env(value: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), "")

    return _ENV_PATTERN.sub(repl, value)


def _expand_obj(node: Any) -> Any:
    if isinstance(node, str):
        return _expand_env(node)
    if isinstance(node, list):
        return [_expand_obj(item) for item in node]
    if isinstance(node, dict):
        return {key: _expand_obj(val) for key, val in node.items()}
    return node


def load_mcp_json_raw(path: Path | str | None = None) -> dict[str, Any]:
    """读取 mcp.json 原文（不展开环境变量），供写回合并用。"""
    target = _target_path(path)
    if not target.is_file():
        return {"mcpServers": {}}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise McpConfigError("MCP 配置文件格式错误，拒绝覆盖") from exc
    except OSError as exc:
        raise McpConfigError("MCP 配置文件无法读取") from exc
    if not isinstance(raw, dict):
        raise McpConfigError("MCP 配置文件根节点必须是对象，拒绝覆盖")
    for key in ("mcpServers", "mcp_servers"):
        if key in raw and not isinstance(raw[key], dict):
            raise McpConfigError(f"MCP 配置字段 {key} 必须是对象，拒绝覆盖")
    if "mcpServers" not in raw and "mcp_servers" not in raw:
        raw = {**raw, "mcpServers": {}}
    return raw


def load_mcp_json(path: Path | str | None = None) -> dict[str, Any]:
    """读取 mcp.json，返回展开环境变量后的对象。"""
    return _expand_obj(load_mcp_json_raw(path))


def write_mcp_json(data: dict[str, Any], path: Path | str | None = None) -> Path:
    """原子写回 mcp.json；读改写调用方必须持有 ``_mcp_json_write_lock``。"""
    target = _target_path(path)
    payload = dict(data)
    if "mcpServers" not in payload and "mcp_servers" in payload:
        payload["mcpServers"] = payload.pop("mcp_servers")
    if "mcpServers" not in payload:
        payload["mcpServers"] = {}
    tmp: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, raw_tmp = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        tmp = Path(raw_tmp)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
        tmp = None
    except (OSError, TypeError, ValueError) as exc:
        raise McpConfigError("MCP 配置文件无法写入") from exc
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
    return target


def _servers_map(data: dict[str, Any]) -> dict[str, Any]:
    servers = data.get("mcpServers") or data.get("mcp_servers") or {}
    return servers if isinstance(servers, dict) else {}


def _extract_legacy_token(cfg: dict[str, Any]) -> str:
    headers = cfg.get("headers") or {}
    if isinstance(headers, dict):
        auth = next(
            (
                str(value)
                for key, value in headers.items()
                if str(key).casefold() == "authorization"
            ),
            "",
        )
        if auth.casefold().startswith("bearer "):
            return auth[7:].strip()
        if auth:
            return ""
    if cfg.get("token"):
        return str(cfg["token"])
    return ""


def _token_aad(name: str) -> str:
    return f"mcp:{name}"


def _encrypt_token(name: str, token: str) -> str:
    try:
        encrypted = encrypt_secret(token, aad=_token_aad(name))
    except CryptoError as exc:
        raise McpConfigError("MCP 凭据无法加密") from exc
    return base64.b64encode(encrypted).decode("ascii")


def _decrypt_token(name: str, payload: str) -> str:
    try:
        encrypted = base64.b64decode(payload.encode("ascii"), validate=True)
        return decrypt_secret(encrypted, aad=_token_aad(name))
    except (UnicodeError, ValueError, binascii.Error) as exc:
        raise McpConfigError("MCP 凭据密文损坏") from exc
    except CryptoError as exc:
        raise McpConfigError("MCP 凭据无法解密") from exc


def _extract_token(name: str, cfg: dict[str, Any], *, decrypt_secrets: bool) -> str:
    encrypted = str(cfg.get("encrypted_token") or "").strip()
    if encrypted:
        return _decrypt_token(name, encrypted) if decrypt_secrets else ""
    return _extract_legacy_token(cfg)


def _mask_token(token: str) -> str:
    if not token:
        return ""
    return mask_secret(token) if len(token) > 4 else "****"


def _set_token(cfg: dict[str, Any], name: str, token: str) -> None:
    headers = dict(cfg.get("headers") or {}) if isinstance(cfg.get("headers"), dict) else {}
    for key, value in list(headers.items()):
        if str(key).casefold() == "authorization" and str(value).casefold().startswith("bearer "):
            headers.pop(key)
    if headers:
        cfg["headers"] = headers
    else:
        cfg.pop("headers", None)
    cfg.pop("token", None)
    if token:
        cfg["encrypted_token"] = _encrypt_token(name, token)
        cfg["token_last4"] = _mask_token(token)
    else:
        cfg.pop("encrypted_token", None)
        cfg.pop("token_last4", None)


def _row_from_cfg(
    name: str, cfg: dict[str, Any], *, decrypt_secrets: bool = False
) -> dict[str, Any]:
    url = str(cfg.get("url") or cfg.get("serverUrl") or "").strip().rstrip("/")
    token = _extract_token(name, cfg, decrypt_secrets=decrypt_secrets)
    headers = cfg.get("headers") if isinstance(cfg.get("headers"), dict) else {}
    return {
        "id": f"JSON-{name}",
        "name": str(name),
        "url": url,
        "token": token,
        "token_last4": str(cfg.get("token_last4") or _mask_token(token)),
        "has_token": bool(cfg.get("encrypted_token") or token or headers),
        "proxy_url": str(cfg.get("proxy_url") or cfg.get("proxy") or ""),
        "tools": cfg.get("tools") or [],
        "tools_synced_at": str(cfg.get("tools_synced_at") or ""),
        "is_active": bool(cfg.get("disabled") is not True),
        "note": str(cfg.get("note") or "mcp.json"),
        "source": "mcp.json",
        "headers": headers,
        "raw": deepcopy(cfg),
    }


def list_mcp_servers_from_json(
    path: Path | str | None = None, *, decrypt_secrets: bool = False
) -> list[dict[str, Any]]:
    """把 mcp.json 转成运维页 / Agent 可用的字典列表（HTTP URL 条目）。"""
    data = load_mcp_json(path)
    rows: list[dict[str, Any]] = []
    for name, cfg in _servers_map(data).items():
        if not isinstance(cfg, dict):
            continue
        row = _row_from_cfg(str(name), cfg, decrypt_secrets=decrypt_secrets)
        if not row["url"]:
            # stdio 型先跳过（应用客户端当前只吃 HTTP）
            continue
        rows.append(row)
    return rows


def get_mcp_server_from_json(
    name_or_id: str, path: Path | str | None = None, *, decrypt_secrets: bool = False
) -> dict[str, Any] | None:
    for row in list_mcp_servers_from_json(path, decrypt_secrets=decrypt_secrets):
        if row["name"] == name_or_id or row["id"] == name_or_id:
            return row
    return None


def upsert_mcp_server_json(
    *,
    name: str,
    url: str,
    token: str | None = None,
    proxy_url: str = "",
    note: str = "",
    tools: list[dict[str, Any]] | None = None,
    tools_synced_at: str = "",
    disabled: bool | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """新增或更新一条 MCP server，写回 mcp.json。token=None 表示保留原 headers。"""
    name = name.strip()
    target = _target_path(path)
    with _mcp_json_write_lock(target):
        data = load_mcp_json_raw(target)
        servers = dict(_servers_map(data))
        existing = servers.get(name) if isinstance(servers.get(name), dict) else {}
        cfg: dict[str, Any] = dict(existing)

        cfg["url"] = url.strip().rstrip("/")
        if proxy_url or "proxy_url" in cfg:
            cfg["proxy_url"] = proxy_url
        if note or "note" in cfg:
            cfg["note"] = note
        if tools is not None:
            cfg["tools"] = tools
        if tools_synced_at:
            cfg["tools_synced_at"] = tools_synced_at
        if disabled is not None:
            if disabled:
                cfg["disabled"] = True
            else:
                cfg.pop("disabled", None)

        if token is not None:
            _set_token(cfg, name, token.strip())
        elif "encrypted_token" not in cfg:
            legacy_token = _extract_legacy_token(cfg)
            if legacy_token and not _ENV_PATTERN.fullmatch(legacy_token):
                _set_token(cfg, name, legacy_token)

        servers[name] = cfg
        data["mcpServers"] = servers
        data.pop("mcp_servers", None)
        write_mcp_json(data, target)
    row = get_mcp_server_from_json(name, target)
    if row is None:  # pragma: no cover
        raise RuntimeError(f"写入 mcp.json 后读不到 {name}")
    return row


def update_mcp_server_tools_json(
    name: str,
    tools: list[dict[str, Any]],
    *,
    tools_synced_at: str,
    path: Path | str | None = None,
) -> dict[str, Any]:
    target = _target_path(path)
    with _mcp_json_write_lock(target):
        data = load_mcp_json_raw(target)
        servers = dict(_servers_map(data))
        cfg = servers.get(name)
        if not isinstance(cfg, dict):
            raise KeyError(name)
        cfg = dict(cfg)
        cfg["tools"] = tools
        cfg["tools_synced_at"] = tools_synced_at
        servers[name] = cfg
        data["mcpServers"] = servers
        write_mcp_json(data, target)
    row = get_mcp_server_from_json(name, target)
    if row is None:
        raise KeyError(name)
    return row


def set_mcp_server_active_json(
    name: str, active: bool, *, path: Path | str | None = None
) -> dict[str, Any]:
    target = _target_path(path)
    with _mcp_json_write_lock(target):
        data = load_mcp_json_raw(target)
        servers = dict(_servers_map(data))
        cfg = servers.get(name)
        if not isinstance(cfg, dict):
            raise KeyError(name)
        cfg = dict(cfg)
        if active:
            cfg.pop("disabled", None)
        else:
            cfg["disabled"] = True
        servers[name] = cfg
        data["mcpServers"] = servers
        write_mcp_json(data, target)
    row = get_mcp_server_from_json(name, target)
    if row is None:
        raise KeyError(name)
    return row


def delete_mcp_server_json(name: str, *, path: Path | str | None = None) -> bool:
    target = _target_path(path)
    with _mcp_json_write_lock(target):
        data = load_mcp_json_raw(target)
        servers = dict(_servers_map(data))
        if name not in servers:
            return False
        del servers[name]
        data["mcpServers"] = servers
        write_mcp_json(data, target)
        return True
