"""Screen Skill 包的磁盘读写与历史快照。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import uuid
import zipfile

import yaml

from src.ops.application.skills import MAX_ARCHIVE_BYTES, SkillError, parse_manifest
from src.shared.paths import data_dir, skill_root

_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_ROOT_FILES = {"SKILL.md", "screen.yaml", "formula.tdx", "strategy.py", "ui.json"}
_REF_SUFFIXES = {".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".csv", ".tsv"}
_PYTHON_SUFFIXES = {".py"}
_MAX_ENTRIES = 2000
_MAX_EXTRACTED_BYTES = 200 * 1024 * 1024


class ScreenPackageError(SkillError):
    """Screen Skill 包错误。"""


@dataclass(slots=True)
class ScreenPackageRecord:
    slug: str
    name: str
    description: str
    version: str
    body: str
    enabled: bool
    install_path: str
    files: list[str]
    package_revision: str
    updated_at: str
    screen: dict
    runtime: str
    dialect: str
    entrypoint: str | None
    code: str
    formula: str
    ui: dict | None


@dataclass(slots=True)
class ScreenArchiveBundle:
    record: ScreenPackageRecord
    files: dict[str, str]


def archive_declares_screen_capability(archive_path: Path | str) -> bool:
    path = Path(archive_path)
    if not path.is_file() or not zipfile.is_zipfile(path):
        return False
    with zipfile.ZipFile(path) as archive:
        try:
            infos = _safe_archive_entries(archive)
        except ScreenPackageError:
            return False
        manifests = [
            info
            for info in infos
            if Path(info.filename.replace("\\", "/")).name == "SKILL.md"
        ]
        if not manifests:
            return False
        chosen = min(
            manifests,
            key=lambda info: len(Path(info.filename.replace("\\", "/")).parts),
        )
        try:
            text = archive.read(chosen).decode("utf-8")
        except UnicodeDecodeError:
            return False
    try:
        meta, _ = parse_manifest(text)
    except SkillError:
        return False
    return str(meta.get("capability") or "").strip().lower() == "screen"


def list_screen_packages(
    *, skill_root_path: Path | str | None = None
) -> list[ScreenPackageRecord]:
    root = Path(skill_root_path or skill_root())
    if not root.is_dir():
        return []
    records: list[ScreenPackageRecord] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        try:
            record = _load_record_from_dir(child)
        except ScreenPackageError:
            continue
        if record is not None:
            records.append(record)
    return records


def get_screen_package(
    slug: str,
    *,
    skill_root_path: Path | str | None = None,
) -> ScreenPackageRecord | None:
    root = Path(skill_root_path or skill_root())
    folder = (root / _normalise_slug(slug)).resolve()
    if not folder.is_dir() or not folder.is_relative_to(root.resolve()):
        return None
    return _load_record_from_dir(folder)


def save_screen_package(
    slug: str,
    files: dict[str, str],
    *,
    expected_revision: str | None = None,
    skill_root_path: Path | str | None = None,
) -> ScreenPackageRecord:
    normalized_slug = _normalise_slug(slug)
    rendered = _validate_file_map(files)
    root = Path(skill_root_path or skill_root())
    root.mkdir(parents=True, exist_ok=True)
    destination = (root / normalized_slug).resolve()
    if not destination.parent.is_relative_to(root.resolve()):
        raise ScreenPackageError("非法的 Screen Skill 路径")
    current = get_screen_package(normalized_slug, skill_root_path=root)
    if current is not None and expected_revision and current.package_revision != expected_revision:
        raise ScreenPackageError("revision_conflict")
    if current is None and expected_revision:
        raise ScreenPackageError("revision_conflict")

    staging = root / f".screen-stage-{normalized_slug}-{uuid.uuid4().hex}"
    backup: Path | None = None
    swapped = False
    try:
        package_dir = staging / normalized_slug
        _write_file_map(package_dir, rendered)
        staged = _load_record_from_dir(package_dir)
        if staged is None or staged.slug != normalized_slug:
            raise ScreenPackageError("Screen Skill slug 与目录名不一致")
        if current is not None:
            _archive_snapshot(destination, current.package_revision)
            backup = root / f".screen-backup-{normalized_slug}-{uuid.uuid4().hex}"
            destination.rename(backup)
        package_dir.rename(destination)
        swapped = True
        if backup is not None and backup.exists():
            shutil.rmtree(backup)
        return _load_record_from_dir(destination) or staged
    except Exception:
        if swapped and destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        if backup is not None and backup.exists() and not destination.exists():
            backup.rename(destination)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def delete_screen_package(
    slug: str,
    *,
    expected_revision: str,
    skill_root_path: Path | str | None = None,
) -> bool:
    root = Path(skill_root_path or skill_root())
    current = get_screen_package(slug, skill_root_path=root)
    if current is None:
        return False
    if current.package_revision != expected_revision:
        raise ScreenPackageError("revision_conflict")
    target = Path(current.install_path)
    backup = root / f".screen-delete-{current.slug}-{uuid.uuid4().hex}"
    _archive_snapshot(target, current.package_revision)
    target.rename(backup)
    try:
        shutil.rmtree(backup)
    except Exception:
        backup.rename(target)
        raise
    return True


def read_screen_archive(archive_path: Path | str) -> ScreenArchiveBundle:
    path = Path(archive_path)
    if not path.is_file():
        raise ScreenPackageError(f"找不到技能包文件：{path}")
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ScreenPackageError("技能包超过上传上限")
    if not zipfile.is_zipfile(path):
        raise ScreenPackageError("不是合法的 zip 文件")
    with tempfile.TemporaryDirectory(prefix="screen-archive-") as tmp:
        staging = Path(tmp) / "unpacked"
        staging.mkdir()
        with zipfile.ZipFile(path) as archive:
            infos = _safe_archive_entries(archive)
            for info in infos:
                relative = Path(info.filename.replace("\\", "/"))
                target = (staging / relative).resolve()
                if not target.is_relative_to(staging.resolve()):
                    raise ScreenPackageError(f"解压路径逃逸，已拒绝：{info.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        record = _load_record_from_dir(_locate_package_root(staging), enforce_dir_slug=False)
        if record is None:
            raise ScreenPackageError("包内不包含有效的 Screen Skill")
        files = {
            relative: (Path(record.install_path) / relative).read_text(encoding="utf-8")
            for relative in record.files
        }
        return ScreenArchiveBundle(record=record, files=files)


def _load_record_from_dir(
    folder: Path, *, enforce_dir_slug: bool = True
) -> ScreenPackageRecord | None:
    folder = folder.resolve()
    manifest = _locate_manifest(folder)
    try:
        meta, body = parse_manifest(_read_utf8_text(manifest, "SKILL.md"))
    except SkillError as exc:
        raise ScreenPackageError(str(exc)) from exc
    if str(meta.get("capability") or "").strip().lower() != "screen":
        return None
    slug = _normalise_slug(meta.get("slug") or folder.name)
    if enforce_dir_slug and slug != folder.name:
        raise ScreenPackageError("Screen Skill slug 与目录名不一致")
    if not str(meta.get("name") or "").strip():
        raise ScreenPackageError("SKILL.md 缺少 name")
    if not str(meta.get("description") or "").strip():
        raise ScreenPackageError("SKILL.md 缺少 description")
    if not body.strip():
        raise ScreenPackageError("SKILL.md 正文不能为空")

    files = _collect_files(folder)
    if "screen.yaml" not in files:
        raise ScreenPackageError(f"{slug} 缺少 screen.yaml")
    screen = _load_screen_yaml(folder / "screen.yaml", "screen.yaml")
    runtime = _resolve_runtime(screen, files)
    dialect = _resolve_dialect(screen, runtime)
    entrypoint = _resolve_entrypoint(screen, runtime)
    code_file = _required_code_file(runtime)
    if code_file not in files:
        raise ScreenPackageError(f"{slug} 缺少 {code_file}")

    ui = None
    if "ui.json" in files:
        raw_ui = _read_utf8_text(folder / "ui.json", "ui.json")
        try:
            ui = json.loads(raw_ui) if raw_ui.strip() else None
        except json.JSONDecodeError as exc:
            raise ScreenPackageError(
                f"ui.json 不是合法 JSON：{exc.msg} (line {exc.lineno}, column {exc.colno})"
            ) from exc
        if ui is not None and not isinstance(ui, dict):
            raise ScreenPackageError("ui.json 必须是 JSON 对象")

    file_map = {relative: _read_utf8_text(folder / relative, relative) for relative in files}
    updated_at = _updated_at_for_files(folder, files)
    code = _read_utf8_text(folder / code_file, code_file)
    return ScreenPackageRecord(
        slug=slug,
        name=str(meta.get("name") or slug),
        description=str(meta.get("description") or "").strip(),
        version=str(meta.get("version") or ""),
        body=body,
        enabled=_meta_enabled(meta),
        install_path=str(folder),
        files=files,
        package_revision=_hash_files(file_map),
        updated_at=updated_at,
        screen=screen,
        runtime=runtime,
        dialect=dialect,
        entrypoint=entrypoint,
        code=code,
        formula=code if runtime == "formula" else "",
        ui=ui,
    )


def _collect_files(folder: Path) -> list[str]:
    files: list[str] = []
    for path in sorted(folder.rglob("*")):
        if path.is_dir():
            continue
        if path.is_symlink():
            raise ScreenPackageError(f"不允许的符号链接：{path.name}")
        relative = str(path.relative_to(folder)).replace("\\", "/")
        # Python 导入产生的缓存不是包正文；否则运行一次后参数保存/导出会失败。
        if "__pycache__" in Path(relative).parts and path.suffix == ".pyc":
            continue
        _validate_relative_path(relative)
        files.append(relative)
    if not files:
        raise ScreenPackageError("Screen Skill 目录为空")
    return files


def _validate_file_map(files: dict[str, str]) -> dict[str, str]:
    rendered = {name.replace("\\", "/"): str(content) for name, content in files.items()}
    if "SKILL.md" not in rendered or "screen.yaml" not in rendered:
        raise ScreenPackageError("Screen Skill 缺少必需文件")
    screen = _load_screen_yaml_text(rendered["screen.yaml"], "screen.yaml")
    runtime = _resolve_runtime(screen, rendered.keys())
    code_file = _required_code_file(runtime)
    if code_file not in rendered:
        raise ScreenPackageError(f"Screen Skill 缺少必需文件：{code_file}")
    for relative, content in rendered.items():
        _validate_relative_path(relative)
        if not content.strip() and relative in {"SKILL.md", "screen.yaml", code_file}:
            raise ScreenPackageError(f"{relative} 不能为空")
    return rendered


def _write_file_map(folder: Path, files: dict[str, str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _validate_relative_path(relative: str) -> None:
    path = Path(relative)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ScreenPackageError(f"非法路径：{relative}")
    suffix = path.suffix.lower()
    if relative in _ROOT_FILES:
        return
    if suffix in _PYTHON_SUFFIXES:
        return
    if relative.startswith("references/") and suffix in _REF_SUFFIXES:
        return
    raise ScreenPackageError(f"Screen Skill 不允许的文件：{relative}")


def _read_utf8_text(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ScreenPackageError(f"{label} 不是合法 UTF-8 文本") from exc


def _archive_snapshot(folder: Path, revision: str) -> None:
    target = _history_root(folder.parent) / folder.name / f"{revision}.zip"
    if target.exists() or _history_tombstone(target).exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(
                    path, arcname=str(path.relative_to(folder)).replace("\\", "/")
                )


def list_screen_history(
    slug: str, *, skill_root_path: Path | str | None = None
) -> list[dict[str, str]]:
    root = Path(skill_root_path or skill_root())
    normalized_slug = _normalise_slug(slug)
    current = get_screen_package(normalized_slug, skill_root_path=root)
    active_revision = current.package_revision if current is not None else ""
    history_dir = _history_root(root) / normalized_slug
    if not history_dir.is_dir():
        return []
    records: list[dict[str, str]] = []
    for archive in history_dir.glob("*.zip"):
        try:
            bundle = read_screen_archive(archive)
        except ScreenPackageError:
            continue
        if bundle.record.slug != normalized_slug or bundle.record.package_revision != archive.stem:
            continue
        if bundle.record.package_revision == active_revision:
            continue
        records.append(
            {
                "version": bundle.record.package_revision,
                "package_revision": bundle.record.package_revision,
                "name": bundle.record.name,
                "runtime": bundle.record.runtime,
                "created_at": datetime.fromtimestamp(archive.stat().st_mtime)
                .astimezone()
                .isoformat(timespec="seconds"),
            }
        )
    return sorted(records, key=lambda item: item["created_at"], reverse=True)


def restore_screen_package(
    slug: str,
    revision: str,
    *,
    expected_revision: str | None = None,
    skill_root_path: Path | str | None = None,
) -> ScreenPackageRecord:
    root = Path(skill_root_path or skill_root())
    normalized_slug = _normalise_slug(slug)
    revision = _normalise_history_revision(revision)
    current = get_screen_package(normalized_slug, skill_root_path=root)
    if current is not None and expected_revision and current.package_revision != expected_revision:
        raise ScreenPackageError("revision_conflict")
    archive = _history_root(root) / normalized_slug / f"{revision}.zip"
    if not archive.is_file() or _history_tombstone(archive).exists():
        raise ScreenPackageError("history_not_found")
    bundle = read_screen_archive(archive)
    if bundle.record.slug != normalized_slug or bundle.record.package_revision != revision:
        raise ScreenPackageError("history_not_found")
    if current is not None and current.package_revision == revision:
        return current
    return save_screen_package(
        normalized_slug,
        bundle.files,
        expected_revision=current.package_revision if current is not None else None,
        skill_root_path=root,
    )


def delete_screen_history(
    slug: str, revision: str, *, skill_root_path: Path | str | None = None
) -> bool:
    root = Path(skill_root_path or skill_root())
    normalized_slug = _normalise_slug(slug)
    normalized_revision = _normalise_history_revision(revision)
    current = get_screen_package(normalized_slug, skill_root_path=root)
    if current is not None and current.package_revision == normalized_revision:
        raise ScreenPackageError("cannot_delete_active_history")
    archive = _history_root(root) / normalized_slug / f"{normalized_revision}.zip"
    if not archive.is_file():
        return False
    archive.unlink()
    _history_tombstone(archive).touch()
    return True


def _safe_archive_entries(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > _MAX_ENTRIES:
        raise ScreenPackageError("包内条目过多")
    total = sum(info.file_size for info in infos)
    if total > _MAX_EXTRACTED_BYTES:
        raise ScreenPackageError("解压后体积过大")
    safe: list[zipfile.ZipInfo] = []
    for info in infos:
        name = info.filename
        if info.is_dir():
            continue
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise ScreenPackageError(f"包内含符号链接，已拒绝：{name}")
        if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
            raise ScreenPackageError(f"包内含绝对路径，已拒绝：{name}")
        relative = Path(name.replace("\\", "/"))
        if any(part == ".." for part in relative.parts):
            raise ScreenPackageError(f"包内含上跳路径，已拒绝：{name}")
        _validate_archive_relative(relative)
        safe.append(info)
    if not safe:
        raise ScreenPackageError("包内没有有效文件")
    return safe


def _locate_manifest(root: Path) -> Path:
    direct = root / "SKILL.md"
    if direct.is_file():
        return direct
    matches = sorted(root.rglob("SKILL.md"))
    if not matches:
        raise ScreenPackageError("包内找不到 SKILL.md")
    return min(matches, key=lambda path: len(path.parts))


def _locate_package_root(root: Path) -> Path:
    return _locate_manifest(root).parent


def _hash_files(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[name].encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _updated_at_for_files(folder: Path, files: list[str]) -> str:
    latest = max((folder / relative).stat().st_mtime for relative in files)
    return datetime.fromtimestamp(latest).astimezone().isoformat(timespec="seconds")


def _history_root(skill_root_path: Path | None = None) -> Path:
    return (skill_root_path.parent if skill_root_path is not None else data_dir()) / "skill-history"


def _history_tombstone(archive: Path) -> Path:
    return archive.with_suffix(".deleted")


def _normalise_history_revision(raw: str) -> str:
    revision = str(raw).strip().lower()
    if not re.fullmatch(r"[a-f0-9]{64}", revision):
        raise ScreenPackageError("history_not_found")
    return revision


def _meta_enabled(meta: dict) -> bool:
    value = meta.get("enabled", True)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _normalise_slug(raw: str) -> str:
    slug = str(raw).strip().lower()
    if not _SLUG_PATTERN.match(slug):
        raise ScreenPackageError(f"非法的技能标识：{raw!r}")
    return slug


def _load_screen_yaml(path: Path, label: str) -> dict:
    return _load_screen_yaml_text(_read_utf8_text(path, label), label)


def _load_screen_yaml_text(text: str, label: str) -> dict:
    try:
        screen = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ScreenPackageError(f"{label} 不是合法 YAML：{exc}") from exc
    if not isinstance(screen, dict):
        raise ScreenPackageError(f"{label} 必须是键值映射")
    return screen


def _resolve_runtime(screen: dict, files) -> str:
    runtime = str(screen.get("runtime") or "").strip().lower()
    names = set(files)
    if not runtime:
        runtime = "python" if "strategy.py" in names and "formula.tdx" not in names else "formula"
    if runtime not in {"formula", "python"}:
        raise ScreenPackageError(f"不支持的 runtime：{runtime!r}")
    return runtime


def _resolve_dialect(screen: dict, runtime: str) -> str:
    dialect = str(screen.get("dialect") or "").strip().lower()
    if runtime == "python":
        if dialect and dialect != "python":
            raise ScreenPackageError("python runtime 的 dialect 只能是 python")
        return "python"
    if dialect in {"", "formula"}:
        return "loci"
    if dialect not in {"loci", "tdx", "ths"}:
        raise ScreenPackageError(f"formula runtime 不支持 dialect：{dialect!r}")
    return dialect


def _resolve_entrypoint(screen: dict, runtime: str) -> str | None:
    if runtime != "python":
        return None
    entrypoint = str(screen.get("entrypoint") or "strategy.py:compute").strip()
    if ":" not in entrypoint or not entrypoint.split(":", 1)[0].endswith(".py"):
        raise ScreenPackageError("python runtime 的 entrypoint 必须是 file.py:callable")
    return entrypoint


def _required_code_file(runtime: str) -> str:
    return "strategy.py" if runtime == "python" else "formula.tdx"


def _validate_archive_relative(relative: Path) -> None:
    candidate = str(relative).replace("\\", "/")
    try:
        _validate_relative_path(candidate)
        return
    except ScreenPackageError:
        if len(relative.parts) <= 1:
            raise
    _validate_relative_path("/".join(relative.parts[1:]))
