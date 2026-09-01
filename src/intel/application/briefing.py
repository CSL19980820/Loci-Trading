"""悟道 AI 简报（``briefings`` 工具）取数、解析与纯文本渲染。

## 为什么单独一个模块

「把简报转成 txt」这件事有两个容易踩空的地方，都与推送渠道无关，所以留在 intel：

1. **不传 `format` 时 `content[0].text` 只有一行 headline，还带省略号**——拿它当
   简报正文发出去，用户看到的是被截断的一句话。全文只在
   ``detailLevel=raw`` 的 ``structuredContent.rawData[0].content.fullContent``，
   而那是一段 **Markdown**（``### 【30秒核心】`` / ``【隔夜要闻】`` / ``【市场预判】``
   / ``### 【🔥 今日热点】`` / ``### 【⚠️ 风险提示】`` / ``### 【📅 今日日程】``）。
2. **「今天这一档还没生成」不是错误**：``success=true``、``data.count=0``、
   正文 ``暂无简报``。判成失败会让 09:10 那条任务天天刷红；判成成功又会推一条
   空简报。所以解析层必须把「没生成」单独表达出来（``parse_briefing`` 返回
   ``None``，调用方记 ``skipped``）。

## 实测记录（2026-08-31，生产 Key，`type` 逐档打过）

| 档 | 悟道 `type` | 生成时点 | 全文实测 |
|---|---|---|---|
| 开盘简报 | ``opening`` | 09:00 | 3424 字 / 8323 字节 |
| 午间简报 | ``midday`` | 12:00 | 1530 字 / 3787 字节 |
| 收盘简报 | ``closing`` | 15:30 | 1359 字 / 3211 字节 |
| 晚间简报 | ``evening`` | 21:00 | 1611 字 / 3939 字节 |

`date` 不传默认今天；`type` 不传返回全部档（本模块一律显式传，避免把四档拼一起）。

## 纪律

简报是**AI 生成的旁注**，不是事实来源。这里只做「取回来 + 转成人能读的 txt」，
不入库当权威口径、不参与复盘数字、不喂给选股引擎。这与
``docs/research/2026-08-wudao-mcp-utilization-assessment.md`` 里
「``briefings`` 不建议入库当事实」是同一条：**可以转发，不可以当账**。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

#: 四档简报：内部 slot → (悟道 type, 中文名, 悟道侧生成时点)。
#:
#: **slot 是本仓的键，type 是服务端的键**，两者不要混用：服务端 `type` 还认
#: open/morning/premarket 等别名（都映射早盘），我们固定用列里这四个。
BRIEFING_SLOTS: dict[str, tuple[str, str, str]] = {
    "open": ("opening", "开盘简报", "09:00"),
    "midday": ("midday", "午间简报", "12:00"),
    "close": ("closing", "收盘简报", "15:30"),
    "evening": ("evening", "晚间简报", "21:00"),
}

#: 悟道 briefings 工具名。
BRIEFING_TOOL = "briefings"


def resolve_slot(value: Any) -> str:
    """把 Job 配置里的档位写法归一成 slot 键；写错的一律回落开盘档。"""
    text = str(value or "").strip().lower()
    if text in BRIEFING_SLOTS:
        return text
    for slot, (kind, _label, _at) in BRIEFING_SLOTS.items():
        if text == kind:
            return slot
    aliases = {
        "opening": "open",
        "morning": "open",
        "premarket": "open",
        "pre_market": "open",
        "noon": "midday",
        "closing": "close",
        "eod": "close",
        "night": "evening",
    }
    return aliases.get(text, "open")


def slot_label(slot: str) -> str:
    return BRIEFING_SLOTS.get(slot, BRIEFING_SLOTS["open"])[1]

def briefing_arguments(slot: str, *, trade_date: str | None = None) -> dict[str, Any]:
    """按 schema 拼参数。

    ``detailLevel=raw`` 是**必须**的，也是唯一的旋钮：standard 档的 ``hotTopics`` 只剩
    标题、没有 ``content``，更没有 ``fullContent``；少了它推出去的「简报」就是一句核心摘要。

    **刻意不传 ``format``**。两条实测理由：

    1. 正文那行 headline 我们不用，全文走 ``structuredContent.rawData[0].content.fullContent``
       （``fetch._resolve_structured`` 已专门把 ``rawData`` 保住，不再随解包丢掉）。
    2. ``format=json`` 会把整份数据在 ``text`` 里再抄一遍，而 ``McpClient`` 对正文有
       ``MAX_TOOL_RESULT_CHARS=12_000`` 截断——raw 档 JSON 正文实测 41KB，截断后 JSON
       必然解不出来，等于白占一倍缓存体积还什么都拿不到。
    """
    kind = BRIEFING_SLOTS.get(slot, BRIEFING_SLOTS["open"])[0]
    args: dict[str, Any] = {"type": kind, "detailLevel": "raw"}
    day = str(trade_date or "").strip()[:10]
    if day:
        args["date"] = day
    return args


@dataclass(frozen=True)
class BriefingDoc:
    """一档已发布的简报。``full_text`` 是 Markdown 原文，可能为空。"""

    slot: str
    kind: str
    label: str
    date: str
    time: str
    status: str
    core_summary: str
    full_text: str
    generated_at: str
    hot_topics: list[dict[str, str]] = field(default_factory=list)
    risks: list[dict[str, str]] = field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        """防重指纹：同一档、同一天、同一次生成只推一次。

        带上 ``generated_at``：悟道重算过一次（内容变了）应该允许再推一条。
        """
        raw = "|".join([self.kind, self.date, self.time, self.generated_at])
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def _structured(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    structured = payload.get("structured")
    if isinstance(structured, dict):
        return structured
    return None


def _text_json(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """``format=json`` 时正文本身就是完整 JSON——**全文的唯一可靠来源**。

    ``call_mcp_tool`` 落库前会把 ``structured`` 解包成服务端的 ``data`` 段
    （``fetch._resolve_structured``），而 ``rawData`` 是 ``data`` 的兄弟节点，解包时
    一起没了。所以这里必须能从 ``text`` 再解一次；解析失败（被截断、不是 JSON）
    返回 None，由调用方退回 ``structured`` 那条路。
    """
    if not isinstance(payload, dict):
        return None
    text = str(payload.get("text") or "").strip()
    if not text.startswith("{"):
        return None
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _sources(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """同一份结果的两条解析入口：解包后的 ``structured`` + ``text`` 里的完整 JSON。"""
    return [
        source
        for source in (_structured(payload), _text_json(payload))
        if isinstance(source, dict)
    ]


def _first_item(structured: dict[str, Any]) -> dict[str, Any] | None:
    data = structured.get("data")
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    return item
    items = structured.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                return item
    return None


def _raw_content(structured: dict[str, Any]) -> dict[str, Any] | None:
    raw = structured.get("rawData")
    if isinstance(raw, list):
        for row in raw:
            if isinstance(row, dict) and isinstance(row.get("content"), dict):
                return row["content"]
    return None


def _text_rows(value: Any, *keys: str) -> list[dict[str, str]]:
    """把 hotTopics / risks 这类列表压成 ``{title, content}`` 行，丢掉 ``_id`` 之类。"""
    out: list[dict[str, str]] = []
    if not isinstance(value, list):
        return out
    for row in value:
        if not isinstance(row, dict):
            continue
        item = {key: str(row.get(key) or "").strip() for key in keys}
        if any(item.values()):
            out.append(item)
    return out


def parse_briefing(payload: dict[str, Any] | None, *, slot: str) -> BriefingDoc | None:
    """解析一档简报；**未生成 / 取数失败一律返回 None**（调用方记 skipped）。"""
    if not isinstance(payload, dict) or payload.get("is_error"):
        return None
    sources = _sources(payload)
    if not sources:
        return None
    item = next((found for found in map(_first_item, sources) if found), None)
    if item is None:
        return None
    status = str(item.get("status") or "").strip()
    if status and status != "published":
        return None
    content = next((found for found in map(_raw_content, sources) if found), None)
    full_text = ""
    if content:
        full_text = str(content.get("fullContent") or "").strip()
    core_summary = str(item.get("coreSummary") or "").strip()
    if not (full_text or core_summary):
        return None
    kind, label, _at = BRIEFING_SLOTS.get(slot, BRIEFING_SLOTS["open"])
    # raw 段的 hotTopics 带 `content` 长文（standard 段只有标题），优先它；但 raw
    # 段可能整块缺字段，缺了要退回 items 那份，别把「有标题」读成「没热点」。
    topics_src = (content or {}).get("hotTopics") or item.get("hotTopics")
    risks_src = (content or {}).get("risks") or item.get("risks")
    return BriefingDoc(
        slot=slot,
        kind=str(item.get("type") or kind).strip() or kind,
        label=label,
        date=str(item.get("date") or "").strip()[:10],
        time=str(item.get("time") or "").strip(),
        status=status or "published",
        core_summary=core_summary,
        full_text=full_text,
        generated_at=str(item.get("generatedAt") or "").strip(),
        hot_topics=_text_rows(topics_src, "title", "content"),
        risks=_text_rows(risks_src, "content", "level"),
    )


#: Markdown 行内标记：加粗、行内代码、图片/链接。
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_MD_BOLD = re.compile(r"\*{1,3}([^*]+)\*{1,3}")
_MD_CODE = re.compile(r"`([^`]*)`")
_MD_HEAD = re.compile(r"^\s{0,3}#{1,6}\s*")
_MD_BULLET = re.compile(r"^(\s*)[-*+]\s+")
#: 分割线单独一行（``---`` / ``***``）：转成 txt 后是一串没有意义的横杠。
#: 注意它必须在列表符号之前判掉，否则 ``---`` 会被当成列表项变成「· --」。
_MD_RULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_BLANKS = re.compile(r"\n{3,}")


def markdown_to_text(markdown: str) -> str:
    """Markdown → 纯文本。企微 text 不渲染 Markdown，原样发过去满屏 ``###`` 和 ``**``。

    只做减法，不重排：标题去井号、列表换成「· 」、链接只留可见文字（悟道正文里的
    ``[名称(代码)](https://…/quote/000001)`` 会变成 ``名称(代码)``）。缩进保留，
    嵌套层级是简报的信息结构。
    """
    text = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for raw_line in text.split("\n"):
        if _MD_RULE.match(raw_line):
            lines.append("")
            continue
        line = _MD_HEAD.sub("", raw_line)
        line = _MD_LINK.sub(r"\1", line)
        line = _MD_BOLD.sub(r"\1", line)
        line = _MD_CODE.sub(r"\1", line)
        line = _MD_BULLET.sub(r"\1· ", line)
        lines.append(line.rstrip())
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()


def _digest_text(doc: BriefingDoc) -> str:
    """没有 ``fullContent`` 时的兜底：核心 + 热点 + 风险。"""
    parts: list[str] = []
    if doc.core_summary:
        parts.append("【核心】\n" + doc.core_summary)
    topics = [row for row in doc.hot_topics if row.get("title")]
    if topics:
        body = []
        for index, row in enumerate(topics, start=1):
            detail = row.get("content") or ""
            body.append(f"{index}. {row['title']}" + (f"\n   {detail}" if detail else ""))
        parts.append("【热点】\n" + "\n".join(body))
    risks = [row for row in doc.risks if row.get("content")]
    if risks:
        body = []
        for row in risks:
            level = row.get("level") or ""
            body.append("· " + row["content"] + (f"（{level}）" if level else ""))
        parts.append("【风险】\n" + "\n".join(body))
    return "\n\n".join(parts).strip()


def briefing_body_text(doc: BriefingDoc, *, prefer_full: bool = True) -> str:
    """简报正文的纯文本形态。``prefer_full=False`` 只发摘要（少几条企微消息）。"""
    if prefer_full and doc.full_text:
        return markdown_to_text(doc.full_text)
    digest = _digest_text(doc)
    if digest:
        return digest
    return markdown_to_text(doc.full_text) or doc.core_summary


def briefing_header(doc: BriefingDoc) -> str:
    """正文首行：哪一档、哪一天、几点生成、谁生成的。

    **必须标明是 AI 生成的旁注**：这条消息与本仓引擎算出来的复盘数字混在同一个
    企微群里，不标就会被当成系统结论。
    """
    stamp = " ".join(part for part in (doc.date, doc.time) if part)
    return f"{doc.label}｜{stamp}｜悟道 AI 生成，仅作旁注"


def fetch_briefing_payload(
    *,
    slot: str,
    server: str = "wudao",
    trade_date: str | None = None,
    market_store: Any | None = None,
    pool: str = "structured",
    cache: bool = True,
    cache_max_age_minutes: int | None = None,
) -> dict[str, Any]:
    """取一档简报的原始载荷（带配额与缓存；悟道不可用时软失败，不抛）。"""
    from src.intel.application.fetch import call_mcp_tool

    return call_mcp_tool(
        BRIEFING_TOOL,
        briefing_arguments(slot, trade_date=trade_date),
        server=server,
        pool=pool,  # type: ignore[arg-type]
        cache=cache,
        cache_max_age_minutes=cache_max_age_minutes,
        market_store=market_store,
    )


__all__ = [
    "BRIEFING_SLOTS",
    "BRIEFING_TOOL",
    "BriefingDoc",
    "briefing_arguments",
    "briefing_body_text",
    "briefing_header",
    "fetch_briefing_payload",
    "markdown_to_text",
    "parse_briefing",
    "resolve_slot",
    "slot_label",
]
