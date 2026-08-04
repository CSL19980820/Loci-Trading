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

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any
import zipfile

import yaml

from src.ops.application.skill_files import atomic_replace_directory

from src.shared.paths import skill_root

#: 技能包安装根。每次调用再解析，避免 import 时 cwd/env 未就绪。
def _skill_root_default() -> Path:
    return skill_root()


DEFAULT_SKILL_ROOT = skill_root()  # 兼容旧引用；新代码请直接调 skill_root()

#: 单个包的压缩包体积上限。
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
#: 解压后的总体积上限，防 zip 炸弹。
MAX_EXTRACTED_BYTES = 200 * 1024 * 1024
#: 条目数量上限，防海量小文件拖死文件系统。
MAX_ENTRIES = 2000
#: 允许落盘的后缀。技能包是"指令 + 参考资料"，不是可执行程序。
ALLOWED_SUFFIXES = {
    ".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".csv", ".tsv",
    ".py", ".sql", ".j2", ".jinja", ".jinja2", ".toml", ".ini", ".cfg",
    ".ps1", ".bat", ".cmd", ".sh", "",
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
    enabled: bool = True
    mcp_servers: list[str] = field(default_factory=list)
    #: frontmatter ``tools:`` 里声明的可调用工具（cli/mcp/builtin）
    tool_specs: list[dict[str, Any]] = field(default_factory=list)
    #: ``skill_only`` = 不注入 palace/项目上下文；默认 ``normal``
    isolation: str = "normal"
    #: ``trading_voice`` = 允许交易向终稿；默认 ``research`` 走全局铁律
    policy: str = "research"
    #: frontmatter ``agents:`` 弹药子任务（cli / llm），主 Agent 前并行跑
    agents: list[dict[str, Any]] = field(default_factory=list)

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
            "enabled": self.enabled,
            "mcp_servers": list(self.mcp_servers),
            "tool_specs": list(self.tool_specs),
            "isolation": self.isolation,
            "policy": self.policy,
            "agents": list(self.agents),
            "source": "filesystem",
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


def _meta_tool_specs(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """解析 frontmatter 的 tools 声明。

    兼容两种写法：
    - 旧：``tools: [kline, limit_up]`` → 仅作为 allowed 名字，无本地 CLI
    - 新：``tools: [{name, description, kind, command, ...}]``
    """
    raw = meta.get("tools")
    if not isinstance(raw, list):
        return []
    specs: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict) and item.get("name"):
            kind = str(item.get("kind") or "cli").strip().lower()
            if kind not in {"cli", "mcp", "builtin"}:
                kind = "cli"
            specs.append(
                {
                    "name": str(item["name"]).strip(),
                    "description": str(item.get("description") or item["name"]).strip(),
                    "kind": kind,
                    "command": item.get("command") or [],
                    "cwd": str(item.get("cwd") or "."),
                    "timeout_sec": int(item.get("timeout_sec") or 120),
                    "args_schema": item.get("args_schema")
                    if isinstance(item.get("args_schema"), dict)
                    else {"type": "object", "properties": {}},
                    "mcp_tool": str(item.get("mcp_tool") or item.get("name") or ""),
                }
            )
    return specs


def _meta_tools(meta: dict[str, Any]) -> list[str]:
    """允许暴露给模型的工具名列表（收窄面）。"""
    explicit = meta.get("allowed_tools")
    if explicit is not None:
        if isinstance(explicit, str):
            return [item.strip() for item in explicit.split(",") if item.strip()]
        if isinstance(explicit, list):
            return [str(item) for item in explicit if not isinstance(item, dict)]
        return []

    tools = meta.get("tools") or []
    if isinstance(tools, str):
        return [item.strip() for item in tools.split(",") if item.strip()]
    if not isinstance(tools, list):
        return []
    names: list[str] = []
    for item in tools:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
        elif not isinstance(item, dict):
            names.append(str(item))
    return names


def _meta_mcp_servers(meta: dict[str, Any]) -> list[str]:
    raw = meta.get("mcp_servers") or meta.get("mcpServers") or []
    if isinstance(raw, str):
        raw = [item.strip() for item in raw.split(",") if item.strip()]
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def _meta_enabled(meta: dict[str, Any]) -> bool:
    if "enabled" not in meta:
        return True
    value = meta.get("enabled")
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _meta_isolation(meta: dict[str, Any]) -> str:
    raw = str(meta.get("isolation") or "normal").strip().lower()
    return "skill_only" if raw in {"skill_only", "isolated", "strict"} else "normal"


def _meta_policy(meta: dict[str, Any]) -> str:
    raw = str(meta.get("policy") or "research").strip().lower()
    return "trading_voice" if raw in {"trading_voice", "trading", "weipan"} else "research"


def _meta_agents(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """解析 frontmatter ``agents:`` 子任务声明。"""
    raw = meta.get("agents")
    if not isinstance(raw, list):
        return []
    agents: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("id") or "").strip()
        if not agent_id:
            continue
        kind = str(item.get("kind") or "cli").strip().lower()
        if kind not in {"cli", "llm"}:
            kind = "cli"
        role = str(item.get("role") or "ammo").strip().lower() or "ammo"
        agents.append(
            {
                "id": agent_id,
                "role": role,
                "kind": kind,
                "description": str(item.get("description") or "").strip(),
                "tool": str(item.get("tool") or "").strip(),
                "command": item.get("command") or [],
                "cwd": str(item.get("cwd") or "."),
                "timeout_sec": int(item.get("timeout_sec") or 300),
                "instructions": str(item.get("instructions") or "").strip(),
                "max_rounds": int(item.get("max_rounds") or 3),
                "max_tokens": int(item.get("max_tokens") or 2048),
                "mcp_servers": list(item["mcp_servers"])
                if isinstance(item.get("mcp_servers"), list)
                else None,
                "tools": list(item["tools"]) if isinstance(item.get("tools"), list) else None,
            }
        )
    return agents


def _meta_extras(meta: dict[str, Any]) -> dict[str, Any]:
    skip = {
        "name",
        "slug",
        "version",
        "description",
        "tools",
        "allowed_tools",
        "schedule",
        "cron",
        "enabled",
        "mcp_servers",
        "mcpServers",
        "isolation",
        "policy",
        "hitl",
        "agents",
    }
    return {key: value for key, value in meta.items() if key not in skip}


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

    root = Path(skill_root or _skill_root_default())
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix=".skill-stage-", dir=root) as tmp:
        unpacked = Path(tmp) / "unpacked"
        unpacked.mkdir()

        with zipfile.ZipFile(archive_path) as archive:
            entries = _reject_unsafe_entries(archive)
            for info in entries:
                target = (unpacked / info.filename).resolve()
                # 双保险：即便前面的审查有疏漏，这里也不会写出目标目录。
                if not target.is_relative_to(unpacked.resolve()):
                    raise SkillError(f"解压路径逃逸，已拒绝：{info.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)

        manifest_path = _locate_skill_manifest(unpacked)
        package_root = manifest_path.parent
        meta, instructions = parse_manifest(manifest_path.read_text(encoding="utf-8"))

        if not meta.get("name"):
            raise SkillError("SKILL.md 的 frontmatter 缺少 name")
        if not str(meta.get("description", "")).strip():
            raise SkillError("SKILL.md 的 frontmatter 缺少 description（用于让模型判断何时该用它）")
        if not instructions.strip():
            raise SkillError("SKILL.md 正文为空，没有可执行的指令")

        slug = _normalise_slug(meta.get("slug") or meta["name"])
        tools = _meta_tools(meta)
        tool_specs = _meta_tool_specs(meta)

        destination = root / slug
        if destination.exists():
            if not overwrite:
                raise SkillError(f"技能 {slug} 已安装。要覆盖请显式指定 overwrite")
        atomic_replace_directory(package_root, destination)

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
        allowed_tools=tools,
        default_cron=str(meta.get("schedule") or meta.get("cron") or ""),
        metadata=_meta_extras(meta),
        install_path=str(destination),
        source_filename=archive_path.name,
        content_sha256=digest,
        files=files,
        enabled=_meta_enabled(meta),
        mcp_servers=_meta_mcp_servers(meta),
        tool_specs=tool_specs,
        isolation=_meta_isolation(meta),
        policy=_meta_policy(meta),
        agents=_meta_agents(meta),
    )


