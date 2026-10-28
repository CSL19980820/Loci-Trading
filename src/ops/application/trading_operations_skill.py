"""交易智能体默认操作上下文；正文来自同一宿主技能，角色只提供权限和偏好。"""
from __future__ import annotations

import hashlib
import json

from src.ops.application.skill_manifest import parse_manifest
from src.shared.paths import PROJECT_ROOT

SKILL_SLUG = "trading-operations"
ANALYSIS_PHASES = {"premarket", "auction", "review", "daily", "weekly", "weekly_review", "research",
                   "planning", "retrospective", "experience", "consultation"}


def load_trading_operations_skill(*, paper: bool = True, phase: str = "intraday",
                                  analysis_only: bool = False) -> tuple[str, dict]:
    text = (PROJECT_ROOT / "templates" / "agent-workbench" / SKILL_SLUG / "SKILL.md").read_text(encoding="utf-8")
    manifest, body = parse_manifest(text)
    if manifest.get("slug") != SKILL_SLUG or manifest.get("capability") != "agent_workbench":
        raise ValueError("内置交易操作技能元数据不匹配")
    policy = {"mode": "paper_quote" if paper else "order_book", "phase": phase,
              "analysis_only": analysis_only, "price_tolerance_pct": 2}
    receipt = {"slug": SKILL_SLUG, "name": manifest["name"], "version": manifest["version"],
               "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "phase": phase,
               "execution_mode": policy["mode"], "loaded": True, "default_context": True}
    instructions = ("【实际加载的默认交易技能：trading-operations】\n" + body
                    + "\n【本轮执行模式；账户和阶段权限以实际输入为准】\n"
                    + json.dumps({"execution_policy": policy,
                                  "builtin_skill": {key: receipt[key] for key in ("slug", "version", "sha256")}},
                                 ensure_ascii=False))
    return instructions, receipt


def prepare_trading_operations_skill(payload: dict, *, paper: bool = True, phase: str | None = None,
                                     analysis_only: bool | None = None) -> tuple[dict, str, dict]:
    phase = phase or payload.get("phase") or "intraday"
    if analysis_only is None:
        analysis_only = bool(payload.get("analysis_only") or phase in ANALYSIS_PHASES)
    instructions, receipt = load_trading_operations_skill(paper=paper, phase=phase, analysis_only=analysis_only)
    enriched = {**payload, "execution_policy": {"mode": receipt["execution_mode"], "phase": phase,
                "analysis_only": analysis_only, "price_tolerance_pct": 2}}
    return enriched, instructions, receipt
