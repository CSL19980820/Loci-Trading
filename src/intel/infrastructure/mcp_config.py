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

from copy import deepcopy
import json
import os
import re
from pathlib import Path
from typing import Any

from src.shared.paths import mcp_json_path

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


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
    target = Path(path) if path else mcp_json_path()
    if not target.is_file():
        return {"mcpServers": {}}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"mcpServers": {}}
    if not isinstance(raw, dict):
        return {"mcpServers": {}}
    if "mcpServers" not in raw and "mcp_servers" not in raw:
        raw = {**raw, "mcpServers": {}}
    return raw


def load_mcp_json(path: Path | str | None = None) -> dict[str, Any]:
    """读取 mcp.json，返回展开环境变量后的对象。"""
    return _expand_obj(load_mcp_json_raw(path))


def write_mcp_json(data: dict[str, Any], path: Path | str | None = None) -> Path:
    """原子写回 mcp.json。"""
    target = Path(path) if path else mcp_json_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    if "mcpServers" not in payload and "mcp_servers" in payload:
        payload["mcpServers"] = payload.pop("mcp_servers")
    if "mcpServers" not in payload:
        payload["mcpServers"] = {}
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(target)
    return target


def _servers_map(data: dict[str, Any]) -> dict[str, Any]:
    servers = data.get("mcpServers") or data.get("mcp_servers") or {}
    return servers if isinstance(servers, dict) else {}


def _extract_token(cfg: dict[str, Any]) -> str:
    headers = cfg.get("headers") or {}
    if isinstance(headers, dict):
        auth = str(headers.get("Authorization") or headers.get("authorization") or "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        if headers.get("X-API-Key"):
            return str(headers["X-API-Key"])
    if cfg.get("token"):
        return str(cfg["token"])
    return ""


def _row_from_cfg(name: str, cfg: dict[str, Any]) -> dict[str, Any]:
    url = str(cfg.get("url") or cfg.get("serverUrl") or "").strip().rstrip("/")
    token = _extract_token(cfg)
    headers = cfg.get("headers") if isinstance(cfg.get("headers"), dict) else {}
    return {
        "id": f"JSON-{name}",
        "name": str(name),
        "url": url,
        "token": token,
        "token_last4": f"****{token[-4:]}" if len(token) >= 4 else (token or ""),
        "has_token": bool(token),
        "proxy_url": str(cfg.get("proxy_url") or cfg.get("proxy") or ""),
        "tools": cfg.get("tools") or [],
        "tools_synced_at": str(cfg.get("tools_synced_at") or ""),
        "is_active": bool(cfg.get("disabled") is not True),
        "note": str(cfg.get("note") or "mcp.json"),
        "source": "mcp.json",
        "headers": headers,
        "raw": deepcopy(cfg),
    }


def list_mcp_servers_from_json(path: Path | str | None = None) -> list[dict[str, Any]]:
    """把 mcp.json 转成运维页 / Agent 可用的字典列表（HTTP URL 条目）。"""
    data = load_mcp_json(path)
    rows: list[dict[str, Any]] = []
    for name, cfg in _servers_map(data).items():
        if not isinstance(cfg, dict):
            continue
        row = _row_from_cfg(str(name), cfg)
        if not row["url"]:
            # stdio 型先跳过（应用客户端当前只吃 HTTP）
            continue
        rows.append(row)
    return rows


def get_mcp_server_from_json(
    name_or_id: str, path: Path | str | None = None
) -> dict[str, Any] | None:
    for row in list_mcp_servers_from_json(path):
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
    data = load_mcp_json_raw(path)
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
        token = token.strip()
        headers = dict(cfg.get("headers") or {}) if isinstance(cfg.get("headers"), dict) else {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        else:
            headers.pop("Authorization", None)
            headers.pop("authorization", None)
        if headers:
            cfg["headers"] = headers
        else:
            cfg.pop("headers", None)
        cfg.pop("token", None)

    servers[name] = cfg
    data["mcpServers"] = servers
    data.pop("mcp_servers", None)
    write_mcp_json(data, path)
    row = get_mcp_server_from_json(name, path)
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
    data = load_mcp_json_raw(path)
    servers = dict(_servers_map(data))
    cfg = servers.get(name)
    if not isinstance(cfg, dict):
        raise KeyError(name)
    cfg = dict(cfg)
    cfg["tools"] = tools
    cfg["tools_synced_at"] = tools_synced_at
    servers[name] = cfg
    data["mcpServers"] = servers
    write_mcp_json(data, path)
    row = get_mcp_server_from_json(name, path)
    if row is None:
        raise KeyError(name)
    return row


def set_mcp_server_active_json(
    name: str, active: bool, *, path: Path | str | None = None
) -> dict[str, Any]:
    data = load_mcp_json_raw(path)
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
    write_mcp_json(data, path)
    row = get_mcp_server_from_json(name, path)
    if row is None:
        raise KeyError(name)
    return row


def delete_mcp_server_json(name: str, *, path: Path | str | None = None) -> bool:
    data = load_mcp_json_raw(path)
    servers = dict(_servers_map(data))
    if name not in servers:
        return False
    del servers[name]
    data["mcpServers"] = servers
    write_mcp_json(data, path)
    return True