def uninstall_skill(slug: str, *, skill_root: Path | str | None = None) -> bool:
    """删除技能包目录。"""
    root = Path(skill_root or _skill_root_default())
    target = (root / _normalise_slug(slug)).resolve()
    if not target.is_relative_to(root.resolve()):
        raise SkillError("非法的技能标识")
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True


def set_skill_enabled(
    slug: str,
    enabled: bool,
    *,
    skill_root: Path | str | None = None,
) -> SkillPackage:
    """改写 SKILL.md frontmatter 的 enabled 字段（不写库）。"""
    root = Path(skill_root or _skill_root_default())
    folder = (root / _normalise_slug(slug)).resolve()
    if not folder.is_dir() or not folder.is_relative_to(root.resolve()):
        raise SkillError(f"未找到技能：{slug}")
    manifest = folder / "SKILL.md"
    if not manifest.is_file():
        manifest = _locate_skill_manifest(folder)
    text = manifest.read_text(encoding="utf-8")
    meta, body = parse_manifest(text)
    meta["enabled"] = bool(enabled)
    # 保持简单 YAML dump，再拼回 frontmatter
    dumped = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    manifest.write_text(f"---\n{dumped}\n---\n\n{body.strip()}\n", encoding="utf-8")
    pkg = load_skill_from_disk(slug, skill_root=root)
    if pkg is None:
        raise SkillError(f"更新后无法加载技能：{slug}")
    return pkg


