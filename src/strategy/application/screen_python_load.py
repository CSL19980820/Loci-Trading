"""Python 选股技能包：模块加载与 traceback 裁剪。"""
from __future__ import annotations

from pathlib import Path
import hashlib
import importlib.util
import sys
import threading
import traceback
import types
from typing import Any

from src.formula import FormulaDiagnostic, FormulaEvaluationError
from src.strategy.application.screen_formula import ScreenFormulaError

_LOAD_LOCK = threading.RLock()
_LOCAL_MODULE_NAMES: set[str] = set()
_TRACEBACK_LIMIT = 4
_TRACEBACK_TEXT_LIMIT = 320


class ScreenPythonError(ScreenFormulaError):
    @classmethod
    def simple(
        cls,
        code: str,
        message: str,
        *,
        line: int | None = None,
        column: int | None = None,
    ) -> ScreenPythonError:
        return cls(
            message,
            (FormulaDiagnostic(code=code, message=message, line=line, column=column),),
        )

    @classmethod
    def from_eval_error(cls, exc: FormulaEvaluationError) -> ScreenPythonError:
        return cls(str(exc), exc.diagnostics)

    @classmethod
    def from_runtime_failure(
        cls,
        code: str,
        exc: Exception,
        *,
        entrypoint: str,
        package_root: Path,
        source_path: Path,
    ) -> ScreenPythonError:
        relative = _display_relative_path(source_path, package_root)
        summary = _bounded_traceback_summary(exc, package_root)
        return cls(
            (
                f"{exc} | entrypoint={entrypoint} | file={relative}"
                f"{f' | trace={summary}' if summary else ''}"
            ),
            (
                FormulaDiagnostic(
                    code=code,
                    message=(
                        f"entrypoint={entrypoint}; file={relative}; error={exc}"
                        f"{f'; trace={summary}' if summary else ''}"
                    ),
                ),
            ),
        )



def _resolve_entrypoint(
    package_root: Path,
    entrypoint: str,
    strategy_revision: str,
) -> tuple[str, Path, str]:
    source_path = _entrypoint_source_path(package_root, entrypoint)
    relative = source_path.relative_to(package_root.resolve())
    _relative_text, attr_path = entrypoint.split(":", 1)
    if not source_path.is_file() or not source_path.is_relative_to(package_root.resolve()):
        raise ScreenPythonError.simple(
            "E_PYTHON_ENTRYPOINT", f"entrypoint 文件不存在：{relative.as_posix()}"
        )
    base = f"_screenpkg_{strategy_revision.replace(':', '_').replace('-', '_')}"
    module_tail = ".".join(relative.with_suffix("").parts)
    return f"{base}.{module_tail}", source_path, attr_path.strip()


def _load_module(module_name: str, source_path: Path, package_root: Path):
    with _LOAD_LOCK:
        _clear_local_module_cache()
        _purge_package_modules(package_root)
        _invalidate_package_bytecode(package_root)
        importlib.invalidate_caches()
        _ensure_package_modules(module_name, package_root, source_path)
        sys.path.insert(0, str(package_root))
        loaded = False
        namespace = module_name.rsplit(".", 1)[0]
        try:
            spec = importlib.util.spec_from_file_location(module_name, source_path)
            if spec is None or spec.loader is None:
                raise ScreenPythonError.simple(
                    "E_PYTHON_LOAD", f"无法加载模块：{source_path.name}"
                )
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
            except SyntaxError as exc:
                raise ScreenPythonError.simple(
                    "E_PYTHON_SYNTAX",
                    str(exc),
                    line=exc.lineno,
                    column=exc.offset,
                ) from exc
            except ScreenPythonError:
                raise
            except Exception as exc:
                raise ScreenPythonError.from_runtime_failure(
                    "E_PYTHON_IMPORT",
                    exc,
                    entrypoint=f"{_display_relative_path(source_path, package_root)}:<module>",
                    package_root=package_root,
                    source_path=source_path,
                ) from exc
            loaded = True
            return module
        finally:
            _cleanup_package_modules(
                package_root,
                keep_prefix=namespace if loaded else "",
            )
            try:
                sys.path.remove(str(package_root))
            except ValueError:
                pass


def _clear_local_module_cache() -> None:
    for name in tuple(_LOCAL_MODULE_NAMES):
        sys.modules.pop(name, None)
    _LOCAL_MODULE_NAMES.clear()


