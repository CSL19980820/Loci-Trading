"""Skill 本地 CLI 执行：目录 jail + 无 shell + 超时截断。

模型只能调用 frontmatter 声明过的 command；**argv[0] 走白名单**：只认解释器
``python`` / ``py``，或技能包内确实存在的脚本文件。裸可执行名（``bash`` /
``sh`` / ``curl``）一律拒绝，解释器的 ``-c`` / ``-m`` 同样拒绝。
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from src.ops.application.skills import SkillError

#: 单次 stdout+stderr 回传上限（字节）
MAX_OUTPUT_BYTES = 512 * 1024
DEFAULT_TIMEOUT_SEC = 120

_INTERPRETER_NAMES = {"python", "python3", "py"}


def _resolve_python() -> str:
    """优先当前解释器，其次 PATH 上的 python。"""
    return sys.executable or shutil.which("python") or shutil.which("python3") or "python"


def _jail_path(skill_root: Path, relative: str | Path) -> Path:
    root = skill_root.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise SkillError(f"路径越界，已拒绝：{relative}")
    return target


#: 解释器的「从命令行喂代码」开关。允许它们等于让 SKILL.md 直接携带可执行代码，
#: 绕过「脚本必须是技能包内的文件」这条唯一的可审计边界。
_CODE_INLINE_FLAGS = {"-c", "-m", "--command"}


def _resolve_executable(skill_root: Path, token: str) -> str:
    """argv[0] 白名单：只认解释器名或技能包内**确实存在**的文件。

    旧实现靠「像不像路径」判断（有分隔符或有后缀才 jail），于是 ``bash`` /
    ``sh`` / ``curl`` / ``node`` 这类裸可执行名原样入 argv，由 subprocess 经 PATH
    解析出容器里的 /bin/bash——本文件开头声称的「可执行路径必须落在 skill 根内」
    在实现里根本不成立。2026-09 的安全审查把这条判成 critical：任意已登录租户
    都能上传技能包并启动 Skill Run，等于容器内任意命令执行。

    现在反过来：先白名单，不在名单里且不是包内文件的一律拒绝。
    """
    if token.lower() in _INTERPRETER_NAMES:
        return _resolve_python()
    target = _jail_path(skill_root, token)
    if not target.is_file():
        allowed = "/".join(sorted(_INTERPRETER_NAMES))
        raise SkillError(
            f"可执行文件只能是 {allowed} 或技能包内已存在的脚本，已拒绝：{token}"
        )
    return str(target)


def build_command(
    skill_root: Path,
    command: list[Any],
    arguments: dict[str, Any] | None = None,
) -> list[str]:
    """把声明的 command + 模型参数拼成 argv（无 shell）。

    约定：
    - command[0] 若为 python/py → 换成当前解释器
    - 含路径分隔或带后缀的项 → 相对 skill 根做 jail
    - arguments 里非空标量按 ``--key value`` 追加（bool True → ``--key``）
    """
    if not command or not isinstance(command, list):
        raise SkillError("cli 工具缺少 command 数组")

    argv: list[str] = []
    for index, raw in enumerate(command):
        token = str(raw).strip()
        if not token:
            continue
        if index == 0:
            argv.append(_resolve_executable(skill_root, token))
            continue
        if token.lower() in _CODE_INLINE_FLAGS:
            raise SkillError(
                f"不允许从命令行喂代码（{token}）：脚本必须是技能包内的文件，"
                "否则 SKILL.md 本身就是可执行载荷"
            )
        looks_like_path = "/" in token or "\\" in token or bool(Path(token).suffix)
        if looks_like_path:
            argv.append(str(_jail_path(skill_root, token)))
            continue
        argv.append(token)

    for key, value in sorted((arguments or {}).items()):
        if value is None or value == "":
            continue
        flag = f"--{str(key).replace('_', '-')}"
        if isinstance(value, bool):
            if value:
                argv.append(flag)
            continue
        argv.append(flag)
        argv.append(str(value))
    return argv


def run_skill_cli(
    skill_root: Path | str,
    command: list[Any],
    *,
    arguments: dict[str, Any] | None = None,
    cwd: str = ".",
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    env_extra: dict[str, str] | None = None,
) -> dict[str, Any]:
    """在 skill 根内执行 CLI，返回 ``{text, is_error, meta}``。"""
    root = Path(skill_root).resolve()
    if not root.is_dir():
        raise SkillError(f"技能目录不存在：{root}")

    work = _jail_path(root, cwd or ".")
    if not work.is_dir():
        raise SkillError(f"工作目录不存在：{cwd}")

    argv = build_command(root, command, arguments)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PYTHONIOENCODING": "utf-8",
        "LOCI_SKILL_ROOT": str(root),
    }
    for key in ("LOCI_DATA_DIR", "PALACE_DATA_DIR", "PALACE_MCP_JSON"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    if env_extra:
        env.update({str(k): str(v) for k, v in env_extra.items()})

    try:
        completed = subprocess.run(
            argv,
            cwd=str(work),
            env=env,
            capture_output=True,
            timeout=max(1, int(timeout_sec or DEFAULT_TIMEOUT_SEC)),
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "text": f"CLI 超时（>{timeout_sec}s）：{' '.join(argv)}",
            "is_error": True,
            "meta": {"argv": argv, "timeout": True},
        }
    except OSError as exc:
        return {
            "text": f"CLI 无法启动：{exc}",
            "is_error": True,
            "meta": {"argv": argv},
        }

    def _decode(raw: bytes | None) -> str:
        if not raw:
            return ""
        text = raw.decode("utf-8", errors="replace")
        if len(raw) > MAX_OUTPUT_BYTES:
            text = text[: MAX_OUTPUT_BYTES // 2] + "\n…(输出已截断)…\n"
        return text

    stdout = _decode(completed.stdout)
    stderr = _decode(completed.stderr)
    parts: list[str] = []
    if stdout.strip():
        parts.append(stdout)
    if stderr.strip():
        parts.append(f"[stderr]\n{stderr}")
    text = "\n".join(parts) if parts else f"(无输出，exit={completed.returncode})"
    if len(text.encode("utf-8", errors="ignore")) > MAX_OUTPUT_BYTES:
        text = text[: MAX_OUTPUT_BYTES // 2] + "\n…(输出已截断)…"

    return {
        "text": text,
        "is_error": completed.returncode != 0,
        "meta": {
            "argv": argv,
            "exit_code": completed.returncode,
            "cwd": str(work),
        },
    }