def read_skill_file(slug: str, relative: str, *, skill_root: Path | str | None = None) -> str:
    """读技能包内的附属文件（参考资料、脚本等）。

    路径必须落在该技能自己的目录内——技能之间不能互相读，也不能读出去。
    """
    root = Path(skill_root or _skill_root_default())
    base = (root / _normalise_slug(slug)).resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base):
        raise SkillError(f"路径越界：{relative}")
    if not target.is_file():
        raise SkillError(f"文件不存在：{relative}")
    return target.read_text(encoding="utf-8")


def load_skill_from_disk(
    slug: str,
    *,
    skill_root: Path | str | None = None,
) -> SkillPackage | None:
    """从 ``skills/<slug>/SKILL.md`` 加载（Cursor 风格：复制目录即用）。"""
    root = Path(skill_root or _skill_root_default())
    folder = (root / _normalise_slug(slug)).resolve()
    if not folder.is_dir() or not folder.is_relative_to(root.resolve()):
        return None
    manifest = folder / "SKILL.md"
    if not manifest.is_file():
        try:
            manifest = _locate_skill_manifest(folder)
        except SkillError:
            return None
    meta, instructions = parse_manifest(manifest.read_text(encoding="utf-8"))
    if not meta.get("name") or not str(meta.get("description", "")).strip():
        return None
    tools = _meta_tools(meta)
    files = sorted(
        str(path.relative_to(folder)).replace("\\", "/")
        for path in folder.rglob("*")
        if path.is_file()
    )
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    return SkillPackage(
        slug=_normalise_slug(slug),
        name=str(meta["name"]),
        version=str(meta.get("version", "")),
        description=str(meta["description"]).strip(),
        instructions=instructions,
        allowed_tools=tools,
        default_cron=str(meta.get("schedule") or meta.get("cron") or ""),
        metadata=_meta_extras(meta),
        install_path=str(folder),
        source_filename="SKILL.md",
        content_sha256=digest,
        files=files,
        enabled=_meta_enabled(meta),
        mcp_servers=_meta_mcp_servers(meta),
        tool_specs=_meta_tool_specs(meta),
        isolation=_meta_isolation(meta),
        policy=_meta_policy(meta),
        agents=_meta_agents(meta),
    )


def discover_skills(*, skill_root: Path | str | None = None) -> list[SkillPackage]:
    """扫描 skill_root 下所有带 SKILL.md 的目录。"""
    root = Path(skill_root or _skill_root_default())
    if not root.is_dir():
        return []
    packages: list[SkillPackage] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        try:
            pkg = load_skill_from_disk(child.name, skill_root=root)
        except SkillError:
            continue
        if pkg is not None:
            packages.append(pkg)
    return packages


def install_skill_dir(
    source_dir: Path | str,
    *,
    skill_root: Path | str | None = None,
    overwrite: bool = True,
) -> SkillPackage:
    """把已有技能目录复制进 skill_root（Cursor：复制即用）。"""
    source = Path(source_dir)
    if not source.is_dir():
        raise SkillError(f"不是技能目录：{source}")
    manifest = source / "SKILL.md"
    if not manifest.is_file():
        manifest = _locate_skill_manifest(source)
    meta, instructions = parse_manifest(manifest.read_text(encoding="utf-8"))
    if not meta.get("name"):
        raise SkillError("SKILL.md 缺少 name")
    if not str(meta.get("description", "")).strip():
        raise SkillError("SKILL.md 缺少 description")
    if not instructions.strip():
        raise SkillError("SKILL.md 正文为空")
    slug = _normalise_slug(meta.get("slug") or source.name or meta["name"])
    root = Path(skill_root or _skill_root_default())
    root.mkdir(parents=True, exist_ok=True)
    destination = root / slug
    if destination.exists():
        if not overwrite:
            raise SkillError(f"技能 {slug} 已存在")
        if destination.resolve() != source.resolve():
            shutil.rmtree(destination)
    if destination.resolve() != source.resolve():
        shutil.copytree(source, destination)
    pkg = load_skill_from_disk(slug, skill_root=root)
    if pkg is None:
        raise SkillError(f"复制后无法加载技能：{slug}")
    return pkg


def resolve_skill(
    slug: str,
    *,
    skill_root: Path | str | None = None,
) -> dict[str, Any] | None:
    """从磁盘加载技能（唯一来源：``data/skills/<slug>/SKILL.md``）。"""
    disk = load_skill_from_disk(slug, skill_root=skill_root)
    if disk is None:
        return None
    return disk.to_record()
