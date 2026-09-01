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
import logging
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

logger = logging.getLogger(__name__)


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
    """``loci.config.json`` 的位置。

    ``LOCI_CONFIG_JSON`` 覆盖用于测试隔离：这份文件里存着 ``data_dir`` 与线路
    策略，没有覆盖点时测试既会读到开发机的真实配置（结果随本机而变），也可能
    被一次忘了 mock 的 ``save_config`` 改写。
    """
    raw = os.environ.get("LOCI_CONFIG_JSON", "").strip()
    return Path(raw) if raw else writable_root() / "loci.config.json"


def default_data_dir() -> Path:
    return writable_root() / "data"


def _resolve_data_path(raw: str) -> Path:
    """解析数据目录；相对配置始终相对安装目录，而不是当前工作目录。"""
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = writable_root() / path
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _holds_unrebuildable_state(root: Path) -> bool:
    """目录里是否已有丢了就回不来的库（账本 / 运维配置）。

    ``market.db`` 不算：它是可重建缓存，大小随时可能为 0（从没同步过）。
    """
    for name in ("palace.db", "ops.db"):
        try:
            path = root / name
            if path.is_file() and path.stat().st_size > 0:
                return True
        except OSError:
            continue
    return False


def _configured_data_dir(raw: str) -> Path:
    """解析配置目录，并为移动后的便携包提供旧绝对路径兜底。"""
    configured = _resolve_data_path(raw)
    default = default_data_dir().resolve()
    if configured == default:
        return default

    # 行情库大小只能用来识别「空壳目录」，不能用来决定账本住哪：配置目录里
    # 已有 palace.db/ops.db 就说明它是用户真在用的数据根，换目录 = 账本消失。
    if _holds_unrebuildable_state(configured):
        return configured

    # loci.config.json 会随旧机器的安装目录一起被复制。若旧目录失效，或
    # 只是启动时被创建出的空目录，而 exe 旁已有完整行情库，应优先使用便携库。
    if (
        market_db_size(default) >= MARKET_POPULATED_BYTES
        and market_db_size(configured) < MARKET_POPULATED_BYTES
    ):
        return default
    if not configured.is_dir():
        return default
    return configured


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    cached = getattr(load_config, "_cache", None)
    if isinstance(cached, tuple) and cached[0] == mtime and isinstance(cached[1], dict):
        return cached[1]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    result = raw if isinstance(raw, dict) else {}
    load_config._cache = (mtime, result)  # type: ignore[attr-defined]
    return result


