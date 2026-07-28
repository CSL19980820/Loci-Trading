"""Loci 本地数据根目录。

默认可写状态落在「程序旁」的 ``data/``（开发 = 仓库 ``data/``，打包 = exe 同级 ``data/``）：

- ``data/palace.db``  账本
- ``data/market.db``  行情仓
- ``data/ops.db``     运维 / 任务 / AI 配置索引
- ``data/skills/``    技能包
- ``data/mcp.json``   MCP 配置

解析顺序：

1. ``PALACE_DB`` / ``PALACE_MARKET_DB`` / ``PALACE_OPS_DB`` / ``PALACE_SKILL_ROOT`` / ``PALACE_MCP_JSON``
2. 环境变量 ``LOCI_DATA_DIR``（或 ``PALACE_DATA_DIR``）
3. exe/仓库旁 ``loci.config.json`` 的 ``data_dir``
4. 默认 ``{writable_root}/data``
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any


#: 有真实日 K 回填时 market.db 远大于空壳 schema（通常 GB 级；空壳约几十 KB）
MARKET_POPULATED_BYTES = 1_000_000


def _bundle_root() -> Path:
    """只读资源根（源码树，或 PyInstaller 解包目录）。"""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    # src/shared/paths.py → 仓库根
    return Path(__file__).resolve().parent.parent.parent


def writable_root() -> Path:
    """可写根（源码树，或 exe 所在目录）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


PROJECT_ROOT = _bundle_root()


def config_path() -> Path:
    return writable_root() / "loci.config.json"


def default_data_dir() -> Path:
    return writable_root() / "data"


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_config(updates: dict[str, Any]) -> dict[str, Any]:
    """合并写入 ``loci.config.json``，返回合并后的完整配置。"""
    current = load_config()
    current.update({k: v for k, v in updates.items() if v is not None})
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(current, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return current


def market_db_size(root: Path | None = None) -> int:
    db = (root or data_dir()) / "market.db"
    try:
        return db.stat().st_size if db.is_file() else 0
    except OSError:
        return 0


def discover_data_dirs() -> list[dict[str, Any]]:
    """扫描旁路可能已有行情的目录，供首次向导「使用已有数据」。"""
    wr = writable_root()
    candidates = [
        wr / "data",
        wr.parent / "data",
    ]

    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    def add(path: Path, *, source: Path, label: str) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            return
        key = str(resolved).lower()
        if key in seen:
            return
        size = source.stat().st_size if source.is_file() else market_db_size(resolved)
        if size < MARKET_POPULATED_BYTES:
            return
        seen.add(key)
        out.append(
            {
                "path": str(resolved),
                "market_bytes": size,
                "source": str(source),
                "label": label or f"{resolved}（约 {size // (1024 * 1024)} MB）",
            }
        )

    for cand in candidates:
        add(
            cand,
            source=cand / "market.db",
            label=f"{cand}（约 {market_db_size(cand) // (1024 * 1024)} MB）"
            if market_db_size(cand) >= MARKET_POPULATED_BYTES
            else "",
        )
    return out


def data_dir() -> Path:
    raw = (
        os.environ.get("LOCI_DATA_DIR")
        or os.environ.get("PALACE_DATA_DIR")
        or ""
    ).strip()
    if raw:
        return Path(raw)
    cfg = load_config().get("data_dir")
    if isinstance(cfg, str) and cfg.strip():
        return Path(cfg.strip())
    return default_data_dir()


def palace_db() -> Path:
    raw = os.environ.get("PALACE_DB", "").strip()
    return Path(raw) if raw else data_dir() / "palace.db"


def market_db() -> Path:
    raw = os.environ.get("PALACE_MARKET_DB", "").strip()
    return Path(raw) if raw else data_dir() / "market.db"


def ops_db() -> Path:
    raw = os.environ.get("PALACE_OPS_DB", "").strip()
    return Path(raw) if raw else data_dir() / "ops.db"


def skill_root() -> Path:
    raw = os.environ.get("PALACE_SKILL_ROOT", "").strip()
    return Path(raw) if raw else data_dir() / "skills"


def skill_runs_dir() -> Path:
    return data_dir() / "skill_runs"


def mcp_json_path() -> Path:
    raw = os.environ.get("PALACE_MCP_JSON", "").strip()
    return Path(raw) if raw else data_dir() / "mcp.json"


def setup_done() -> bool:
    return bool(load_config().get("setup_done"))


def needs_setup() -> bool:
    """首次向导是否还要弹：未确认过，或配置的数据根目录已不存在。"""
    if not setup_done():
        return True
    try:
        return not data_dir().is_dir()
    except OSError:
        return True


def apply_data_dir(path: str | Path, *, mark_setup_done: bool = True) -> Path:
    """写入配置中的 data_dir（不热切当前进程已打开的库）。"""
    resolved = Path(path).expanduser().resolve()
    updates: dict[str, Any] = {"data_dir": str(resolved)}
    if mark_setup_done:
        updates["setup_done"] = True
    save_config(updates)
    return resolved


def _prepare_layout_dirs(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "skills").mkdir(parents=True, exist_ok=True)
    (root / "skill_runs").mkdir(parents=True, exist_ok=True)
    mcp_path = root / "mcp.json"
    example = PROJECT_ROOT / "mcp.json.example"
    if not mcp_path.is_file() and example.is_file():
        shutil.copy2(example, mcp_path)


def _ensure_empty_stores(root: Path) -> None:
    """在指定根下创建三库空 schema（已有库则只补 DDL，不覆盖数据）。"""
    from src.ledger import PalaceStore
    from src.market import MarketStore
    from src.ops import OpsStore

    PalaceStore(root / "palace.db").close()
    MarketStore(root / "market.db").close()
    OpsStore(root / "ops.db").close()


def initialize_data_layout(root: Path | str | None = None) -> Path:
    """创建目录树 + 三库空 schema + mcp.json 样例。

    可指定任意根（向导确认新路径时，即使当前进程仍读旧目录也可先落盘）。
    """
    target = Path(root).expanduser().resolve() if root is not None else data_dir().resolve()
    _prepare_layout_dirs(target)
    _ensure_empty_stores(target)
    return target


def ensure_data_dir() -> Path:
    """创建 ``data/`` 与 ``skills/``，并尽量补齐三库空 schema / mcp.json。

    已确认过数据目录时：缺子目录或缺库会自动补齐，不再弹窗。
    启动阶段若行情依赖未就绪，至少保证目录存在，库表延后到首次访问再建。
    """
    root = data_dir()
    _prepare_layout_dirs(root)
    try:
        _ensure_empty_stores(root)
    except Exception:
        pass
    return root
