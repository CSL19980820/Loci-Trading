"""一键分享打包：仅基于已编译的 Loci onedir 产物生成加密 zip。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from src.shared.paths import (
    config_path,
    data_dir,
    mcp_json_path,
    market_db,
    ops_db,
    palace_db,
    skill_root,
    writable_root,
)
from src.shared.version import APP_RELEASED_AT, APP_RELEASE_SUMMARY, APP_VERSION

#: 分享包固定解压密码（后续可改为可配置）
SHARE_PACK_PASSWORD = "Asdf!234"

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_ARCHIVE_ROOT_NAME = "Loci"

# _internal 内跳过的噪声（审计/缓存），其余整树打入
_INTERNAL_SKIP_DIR_NAMES = frozenset(
    {
        "__pycache__",
        ".git",
        ".pytest_cache",
        "loci-audit-shots",
        ".workbuddy-ai",
    }
)


@dataclass(frozen=True)
class PackOption:
    id: str
    label: str
    description: str
    default: bool


#: 不勾「内置算法」时从 _internal 排除的相对路径前缀
_ALGORITHM_PREFIXES = (
    ("src", "strategy"),
    ("src", "formula"),
)

PACK_OPTIONS: tuple[PackOption, ...] = (
    PackOption(
        "algorithms",
        "内置算法",
        "潜龙等内置战法与公式引擎（_internal/src/strategy、formula）",
        True,
    ),
    PackOption(
        "market",
        "行情数据",
        "market.db：日 K 等可重建缓存，非个人数据，体积可能很大",
        False,
    ),
    PackOption(
        "ops",
        "运维骨架",
        "ops.db：任务定义、战法档案、推送模板、调参档位。"
        "默认已抹掉 LLM 密钥、Webhook 与纸面舱/教训/留痕等个人记录",
        False,
    ),
    PackOption(
        "mcp",
        "MCP 接入骨架",
        "mcp.json：服务地址与工具清单。默认已抹掉 API Key",
        False,
    ),
    PackOption(
        "skills",
        "技能包",
        "data/skills/ 下已安装技能正文",
        False,
    ),
    PackOption(
        "config",
        "本机配置",
        "loci.config.json 与 data/desktop.json，默认已抹掉密钥字段",
        False,
    ),
    PackOption(
        "ledger",
        "账本（个人）",
        "palace.db：你的真实成交、候选与预案。给别人分享通常不该勾",
        False,
    ),
    PackOption(
        "private",
        "包含我的密钥与个人记录（危险）",
        "取消上面各项的脱敏：API Key、Webhook、纸面交易记录都会原样打进包里。"
        "只在给自己换机器时勾选",
        False,
    ),
)

_OPTION_IDS = frozenset(opt.id for opt in PACK_OPTIONS)


class SharePackError(ValueError):
    """打包前置条件或参数不合法。"""


def resolve_bundle_root(root: Path | None = None) -> Path | None:
    """定位已编译的 onedir：``Loci.exe`` + ``_internal``。

    优先 ``writable_root``（打包运行时即 exe 旁）；开发态再试 ``writable_root/Loci``。
    """
    base = (root or writable_root()).resolve()
    candidates = (base, base / "Loci")
    for candidate in candidates:
        if (candidate / "Loci.exe").is_file() and (candidate / "_internal").is_dir():
            return candidate
    return None


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _dir_size(path: Path) -> int:
    if not path.is_dir():
        return 0
    total = 0
    try:
        for child in path.rglob("*"):
            if child.is_file():
                try:
                    total += child.stat().st_size
                except OSError:
                    continue
    except OSError:
        return total
    return total


def _algorithm_roots(bundle: Path) -> list[Path]:
    internal = bundle / "_internal"
    return [
        internal / "src" / "strategy",
        internal / "src" / "formula",
    ]


def _algorithms_bytes(bundle: Path | None) -> int:
    if bundle is None:
        return 0
    return sum(_dir_size(path) for path in _algorithm_roots(bundle))


def _option_bytes(option_id: str, *, bundle: Path | None = None) -> int:
    if option_id == "algorithms":
        return _algorithms_bytes(bundle)
    if option_id == "private":
        return 0
    if option_id == "ledger":
        return _file_size(palace_db())
    if option_id == "market":
        return _file_size(market_db())
    if option_id == "ops":
        return _file_size(ops_db())
    if option_id == "mcp":
        return _file_size(mcp_json_path())
    if option_id == "skills":
        return _dir_size(skill_root())
    if option_id == "config":
        return _file_size(config_path()) + _file_size(data_dir() / "desktop.json")
    return 0


def _option_available(option_id: str, *, bundle: Path | None = None) -> bool:
    if option_id == "algorithms":
        return any(path.is_dir() for path in _algorithm_roots(bundle)) if bundle else False
    if option_id == "private":
        return True
    if option_id == "ledger":
        return palace_db().is_file()
    if option_id == "market":
        return market_db().is_file()
    if option_id == "ops":
        return ops_db().is_file()
    if option_id == "mcp":
        return mcp_json_path().is_file()
    if option_id == "skills":
        root = skill_root()
        return root.is_dir() and any(root.iterdir())
    if option_id == "config":
        return config_path().is_file() or (data_dir() / "desktop.json").is_file()
    return False


def share_pack_status(*, bundle_root: Path | None = None) -> dict[str, Any]:
    """供设置页展示：能否打包、各可选件体积、版本信息。不回传解压密码。"""
    resolved = resolve_bundle_root(bundle_root)
    can_pack = resolved is not None
    reason = "" if can_pack else "尚未找到编译产物（需要 Loci.exe 与 _internal）。请先运行 scripts/build-loci.ps1。"
    runtime_bytes = 0
    algo_bytes = 0
    if resolved is not None:
        algo_bytes = _algorithms_bytes(resolved)
        runtime_bytes = (
            _file_size(resolved / "Loci.exe")
            + _dir_size(resolved / "_internal")
            - algo_bytes
        )
        readme = resolved / "使用说明.txt"
        if not readme.is_file():
            readme = writable_root() / "使用说明.txt"
        runtime_bytes += _file_size(readme)

    options: list[dict[str, Any]] = []
    for opt in PACK_OPTIONS:
        available = _option_available(opt.id, bundle=resolved)
        options.append(
            {
                "id": opt.id,
                "label": opt.label,
                "description": opt.description,
                "default": opt.default,
                "available": available,
                "bytes": _option_bytes(opt.id, bundle=resolved) if available else 0,
            }
        )

    return {
        "version": APP_VERSION,
        "released_at": APP_RELEASED_AT,
        "summary": APP_RELEASE_SUMMARY,
        "can_pack": can_pack,
        "reason": reason,
        "bundle_root": str(resolved) if resolved else None,
        "runtime_bytes": max(runtime_bytes, 0),
        "options": options,
    }


def _normalize_includes(include: Iterable[str] | None) -> set[str]:
    selected = {str(item).strip() for item in (include or ()) if str(item).strip()}
    unknown = selected - _OPTION_IDS
    if unknown:
        raise SharePackError(f"未知打包选项：{', '.join(sorted(unknown))}")
    return selected


def _is_algorithm_path(rel_parts: tuple[str, ...]) -> bool:
    return any(
        len(rel_parts) >= len(prefix) and rel_parts[: len(prefix)] == prefix
        for prefix in _ALGORITHM_PREFIXES
    )


def _should_skip_internal(
    path: Path,
    internal_root: Path,
    *,
    include_algorithms: bool,
) -> bool:
    try:
        rel_parts = path.relative_to(internal_root).parts
    except ValueError:
        return True
    if any(part in _INTERNAL_SKIP_DIR_NAMES for part in rel_parts):
        return True
    if not include_algorithms and _is_algorithm_path(rel_parts):
        return True
    return False


def _copy_runtime(bundle: Path, staging: Path, *, include_algorithms: bool) -> None:
    exe = bundle / "Loci.exe"
    internal = bundle / "_internal"
    shutil.copy2(exe, staging / "Loci.exe")
    dest_internal = staging / "_internal"
    dest_internal.mkdir(parents=True, exist_ok=True)
    for src in internal.rglob("*"):
        if _should_skip_internal(src, internal, include_algorithms=include_algorithms):
            continue
        rel = src.relative_to(internal)
        dest = dest_internal / rel
        if src.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    readme = bundle / "使用说明.txt"
    if not readme.is_file():
        readme = writable_root() / "使用说明.txt"
    if readme.is_file():
        shutil.copy2(readme, staging / "使用说明.txt")

    version_note = staging / "VERSION.txt"
    version_note.write_text(
        f"Loci {APP_VERSION}\n发布：{APP_RELEASED_AT}\n{APP_RELEASE_SUMMARY}\n",
        encoding="utf-8",
    )


def _copy_optional(staging: Path, selected: set[str], *, sanitize: bool) -> list[str]:
    """拷贝可选件；``sanitize=True``（默认）时先抹掉密钥与个人记录。"""
    from src.ops.application.share_pack_sanitize import (
        sanitize_json_file,
        sanitize_mcp_json,
        sanitize_ops_db,
    )

    data_staging = staging / "data"
    if selected & {"ledger", "market", "ops", "mcp", "skills", "config"}:
        data_staging.mkdir(parents=True, exist_ok=True)

    notes: list[str] = []
    mapping: list[tuple[str, Path, Path]] = [
        ("ledger", palace_db(), data_staging / "palace.db"),
        ("market", market_db(), data_staging / "market.db"),
        ("ops", ops_db(), data_staging / "ops.db"),
        ("mcp", mcp_json_path(), data_staging / "mcp.json"),
    ]
    for option_id, src, dest in mapping:
        if option_id not in selected:
            continue
        if not src.is_file():
            raise SharePackError(f"「{option_id}」对应文件不存在：{src}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if sanitize and option_id == "ops":
            notes.extend(sanitize_ops_db(src, dest))
        elif sanitize and option_id == "mcp":
            notes.extend(sanitize_mcp_json(src, dest))
        else:
            shutil.copy2(src, dest)

    if "skills" in selected:
        src_skills = skill_root()
        if not src_skills.is_dir() or not any(src_skills.iterdir()):
            raise SharePackError("技能包目录为空或不存在")
        dest_skills = data_staging / "skills"
        if dest_skills.exists():
            shutil.rmtree(dest_skills)
        shutil.copytree(
            src_skills,
            dest_skills,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"),
        )

    if "config" in selected:
        cfg = config_path()
        if cfg.is_file():
            if sanitize:
                notes.extend(sanitize_json_file(cfg, staging / "loci.config.json"))
            else:
                shutil.copy2(cfg, staging / "loci.config.json")
        desktop = data_dir() / "desktop.json"
        if desktop.is_file():
            data_staging.mkdir(parents=True, exist_ok=True)
            shutil.copy2(desktop, data_staging / "desktop.json")
        if not cfg.is_file() and not desktop.is_file():
            raise SharePackError("未找到可打包的本机配置")
    return notes


def _zip_encrypted(staging: Path, zip_path: Path, *, password: str) -> None:
    try:
        import pyzipper
    except ImportError as exc:
        raise SharePackError(
            "缺少 pyzipper，无法生成加密 zip。请执行：pip install pyzipper"
        ) from exc

    pwd = password.encode("utf-8")
    with pyzipper.AESZipFile(
        zip_path,
        "w",
        compression=pyzipper.ZIP_DEFLATED,
        encryption=pyzipper.WZ_AES,
    ) as archive:
        archive.setpassword(pwd)
        for src in staging.rglob("*"):
            if not src.is_file():
                continue
            arcname = Path(_ARCHIVE_ROOT_NAME) / src.relative_to(staging)
            archive.write(src, arcname.as_posix())


def build_share_pack(
    *,
    include: Iterable[str] | None = None,
    bundle_root: Path | None = None,
    output_dir: Path | None = None,
    password: str,
) -> dict[str, Any]:
    """组装分享包，返回 ``path`` / ``filename`` / ``bytes`` / ``includes``。"""
    selected = _normalize_includes(include)
    if password != SHARE_PACK_PASSWORD:
        raise SharePackError("打包密码不正确")
    bundle = resolve_bundle_root(bundle_root)
    if bundle is None:
        raise SharePackError(
            "尚未找到编译产物（需要 Loci.exe 与 _internal）。请先运行 scripts/build-loci.ps1。"
        )

    from src.ops.application.share_pack_sanitize import find_forbidden_files

    stamp = datetime.now(_SHANGHAI).strftime("%Y%m%d-%H%M")
    filename = f"Loci-v{APP_VERSION}-{stamp}.zip"
    out_dir = (output_dir or Path(tempfile.gettempdir()) / "loci-share-pack").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / filename
    include_algorithms = "algorithms" in selected
    include_private = "private" in selected
    data_selected = selected - {"algorithms", "private"}

    with tempfile.TemporaryDirectory(prefix="loci-share-staging-") as tmp:
        staging = Path(tmp) / _ARCHIVE_ROOT_NAME
        staging.mkdir(parents=True, exist_ok=True)
        _copy_runtime(bundle, staging, include_algorithms=include_algorithms)
        sanitized = _copy_optional(staging, data_selected, sanitize=not include_private)
        # 最后一道闸：密钥文件绝不出机器，哪怕它是从编译产物里带进来的
        leaked = find_forbidden_files(staging)
        if leaked:
            raise SharePackError(
                "打包已中止：检测到不应外发的密钥文件 " + "、".join(leaked)
            )
        if zip_path.exists():
            zip_path.unlink()
        _zip_encrypted(staging, zip_path, password=password)

    size = _file_size(zip_path)
    return {
        "path": str(zip_path),
        "filename": filename,
        "bytes": size,
        "includes": sorted(selected),
        "sanitized": not include_private,
        "sanitize_notes": sanitized,
        "version": APP_VERSION,
        "bundle_root": str(bundle),
    }