def _module_belongs_to_package(module: Any, package_root: Path) -> bool:
    filename = getattr(module, "__file__", None)
    if not filename:
        return False
    try:
        return Path(filename).resolve().is_relative_to(package_root.resolve())
    except (OSError, ValueError):
        return False


def _purge_package_modules(package_root: Path) -> None:
    root = package_root.resolve()
    for name, module in list(sys.modules.items()):
        if _module_belongs_to_package(module, root):
            sys.modules.pop(name, None)


def _invalidate_package_bytecode(package_root: Path) -> None:
    """Drop package-local ``__pycache__`` so helper edits are not shadowed."""
    root = package_root.resolve()
    for cache_dir in root.rglob("__pycache__"):
        if not cache_dir.is_dir():
            continue
        for cached in cache_dir.glob("*.pyc"):
            try:
                cached.unlink()
            except OSError:
                pass
        try:
            cache_dir.rmdir()
        except OSError:
            pass


def _cleanup_package_modules(package_root: Path, *, keep_prefix: str) -> None:
    root = package_root.resolve()
    for name, module in list(sys.modules.items()):
        if not _module_belongs_to_package(module, root):
            continue
        if keep_prefix and (name == keep_prefix or name.startswith(f"{keep_prefix}.")):
            continue
        _LOCAL_MODULE_NAMES.add(name)
        sys.modules.pop(name, None)


def _python_source_fingerprints(
    package_files: dict[str, str] | None,
    install_path: str,
) -> dict[str, str]:
    """为所有 Python 源文件建指纹，避免 helper 变更复用旧策略版本。"""
    sources: dict[str, bytes] = {}
    if package_files is not None:
        for relative, content in package_files.items():
            normalized = str(relative).replace("\\", "/")
            if normalized.lower().endswith(".py"):
                sources[normalized] = str(content).encode("utf-8")
    elif install_path:
        root = Path(install_path)
        if root.is_dir():
            for path in root.rglob("*.py"):
                if path.is_file():
                    relative = path.relative_to(root).as_posix()
                    sources[relative] = path.read_bytes()
    return {
        name: hashlib.sha256(sources[name]).hexdigest()
        for name in sorted(sources)
    }


def _ensure_package_modules(
    module_name: str, package_root: Path, source_path: Path
) -> None:
    parts = module_name.split(".")
    if len(parts) < 2:
        return
    relative_parent = source_path.parent.relative_to(package_root)
    package_paths = [package_root, *[package_root / Path(*relative_parent.parts[:i + 1]) for i in range(len(relative_parent.parts))]]
    for index in range(len(parts) - 1):
        name = ".".join(parts[: index + 1])
        module = sys.modules.get(name)
        if module is None:
            module = types.ModuleType(name)
            sys.modules[name] = module
        path_index = min(index, len(package_paths) - 1)
        module.__path__ = [str(package_paths[path_index])]  # type: ignore[attr-defined]


def _normalize_code(code: str) -> str:
    return str(code or "").rstrip() + "\n"


def _stable_sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _entrypoint_source_path(package_root: Path, entrypoint: str) -> Path:
    relative_text, _attr_path = entrypoint.split(":", 1)
    relative = Path(relative_text.replace("\\", "/"))
    if relative.is_absolute() or any(part == ".." for part in relative.parts):
        raise ScreenPythonError.simple("E_PYTHON_ENTRYPOINT", "entrypoint 路径非法")
    return (package_root / relative).resolve()


def _display_relative_path(path: Path, package_root: Path) -> str:
    try:
        return path.resolve().relative_to(package_root.resolve()).as_posix()
    except ValueError:
        return path.name


def _bounded_traceback_summary(exc: Exception, package_root: Path) -> str:
    extracted = traceback.extract_tb(exc.__traceback__)
    if not extracted:
        return ""
    picked = [
        frame
        for frame in extracted
        if Path(frame.filename).resolve().is_relative_to(package_root.resolve())
    ]
    frames = (picked or extracted)[-_TRACEBACK_LIMIT:]
    parts = [
        f"{_display_relative_path(Path(frame.filename), package_root)}:{frame.lineno} in {frame.name}"
        for frame in frames
    ]
    text = " -> ".join(parts)
    if len(text) > _TRACEBACK_TEXT_LIMIT:
        return text[: _TRACEBACK_TEXT_LIMIT - 3] + "..."
    return text
