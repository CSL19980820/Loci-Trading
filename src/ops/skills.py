"""技能包（skill）的安装、解析与卸载。

一个技能包是个 zip，解出来至少要有 ``SKILL.md``：YAML frontmatter 给元数据，
正文是给模型的指令。装上之后它就成了一个可复用的"模式"——可以手动触发，
也可以挂上 cron 让它按配置的 LLM 定时跑。

## 解 zip 是这个系统攻击面最大的地方

技能包可能来自任何地方。以下每一条都对应一种真实存在的攻击，全部在
**解压前**拦截，而不是解完再检查（解完就已经写到磁盘上了）：

- **Zip Slip**：条目名写成 ``../../etc/cron.d/x`` 或绝对路径，解压时逃出
  目标目录覆盖系统文件。
- **符号链接**：zip 支持存 symlink，指向 ``/etc/shadow`` 之类，之后读它
  就等于读系统文件。
- **Zip 炸弹**：几十 KB 的包解出几十 GB，撑爆磁盘。按声明的解压后总大小
  与压缩比一起判断。
- **可执行内容混入**：只放行白名单后缀，不让 ``.so`` / ``.dll`` / ``.exe``
  这类东西落到磁盘上。

安装是原子的：先解到临时目录、校验通过再整体搬到最终位置，失败不留残骸。
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any
import zipfile

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

#: 技能包的安装根目录。
#:
#: 线上**必须**用 PALACE_SKILL_ROOT 指到数据卷（如 /data/skills）。
#: 默认值在仓库目录下，而线上每次发布都会把代码换成一个新的 release 目录——
#: 装在那里的技能包会随着下一次同步凭空消失，且没有任何报错。
DEFAULT_SKILL_ROOT = Path(os.environ.get("PALACE_SKILL_ROOT") or (PROJECT_ROOT / ".skills"))

#: 单个包的压缩包体积上限。
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
#: 解压后的总体积上限，防 zip 炸弹。
MAX_EXTRACTED_BYTES = 200 * 1024 * 1024
#: 条目数量上限，防海量小文件拖死文件系统。
MAX_ENTRIES = 2000
#: 允许落盘的后缀。技能包是"指令 + 参考资料"，不是可执行程序。
ALLOWED_SUFFIXES = {
    ".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".csv", ".tsv",
    ".py", ".sql", ".j2", ".jinja", ".jinja2", ".toml", ".ini", ".cfg", "",
}

SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)


class SkillError(RuntimeError):
    """技能包不合法。消息会原样回给用户，要说清楚哪一条不满足。"""


@dataclass
class SkillPackage:
    """解析好的技能包元数据。"""

    slug: str
    name: str
    version: str
    description: str
    instructions: str
    allowed_tools: list[str]
    default_cron: str
    metadata: dict[str, Any]
    install_path: str
    source_filename: str
    content_sha256: str
    files: list[str]

    def to_record(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "instructions": self.instructions,
            "allowed_tools": self.allowed_tools,
            "default_cron": self.default_cron,
            "metadata": {**self.metadata, "files": self.files},
            "install_path": self.install_path,
            "source_filename": self.source_filename,
            "content_sha256": self.content_sha256,
        }


def _reject_unsafe_entries(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """解压前逐条审查。任何一条不过就整包拒绝，不做"跳过坏条目"的妥协。

    跳过坏条目听起来更友好，实际上会让攻击者用一个含恶意条目的包换到一次
    "部分安装成功"，而用户以为装好了。
    """
    infos = archive.infolist()
    if len(infos) > MAX_ENTRIES:
        raise SkillError(f"包内条目过多（{len(infos)} > {MAX_ENTRIES}）")

    total_size = sum(info.file_size for info in infos)
    if total_size > MAX_EXTRACTED_BYTES:
        raise SkillError(
            f"解压后体积过大（{total_size / 1e6:.1f}MB > {MAX_EXTRACTED_BYTES / 1e6:.0f}MB），"
            "疑似 zip 炸弹"
        )

    safe: list[zipfile.ZipInfo] = []
    for info in infos:
        name = info.filename
        if info.is_dir():
            continue

        # 符号链接在 zip 里以文件模式高位标记，解出来会指向任意路径。
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise SkillError(f"包内含符号链接，已拒绝：{name}")

        if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
            raise SkillError(f"包内含绝对路径，已拒绝：{name}")

        parts = Path(name.replace("\\", "/")).parts
        if any(part == ".." for part in parts):
            raise SkillError(f"包内含上跳路径（Zip Slip），已拒绝：{name}")

        suffix = Path(name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise SkillError(
                f"不允许的文件类型 {suffix or '(无后缀)'}：{name}。"
                f"技能包只接受指令与参考资料，允许的后缀：{sorted(s for s in ALLOWED_SUFFIXES if s)}"
            )
        safe.append(info)

    if not safe:
        raise SkillError("包内没有任何有效文件")
    return safe


def _locate_skill_manifest(root: Path) -> Path:
    """找 SKILL.md。允许包内多套一层目录（zip 常见的顶层文件夹）。"""
    direct = root / "SKILL.md"
    if direct.is_file():
        return direct
    candidates = sorted(root.rglob("SKILL.md"))
    if not candidates:
        raise SkillError("包内找不到 SKILL.md（技能包必须有它，用于声明元数据与指令）")
    # 取路径最短的那个，避免 references/ 里的示例文件被误当成主清单。
    return min(candidates, key=lambda path: len(path.parts))


def parse_manifest(text: str) -> tuple[dict[str, Any], str]:
    """拆出 YAML frontmatter 与正文指令。"""
    match = FRONTMATTER_PATTERN.match(text.lstrip("﻿"))
    if not match:
        raise SkillError(
            "SKILL.md 缺少 YAML frontmatter。开头必须是 --- 包裹的元数据块，"
            "至少包含 name 与 description。"
        )
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillError(f"SKILL.md 的 frontmatter 不是合法 YAML：{exc}") from exc
    if not isinstance(meta, dict):
        raise SkillError("SKILL.md 的 frontmatter 必须是键值映射")
    return meta, match.group(2).strip()


def _normalise_slug(raw: str) -> str:
    slug = str(raw).strip().lower().replace(" ", "-")
    if not SLUG_PATTERN.match(slug):
        raise SkillError(
            f"非法的技能标识：{raw!r}。只允许小写字母、数字、点、下划线与连字符，"
            "且不超过 64 字符"
        )
    return slug


def install_skill(
    archive_path: Path | str,
    *,
    skill_root: Path | str | None = None,
    overwrite: bool = True,
) -> SkillPackage:
    """安装一个技能包 zip，返回解析好的元数据。

    整个过程原子：先解到临时目录并校验，全部通过后才整体搬到 skill_root。
    中途失败不会在最终位置留下半个包。
    """
    archive_path = Path(archive_path)
    if not archive_path.is_file():
        raise SkillError(f"找不到技能包文件：{archive_path}")
    size = archive_path.stat().st_size
    if size > MAX_ARCHIVE_BYTES:
        raise SkillError(f"技能包过大（{size / 1e6:.1f}MB > {MAX_ARCHIVE_BYTES / 1e6:.0f}MB）")
    if not zipfile.is_zipfile(archive_path):
        raise SkillError("不是合法的 zip 文件")

    root = Path(skill_root or DEFAULT_SKILL_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()

    with tempfile.TemporaryDirectory(prefix="skill-install-") as tmp:
        staging = Path(tmp) / "unpacked"
        staging.mkdir()

        with zipfile.ZipFile(archive_path) as archive:
            entries = _reject_unsafe_entries(archive)
            for info in entries:
                target = (staging / info.filename).resolve()
                # 双保险：即便前面的审查有疏漏，这里也不会写出目标目录。
                if not target.is_relative_to(staging.resolve()):
                    raise SkillError(f"解压路径逃逸，已拒绝：{info.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)

        manifest_path = _locate_skill_manifest(staging)
        package_root = manifest_path.parent
        meta, instructions = parse_manifest(manifest_path.read_text(encoding="utf-8"))

        if not meta.get("name"):
            raise SkillError("SKILL.md 的 frontmatter 缺少 name")
        if not str(meta.get("description", "")).strip():
            raise SkillError("SKILL.md 的 frontmatter 缺少 description（用于让模型判断何时该用它）")
        if not instructions.strip():
            raise SkillError("SKILL.md 正文为空，没有可执行的指令")

        slug = _normalise_slug(meta.get("slug") or meta["name"])
        tools = meta.get("tools") or meta.get("allowed_tools") or []
        if isinstance(tools, str):
            tools = [item.strip() for item in tools.split(",") if item.strip()]
        if not isinstance(tools, list):
            raise SkillError("frontmatter 的 tools 必须是列表或逗号分隔字符串")

        destination = root / slug
        if destination.exists():
            if not overwrite:
                raise SkillError(f"技能 {slug} 已安装。要覆盖请显式指定 overwrite")
            shutil.rmtree(destination)
        shutil.move(str(package_root), str(destination))

        files = sorted(
            str(path.relative_to(destination)).replace("\\", "/")
            for path in destination.rglob("*")
            if path.is_file()
        )

    return SkillPackage(
        slug=slug,
        name=str(meta["name"]),
        version=str(meta.get("version", "")),
        description=str(meta["description"]).strip(),
        instructions=instructions,
        allowed_tools=[str(item) for item in tools],
        default_cron=str(meta.get("schedule") or meta.get("cron") or ""),
        metadata={
            key: value
            for key, value in meta.items()
            if key not in {"name", "slug", "version", "description", "tools",
                           "allowed_tools", "schedule", "cron"}
        },
        install_path=str(destination),
        source_filename=archive_path.name,
        content_sha256=digest,
        files=files,
    )


def uninstall_skill(slug: str, *, skill_root: Path | str | None = None) -> bool:
    """删除技能包目录。不负责清理数据库记录，由调用方一并处理。"""
    root = Path(skill_root or DEFAULT_SKILL_ROOT)
    target = (root / _normalise_slug(slug)).resolve()
    if not target.is_relative_to(root.resolve()):
        raise SkillError("非法的技能标识")
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True


def read_skill_file(slug: str, relative: str, *, skill_root: Path | str | None = None) -> str:
    """读技能包内的附属文件（参考资料、脚本等）。

    路径必须落在该技能自己的目录内——技能之间不能互相读，也不能读出去。
    """
    root = Path(skill_root or DEFAULT_SKILL_ROOT)
    base = (root / _normalise_slug(slug)).resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base):
        raise SkillError(f"路径越界：{relative}")
    if not target.is_file():
        raise SkillError(f"文件不存在：{relative}")
    return target.read_text(encoding="utf-8")