def save_config(updates: dict[str, Any]) -> dict[str, Any]:
    """合并写入 ``loci.config.json``，返回合并后的完整配置。"""
    current = load_config()
    current.update({k: v for k, v in updates.items() if v is not None})
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # 原地截断覆盖时若中途崩溃，会留下半截 JSON；load_config 捕获解析错误后
    # 静默返回 {}，data_dir / 线路策略 / setup_done 会一起无声重置。
    staging = path.with_name(f"{path.name}.tmp")
    staging.write_text(
        json.dumps(current, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(staging, path)
    try:
        load_config._cache = (path.stat().st_mtime, current)  # type: ignore[attr-defined]
    except OSError:
        load_config._cache = None  # type: ignore[attr-defined]
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
        return _resolve_data_path(raw)
    cfg = load_config().get("data_dir")
    if isinstance(cfg, str) and cfg.strip():
        return _configured_data_dir(cfg.strip())
    return default_data_dir().resolve()


def _tenant_dir() -> Path:
    """当前租户的私有目录。主租户就是 ``data/`` 本身，存量单机零迁移。

    多租户不是「把每张表加一列 user_id」，而是「换一个 data 根」：
    行情是公共事实（全局共享一份），账本/运维/技能/研究产物是私人事实（分库）。
    见 ``src/shared/tenancy.py`` 的取舍说明。
    """
    from src.shared.tenancy import tenant_root

    return tenant_root(data_dir())


def _tenant_scoped(env_key: str, filename: str) -> Path:
    """环境变量只对主租户生效——它表达的是「这台机器的那一份库」。

    子租户若也认这个变量，所有人会写进同一个文件，隔离当场失效。
    """
    from src.shared.tenancy import is_primary_tenant

    raw = os.environ.get(env_key, "").strip()
    if raw and is_primary_tenant():
        return Path(raw)
    return _tenant_dir() / filename


def palace_db() -> Path:
    return _tenant_scoped("PALACE_DB", "palace.db")


def market_db() -> Path:
    """行情全量库：全局共享，不随租户切换。"""
    raw = os.environ.get("PALACE_MARKET_DB", "").strip()
    return Path(raw) if raw else data_dir() / "market.db"


def market_hot_db() -> Path:
    """滚动热读库：近 N 交易日行情窗口，选股/面板只读它，与全量写库物理隔离。

    全量库被同步写时，热库读路径不受写锁影响；数据从全量库镜像派生，可随时重建。
  与 ``market_db`` 一样是全局共享资源。
    """
    raw = os.environ.get("PALACE_MARKET_HOT_DB", "").strip()
    return Path(raw) if raw else data_dir() / "market_hot.db"


def identity_db() -> Path:
    """账号 / 身份 / 会话库：跨租户全局唯一，绝不分库。"""
    raw = os.environ.get("LOCI_IDENTITY_DB", "").strip()
    return Path(raw) if raw else data_dir() / "identity.db"


def community_db() -> Path:
    """社区库（策略广场、榜单、跟单、动态）：跨租户全局唯一。"""
    raw = os.environ.get("LOCI_COMMUNITY_DB", "").strip()
    return Path(raw) if raw else data_dir() / "community.db"


def ops_db() -> Path:
    return _tenant_scoped("PALACE_OPS_DB", "ops.db")


def skill_root() -> Path:
    return _tenant_scoped("PALACE_SKILL_ROOT", "skills")


def skill_runs_dir() -> Path:
    return _tenant_dir() / "skill_runs"


def research_runs_dir() -> Path:
    """研究 run 的 JSON 产物目录；不与运维 run 或业务数据库混用。"""
    return _tenant_dir() / "research_runs"


def mcp_json_path() -> Path:
    return _tenant_scoped("PALACE_MCP_JSON", "mcp.json")


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
    try:
        relative = resolved.relative_to(writable_root().resolve())
    except (OSError, ValueError):
        config_value = str(resolved)
    else:
        # 安装目录内的状态使用相对路径，复制便携包时不会把旧盘符带走。
        config_value = relative.as_posix() or "."
    updates: dict[str, Any] = {"data_dir": config_value}
    if mark_setup_done:
        updates["setup_done"] = True
    save_config(updates)
    return resolved


def _prepare_layout_dirs(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "skills").mkdir(parents=True, exist_ok=True)
    (root / "skill_runs").mkdir(parents=True, exist_ok=True)
    mcp_path = root / "mcp.json"
    try:
        with mcp_path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump({"mcpServers": {}}, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except FileExistsError:
        pass


def _ensure_empty_stores(root: Path) -> None:
    """在指定根下创建三库空 schema（已有库则只补 DDL，不覆盖数据）。"""
    from src.ledger import PalaceStore
    from src.market import MarketStore
    from src.ops import OpsStore

    PalaceStore(root / "palace.db").close()
    MarketStore(root / "market.db").close()
    OpsStore(root / "ops.db").close()


def initialize_data_layout(root: Path | str | None = None) -> Path:
    """创建目录树 + 三库空 schema + 空 MCP 配置。

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
    except (ImportError, OSError, sqlite3.Error) as exc:
        # 依赖缺失 / 磁盘只读 / 库被占用都不该拦住启动，但要留痕：
        # 静默 pass 会让「建库失败」在后面某个接口以莫名其妙的形式冒出来。
        logger.warning("三库空 schema 补齐失败，延后到首次访问再建：%s", exc)
    return root
