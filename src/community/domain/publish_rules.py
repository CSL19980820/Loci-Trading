"""上架检查清单（机器可校验）。

抄的是 TradingView 的 *House Rules for script publishing* 与 QuantConnect 提交
Alpha 时的强制项，只保留**能被程序判定**的那些——「描述要写清楚思路」这类靠人看的
条款不在这里，避免给作者一个假的通过感。

清单（全部是硬门槛，任一不过就不给上架）：

- **必须有回测结果**：没有回测的「策略」只是一段代码，广场不是代码托管。
- **成交笔数 >= 30**：样本太小时胜率 / 夏普都没有统计意义（与
  ``src/backtest/application/metrics.py::SAMPLE_LOW`` 同口径）。
- **回测区间 >= 1 年**：一轮牛熊都没跨过的曲线不构成证据。
- **必须声明 entry_timing**：不声明就无法判断有没有前视，这是本仓策略铁律。
- **佣金 / 印花税 / 滑点不得为 0**：零成本回测是策略广场最常见的注水手法，
  高频小赚的策略扣掉成本后基本全是负的。
- **标题与摘要非空**：榜单与卡片要展示，空标题等于占位垃圾。
- **不得含外部联系方式**：广场不是引流场，微信 / QQ / 手机号 / 私域链接一律拦，
  这是「荐股拉群」灰产的入口。

本模块是纯函数：不读库、不看时间、不联网。同一份 payload 永远得到同一组
``RuleViolation``，因此可以在前端「发布前预检」与后端 ``publishing`` 两处共用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from src.community.domain.models import (
    KINDS,
    PublishRuleError,
    as_float,
    as_int,
    as_str,
)

#: 入场时点取值。**镜像** ``src.strategy.domain.base.ENTRY_TIMINGS``。
#:
#: 这里刻意复制而不是 ``from src.strategy import ENTRY_TIMINGS``：domain 层不许依赖
#: 兄弟上下文（那会把 pandas 与整个策略注册表拖进社区域的导入链）。漂移风险由
#: ``tests/community/test_publish_rules.py::test_entry_timings_mirror_strategy`` 兜住。
ENTRY_TIMINGS: tuple[str, ...] = ("open", "close", "next_open", "next_dip")

#: 最少可评估成交笔数。与 ``src/backtest/application/metrics.py::SAMPLE_LOW`` 一致。
MIN_TRADES = 30

#: 最短回测区间（自然日）。
MIN_BACKTEST_DAYS = 365

#: 文案长度上限。
MAX_TITLE_LEN = 80
MAX_SUMMARY_LEN = 500
MAX_TAGS = 8

#: 三项成本，缺一不可，且都必须 > 0。键名与 ``BacktestConfig`` / ``POST /api/backtest`` 一致。
COST_FIELDS = ("commission_bps", "stamp_duty_bps", "slippage_bps")
COST_LABELS = {
    "commission_bps": "佣金",
    "stamp_duty_bps": "印花税",
    "slippage_bps": "滑点",
}

#: 允许出现在正文里的链接域名（源码仓库、本仓文档）。其余一律按引流处理。
ALLOWED_LINK_HOSTS = ("github.com", "gitee.com", "gitlab.com", "docs.python.org")

#: 联系方式 / 引流特征。故意宽松：宁可误伤一个链接，也不让「加V看实盘」上广场。
CONTACT_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("contact_phone", r"(?<!\d)1[3-9]\d{9}(?!\d)", "疑似手机号"),
    ("contact_email", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "疑似邮箱"),
    (
        "contact_wechat",
        r"(微信|weixin|wechat|加\s*v|vx|威信|薇信)\s*[:：]?\s*[A-Za-z0-9_-]{4,}",
        "疑似微信号",
    ),
    ("contact_qq", r"(qq|QQ|扣扣)\s*[:：]?\s*\d{5,12}", "疑似 QQ 号"),
    (
        "contact_group",
        r"(加群|进群|私聊|私信我|付费群|荐股|带单|一对一指导|扫码|加\s*[vV微]|微信号|私域)",
        "疑似引流话术",
    ),
    ("contact_im", r"(t\.me/|telegram|whatsapp|公众号\s*[:：]?\s*\S+)", "疑似站外联系方式"),
)

_LINK_RE = re.compile(r"(https?://|www\.)([A-Za-z0-9.-]+)", re.IGNORECASE)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True, slots=True)
class RuleViolation:
    """一条不通过的检查项。

    ``field`` 指向表单字段，前端据此把红字标在对应输入框上；``code`` 稳定不变，
    前端与测试都按它断言，``message`` 可以改文案。
    """

    code: str
    field: str
    message: str
    severity: str = "error"

    @property
    def blocking(self) -> bool:
        return self.severity == "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "field": self.field,
            "message": self.message,
            "severity": self.severity,
        }


def _parse_day(raw: Any) -> date | None:
    text = as_str(raw).strip()[:10]
    if not _DATE_RE.match(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _pick(source: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in source and source[key] not in (None, ""):
            return source[key]
    return None


def _cost_value(backtest: Mapping[str, Any], key: str) -> Any:
    """成本既可能平铺在 backtest 上，也可能在 ``costs`` / ``config`` 子对象里。"""
    for scope in (backtest, backtest.get("costs"), backtest.get("config")):
        if isinstance(scope, Mapping) and scope.get(key) is not None:
            return scope.get(key)
    return None


def scan_contacts(text: str, *, field: str) -> list[RuleViolation]:
    """扫一段文案里的联系方式 / 引流特征。"""
    found: list[RuleViolation] = []
    body = as_str(text)
    if not body.strip():
        return found
    for code, pattern, label in CONTACT_PATTERNS:
        if re.search(pattern, body, re.IGNORECASE):
            found.append(RuleViolation(code, field, f"{label}，广场禁止站外引流"))
    for match in _LINK_RE.finditer(body):
        host = match.group(2).lower()
        if not any(
            host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_LINK_HOSTS
        ):
            found.append(
                RuleViolation("external_link", field, f"外部链接 {host} 不在白名单内，禁止引流")
            )
            break
    return found


def _check_text(payload: Mapping[str, Any]) -> list[RuleViolation]:
    out: list[RuleViolation] = []
    title = as_str(payload.get("title")).strip()
    summary = as_str(payload.get("summary")).strip()
    if not title:
        out.append(RuleViolation("title_required", "title", "标题不能为空"))
    elif len(title) > MAX_TITLE_LEN:
        out.append(RuleViolation("title_too_long", "title", f"标题不得超过 {MAX_TITLE_LEN} 字"))
    if not summary:
        out.append(RuleViolation("summary_required", "summary", "摘要不能为空"))
    elif len(summary) > MAX_SUMMARY_LEN:
        out.append(
            RuleViolation("summary_too_long", "summary", f"摘要不得超过 {MAX_SUMMARY_LEN} 字")
        )
    kind = as_str(payload.get("kind")).strip() or "screen"
    if kind not in KINDS:
        out.append(RuleViolation("kind_invalid", "kind", f"未知类型 {kind}"))
    tags = payload.get("tags") or []
    if isinstance(tags, (list, tuple)) and len(tags) > MAX_TAGS:
        out.append(RuleViolation("tags_too_many", "tags", f"标签最多 {MAX_TAGS} 个"))
    if not as_str(payload.get("source_text")).strip():
        out.append(RuleViolation("source_required", "source_text", "必须提供策略正文 / 参数说明"))
    for field_name in ("title", "summary", "release_notes"):
        out.extend(scan_contacts(payload.get(field_name), field=field_name))
    if isinstance(tags, (list, tuple)):
        for tag in tags:
            out.extend(scan_contacts(tag, field="tags"))
    return out


def _check_entry_timing(payload: Mapping[str, Any]) -> list[RuleViolation]:
    timing = as_str(payload.get("entry_timing")).strip()
    if not timing:
        return [
            RuleViolation(
                "entry_timing_required",
                "entry_timing",
                "必须声明入场时点（open/close/next_open/next_dip）",
            )
        ]
    if timing not in ENTRY_TIMINGS:
        return [
            RuleViolation(
                "entry_timing_invalid",
                "entry_timing",
                f"未知入场时点 {timing}，只能是 {', '.join(ENTRY_TIMINGS)}",
            )
        ]
    return []


def _check_backtest(payload: Mapping[str, Any]) -> list[RuleViolation]:
    backtest = payload.get("backtest")
    if not isinstance(backtest, Mapping) or not backtest:
        return [RuleViolation("backtest_required", "backtest", "必须附带回测结果才能上架")]
    out: list[RuleViolation] = []
    trades = as_int(_pick(backtest, "trades", "trade_count", "n"))
    if trades < MIN_TRADES:
        out.append(
            RuleViolation(
                "trades_too_few",
                "backtest.trades",
                f"成交笔数 {trades} < {MIN_TRADES}，样本不足以说明问题",
            )
        )
    start = _parse_day(_pick(backtest, "start", "start_date", "from"))
    end = _parse_day(_pick(backtest, "end", "end_date", "to"))
    if start is None or end is None:
        out.append(
            RuleViolation(
                "backtest_window_missing", "backtest.start", "回测区间缺失或不是 YYYY-MM-DD"
            )
        )
    elif (end - start).days < MIN_BACKTEST_DAYS:
        out.append(
            RuleViolation(
                "backtest_window_too_short",
                "backtest.start",
                f"回测区间 {(end - start).days} 天 < {MIN_BACKTEST_DAYS} 天",
            )
        )
    for key in COST_FIELDS:
        raw = _cost_value(backtest, key)
        if raw is None:
            out.append(
                RuleViolation(
                    f"cost_missing_{key}", f"backtest.{key}", f"必须声明{COST_LABELS[key]}"
                )
            )
            continue
        if as_float(raw) <= 0:
            out.append(
                RuleViolation(
                    f"cost_zero_{key}",
                    f"backtest.{key}",
                    f"{COST_LABELS[key]}为 0 的回测不作数（零成本是最常见的注水手法）",
                )
            )
    return out


def check_publish_ready(payload: Mapping[str, Any]) -> list[RuleViolation]:
    """跑完整份上架清单，返回全部未通过项（空列表 = 可以上架）。

    一次性返回所有问题而不是遇到第一条就退出：作者改一轮就能全改完，别让他
    「改一条、提交、又被拒」地来回七次。
    """
    if not isinstance(payload, Mapping):
        raise PublishRuleError("上架检查需要一个 payload 字典")
    violations: list[RuleViolation] = []
    violations.extend(_check_text(payload))
    violations.extend(_check_entry_timing(payload))
    violations.extend(_check_backtest(payload))
    return violations


def ensure_publishable(payload: Mapping[str, Any]) -> None:
    """检查不过就抛 ``PublishRuleError``（api 层映射成 422 + 逐条 violations）。"""
    violations = [item for item in check_publish_ready(payload) if item.blocking]
    if violations:
        raise PublishRuleError(
            f"上架检查未通过（{len(violations)} 项）",
            [item.to_dict() for item in violations],
        )


def checklist() -> list[dict[str, Any]]:
    """给前端「发布前须知」用的清单说明（静态文案，与实现同源）。"""
    return [
        {"code": "backtest_required", "text": "必须附带回测结果"},
        {"code": "trades_too_few", "text": f"可评估成交笔数 >= {MIN_TRADES}"},
        {"code": "backtest_window_too_short", "text": f"回测区间 >= {MIN_BACKTEST_DAYS} 天"},
        {"code": "entry_timing_required", "text": "必须声明 entry_timing"},
        {"code": "cost_zero_commission_bps", "text": "佣金 / 印花税 / 滑点均不得为 0"},
        {"code": "title_required", "text": "标题与摘要非空"},
        {"code": "external_link", "text": "正文不得含微信 / QQ / 手机号 / 站外链接"},
    ]
