"""Cursor 兼容的 ``mcp.json``（唯一配置面，不再写入 ops.db）。

把文件放在 ``data/mcp.json``（或由 ``PALACE_MCP_JSON`` / loci.config 指定），
形态与 Cursor 项目级 MCP 一致。前端运维页的增删改也会回写此文件。

```json
{
  "mcpServers": {
    "wudao": {
      "url": "https://example.com/mcp",
      "headers": { "Authorization": "Bearer ${WUDAO_API_KEY}" },
      "proxy_url": "",
      "tools": [],
      "tools_synced_at": "",
      "disabled": false,
      "expires_at": "2027-06-04",
      "note": ""
    }
  }
}
```

``${ENV}`` 会在读取用于连接时从进程环境变量展开；写回文件时保留原文。
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
import json
import os
import re
from pathlib import Path
import tempfile
import threading
import time
from datetime import date
from typing import Any

from src.ai import mask_secret
from src.shared.paths import mcp_json_path

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

#: 悟道 / stock.quicktiny.cn 官方 MCP 端点（付费情报补充源）
WUDAO_MCP_URL = "https://stock.quicktiny.cn/api/mcp"
#: 与 Hermes Studio / Cursor 习惯一致，全仓只认这一条名。
WUDAO_PRESET_NAME = "wudao"
#: 旧配置键；读到时迁到 ``WUDAO_PRESET_NAME``，列表里不再单独出现。
WUDAO_LEGACY_NAMES = frozenset({"wudao-a-stock", "wudao-mcp"})
WUDAO_PRESET_NOTE = (
    "悟道 A 股 · 涨停梯队/题材/龙虎榜/研报等；配额约 5000 次/天、50 次/分"
)
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


def migrate_wudao_server_name(path: Path | str | None = None) -> bool:
    """把 ``wudao-a-stock`` / ``wudao-mcp`` 合并到唯一键 ``wudao``。

    已有 ``wudao`` 时丢掉旧键（优先保留规范名下的配置）；只写盘一次。
    """
    target = _target_path(path)
    with _mcp_json_write_lock(target):
        data = load_mcp_json_raw(target)
        servers = dict(_servers_map(data))
        legacy_hits = [
            name for name in list(servers) if str(name).strip() in WUDAO_LEGACY_NAMES
        ]
        if not legacy_hits:
            return False
        canonical = WUDAO_PRESET_NAME
        if canonical not in servers:
            # 旧键里挑一份最像「已配好」的迁过去
            pick = legacy_hits[0]
            for name in legacy_hits:
                cfg = servers.get(name)
                if isinstance(cfg, dict) and (
                    cfg.get("encrypted_token") or cfg.get("headers") or cfg.get("tools")
                ):
                    pick = name
                    break
            cfg = servers.get(pick)
            if isinstance(cfg, dict):
                servers[canonical] = dict(cfg)
        for name in legacy_hits:
            servers.pop(name, None)
        data["mcpServers"] = servers
        data.pop("mcp_servers", None)
        write_mcp_json(data, target)
    return True


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


def _extract_token(name: str, cfg: dict[str, Any], *, decrypt_secrets: bool = False) -> str:
    """只读明文 token。``decrypt_secrets`` 保留兼容参数，已忽略。"""
    _ = name, decrypt_secrets
    return _extract_legacy_token(cfg).strip()


def _mask_token(token: str) -> str:
    if not token:
        return ""
    return mask_secret(token) if len(token) > 4 else "****"


def _parse_expires_at(raw: Any) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _has_configured_token(name: str, cfg: dict[str, Any], *, decrypt_secrets: bool = False) -> bool:
    _ = name, decrypt_secrets
    plain = _extract_legacy_token(cfg).strip()
    if plain and not _ENV_PATTERN.fullmatch(plain):
        return True
    headers = cfg.get("headers") if isinstance(cfg.get("headers"), dict) else {}
    auth = next(
        (
            str(value)
            for key, value in headers.items()
            if str(key).casefold() == "authorization"
        ),
        "",
    ).strip()
    if not auth:
        return False
    expanded = _expand_env(auth)
    if expanded.strip():
        return True
    for match in _ENV_PATTERN.finditer(auth):
        if os.environ.get(match.group(1), "").strip():
            return True
    return False


def assess_server_usability(
    name: str,
    cfg: dict[str, Any],
    *,
    decrypt_secrets: bool = False,
) -> dict[str, Any]:
    """判断 MCP server 是否应参与工具汇总 / 调用。

    未配 Key、仅剩旧密文、已过期或显式停用时 ``usable=False``。
    """
    _ = decrypt_secrets
    if cfg.get("disabled") is True:
        return {"usable": False, "skip_reason": "已停用"}
    plain = _extract_legacy_token(cfg).strip()
    encrypted = str(cfg.get("encrypted_token") or "").strip()
    if not plain and encrypted:
        return {
            "usable": False,
            "skip_reason": "旧加密凭据已废弃，请重新录入 API Key",
        }
    if not _has_configured_token(name, cfg):
        return {"usable": False, "skip_reason": "未配置 API Key"}
    expires = _parse_expires_at(cfg.get("expires_at"))
    if expires is not None and date.today() > expires:
        return {"usable": False, "skip_reason": f"已于 {expires.isoformat()} 过期"}
    return {"usable": True, "skip_reason": ""}


def _set_token(cfg: dict[str, Any], name: str, token: str) -> None:
    """写入 MCP API Key：明文 ``token``，并清掉旧 ``encrypted_token``。"""
    _ = name
    headers = dict(cfg.get("headers") or {}) if isinstance(cfg.get("headers"), dict) else {}
    for key, value in list(headers.items()):
        if str(key).casefold() == "authorization" and str(value).casefold().startswith("bearer "):
            headers.pop(key)
    if headers:
        cfg["headers"] = headers
    else:
        cfg.pop("headers", None)
    cfg.pop("encrypted_token", None)
    if token:
        cfg["token"] = token
        cfg["token_last4"] = _mask_token(token)
    else:
        cfg.pop("token", None)
        cfg.pop("token_last4", None)


def _row_from_cfg(
    name: str, cfg: dict[str, Any], *, decrypt_secrets: bool = False
) -> dict[str, Any]:
    url = str(cfg.get("url") or cfg.get("serverUrl") or "").strip().rstrip("/")
    token = _extract_token(name, cfg, decrypt_secrets=decrypt_secrets)
    headers = cfg.get("headers") if isinstance(cfg.get("headers"), dict) else {}
    expires_at = str(cfg.get("expires_at") or "").strip()
    usability = assess_server_usability(name, cfg, decrypt_secrets=decrypt_secrets)
    return {
        "id": f"JSON-{name}",
        "name": str(name),
        "url": url,
        "token": token,
        "token_last4": str(cfg.get("token_last4") or _mask_token(token)),
        "has_token": _has_configured_token(name, cfg, decrypt_secrets=decrypt_secrets),
        "expires_at": expires_at,
        "is_usable": bool(usability["usable"]),
        "skip_reason": str(usability["skip_reason"] or ""),
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
    key = str(name_or_id or "").strip()
    rows = list_mcp_servers_from_json(path, decrypt_secrets=decrypt_secrets)
    for row in rows:
        if row["name"] == key or row["id"] == key:
            return row
    # 悟道旧名 ↔ 规范名互认（迁移前读盘仍可用）
    wudao_keys = {WUDAO_PRESET_NAME, *WUDAO_LEGACY_NAMES}
    if key in wudao_keys:
        for row in rows:
            if row["name"] == WUDAO_PRESET_NAME:
                return row
        for row in rows:
            if row["name"] in WUDAO_LEGACY_NAMES:
                return row
    return None


def migrate_encrypted_mcp_tokens(path: Path | str | None = None) -> int:
    """丢掉旧 ``encrypted_token``（主密钥方案已废弃）；有明文则保留明文。

    返回清理条数。无明文的 server 需在运维页重录 Key。
    """
    target = _target_path(path)
    if not target.is_file():
        return 0
    changed = 0
    with _mcp_json_write_lock(target):
        data = load_mcp_json_raw(target)
        servers = dict(_servers_map(data))
        for name, raw_cfg in list(servers.items()):
            if not isinstance(raw_cfg, dict):
                continue
            cfg = dict(raw_cfg)
            if not str(cfg.get("encrypted_token") or "").strip():
                continue
            cfg.pop("encrypted_token", None)
            servers[name] = cfg
            changed += 1
        if changed:
            data["mcpServers"] = servers
            data.pop("mcp_servers", None)
            write_mcp_json(data, target)
    return changed


def upsert_mcp_server_json(
    *,
    name: str,
    url: str,
    token: str | None = None,
    proxy_url: str = "",
    note: str | None = None,
    expires_at: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tools_synced_at: str = "",
    disabled: bool | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """新增或更新一条 MCP server，写回 mcp.json。token=None 表示保留原 Key。"""
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
        if note is not None:
            cfg["note"] = note
        if expires_at is not None:
            cleaned = expires_at.strip()
            if cleaned:
                parsed = _parse_expires_at(cleaned)
                if parsed is None:
                    raise McpConfigError("expires_at 必须是 YYYY-MM-DD 格式")
                cfg["expires_at"] = parsed.isoformat()
            else:
                cfg.pop("expires_at", None)
        if tools is not None:
            cfg["tools"] = tools
        if tools_synced_at:
            cfg["tools_synced_at"] = tools_synced_at
        if disabled is not None:
            if disabled:
                cfg["disabled"] = True
            else:
                cfg.pop("disabled", None)

        # token=None：保留已有明文；顺手丢掉旧密文残留。
        if token is not None:
            _set_token(cfg, name, token.strip())
        else:
            if str(cfg.get("encrypted_token") or "").strip():
                cfg.pop("encrypted_token", None)
            if not str(cfg.get("token") or "").strip():
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
