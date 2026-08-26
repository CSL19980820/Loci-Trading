"""战法监测调参：每一段都可启停，每个阈值都可改。

存 ops.db `meta`（键 ``watch_tuning:{slug}``），不新开表——调参是小体量配置，
丢了回落默认即可，不属于账本事实。

**只保留白名单里的键**：SKILL.md 或前端传进来的野字段一律丢弃，避免调参面
悄悄变成第二套配置协议。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.ops.application.skill_watch.defaults import (
    DEFAULT_GATE_PARAMS,
    DEFAULT_ROLE_PARAMS,
)
from src.ops.application.paper_policy.auction_gap import (
    DEFAULT_ABANDON_GAP_PCT,
    DEFAULT_DOWNGRADE_GAP_PCT,
)

SETTING_PREFIX = "watch_tuning:"

#: 每段流水线都能单独关掉。关掉不是「跳过校验」，而是明确的降级语义。
DEFAULT_STAGES: dict[str, bool] = {
    #: 龙空龙闸门。关掉 = 不做市场择时，风险自负
    "market_gate": True,
    #: 开盘啦区间强度软过滤（选题材偏好持续强势；失败 fail-open）
    "theme_interval": True,
    #: 09:15-09:25 竞价确认龙头是否还在
    "auction_confirm": True,
    #: 角色留痕（可回看角色演进）
    "role_history": True,
    #: 是否产出纸面候选（关掉则只出观察信号）
    "paper_candidates": True,
}

DEFAULT_SCAN: dict[str, float] = {
    "theme_limit": 3,
    #: 主线名额里留几席给「近窗持续强势」的细分题材（0=只按盘中强度选大类板）
    "interval_theme_slots": 1,
    "member_limit": 6,
    "candidate_score": 65,
    "max_candidates": 2,
    "max_observe": 2,
    "observe_min_score": 50,
    "max_observe_pool": 5,
    "observe_replace_margin": 8,
    "observe_alert_drop_pct": -5.0,
    "observe_max_miss_days": 2,
    "observe_max_same_theme": 2,
    "observe_max_age_days": 10,
}

#: 龙回头·二波监测。阈值全部来自回测分档，改动请同步
#: `docs/research/2026-08-dragon-second-wave-live-alert-spec.md`。
DEFAULT_SECOND_WAVE: dict[str, float] = {
    #: 入池：20 日涨幅进过全市场前 N。**别调小**——收紧到 5 会让分档验证失去统计力
    "pool_top_n": 10,
    #: 入池后监控多少个交易日
    "watch_days": 20,
    #: 触发均线。MA5 太敏感、MA20/60 太迟钝，MA10 的两段皆正格最多
    "ma_window": 10,
    #: 市场宽度下限（全市场上涨家数占比 %）。单此一条把全期收益从 −3.72% 拉到 +80.02%
    "breadth_min": 55.0,
    #: 距 20 日最高价的天数上限。要新高附近洗盘，不是深回踩
    "peak_days_max": 3,
    #: 强度下限，低于此分不出提醒。实测 00-44 档均净 −0.962%、45+ 各档均为正
    "min_strength": 45,
    #: 成交额底线（万元），滤掉不可交易的票
    "amount_min_wan": 3000,
}

DEFAULT_AUCTION: dict[str, float] = {
    #: 竞价高开超过这个幅度算强确认
    "strong_gap_pct": 3.0,
    #: 低开超过这个幅度降级
    "downgrade_gap_pct": DEFAULT_DOWNGRADE_GAP_PCT,
    #: 低开超过这个幅度直接放弃
    "abandon_gap_pct": DEFAULT_ABANDON_GAP_PCT,
}

#: 数值键的合法区间。越界不报错，钳到边界——调参面板不该因手滑变成 500。
_RANGES: dict[str, tuple[float, float]] = {
    "promotion_attack": (0.0, 1.0),
    "promotion_empty": (0.0, 1.0),
    "broken_empty": (0.0, 1.0),
    "broken_attack_max": (0.0, 1.0),
    "min_height_attack": (1.0, 15.0),
    "theme_strength_attack": (0.0, 200.0),
    "theme_strength_empty": (0.0, 200.0),
    "breadth_attack": (0.0, 1.0),
    "breadth_empty": (0.0, 1.0),
    "temperature_attack": (0.0, 100.0),
    "temperature_empty": (0.0, 100.0),
    "leader_min_level": (1.0, 10.0),
    "leader_min_gain_20": (0.0, 200.0),
    "secondary_min_level": (1.0, 10.0),
    "weakened_drawdown": (1.0, 90.0),
    "failed_ma20_ratio": (0.5, 1.0),
    "failed_vol_ratio": (0.5, 10.0),
    "theme_limit": (1.0, 10.0),
    "interval_theme_slots": (0.0, 3.0),
    "member_limit": (1.0, 20.0),
    "candidate_score": (0.0, 100.0),
    "max_candidates": (0.0, 10.0),
    "max_observe": (0.0, 5.0),
    "observe_min_score": (0.0, 100.0),
    "max_observe_pool": (0.0, 20.0),
    "observe_replace_margin": (0.0, 30.0),
    "observe_alert_drop_pct": (-20.0, 0.0),
    "observe_max_miss_days": (1.0, 10.0),
    "observe_max_same_theme": (1.0, 20.0),
    "observe_max_age_days": (3.0, 60.0),
    "strong_gap_pct": (0.0, 10.0),
    "downgrade_gap_pct": (-10.0, 0.0),
    "abandon_gap_pct": (-20.0, 0.0),
    "pool_top_n": (3.0, 50.0),
    "watch_days": (5.0, 60.0),
    "ma_window": (3.0, 120.0),
    "breadth_min": (0.0, 100.0),
    "peak_days_max": (0.0, 20.0),
    "min_strength": (0.0, 100.0),
    "amount_min_wan": (0.0, 100_000.0),
}

_INT_KEYS = {
    "theme_limit",
    "interval_theme_slots",
    "member_limit",
    "max_candidates",
    "max_observe",
    "max_observe_pool",
    "observe_max_miss_days",
    "observe_max_same_theme",
    "observe_max_age_days",
    "pool_top_n",
    "watch_days",
    "ma_window",
    "peak_days_max",
    "min_strength",
    "amount_min_wan",
}

#: 段开关的中文名与含义。前端不再自己抄一份，避免加了开关界面看不到。
STAGE_META: dict[str, tuple[str, str]] = {
    "market_gate": ("龙空龙闸门", "关掉 = fail-closed 禁开仓（非「自负放行」）"),
    "theme_interval": ("区间强度", "四象限选细分主线并软过滤；关掉=仅盘中 strength 选大类板"),
    "auction_confirm": ("竞价确认", "09:15-09:30 用集合竞价复核龙头"),
    "role_history": ("角色留痕", "追加角色观测，可回看角色演进"),
    "paper_candidates": ("纸面候选", "关掉则不出可买/观察预案项，仅监测信号"),
}

SECTION_META: dict[str, str] = {
    "scan": "扫描范围",
    "gate": "闸门阈值",
    "roles": "角色判定",
    "auction": "竞价阈值",
    "second_wave": "二波监测",
}

#: 三套命名预设。balanced 与 ``default_tuning()`` 一致；另两套在其上偏移。
PRESET_META: list[dict[str, str]] = [
    {
        "id": "aggressive",
        "label": "偏进攻",
        "summary": "闸门更松、候选分线略低、候选上限略高",
    },
    {
        "id": "balanced",
        "label": "中性",
        "summary": "系统默认档，攻守均衡",
    },
    {
        "id": "defensive",
        "label": "偏防守",
        "summary": "闸门更严、竞价放弃更紧、候选更少",
    },
]

_PRESET_IDS = frozenset(item["id"] for item in PRESET_META)

#: 相对默认档的偏移；空 dict 表示 balanced 直接用默认。
_PRESET_PATCHES: dict[str, dict[str, dict[str, float]]] = {
    "balanced": {},
    "aggressive": {
        "gate": {
            "promotion_attack": 0.30,
            "promotion_empty": 0.15,
            "broken_empty": 0.50,
            "broken_attack_max": 0.35,
            "theme_strength_attack": 50.0,
            "breadth_attack": 0.50,
            "temperature_attack": 50.0,
        },
        "roles": {"weakened_drawdown": 30.0},
        "scan": {"candidate_score": 60.0, "max_candidates": 3.0},
        "auction": {"abandon_gap_pct": -6.0},
    },
    "defensive": {
        "gate": {
            "promotion_attack": 0.40,
            "promotion_empty": 0.25,
            "broken_empty": 0.40,
            "broken_attack_max": 0.25,
            "theme_strength_attack": 70.0,
            "breadth_attack": 0.60,
            "temperature_attack": 70.0,
        },
        "roles": {"weakened_drawdown": 20.0},
        "scan": {"candidate_score": 70.0, "max_candidates": 1.0},
        "auction": {"abandon_gap_pct": -4.0},
    },
}

#: 每个阈值的中文名与输入步长。**新增阈值必须在这里登记**，否则调参面板不显示。
FIELD_META: dict[str, tuple[str, float]] = {
    "theme_limit": ("主线题材数", 1),
    "interval_theme_slots": ("区间强势名额", 1),
    "member_limit": ("每题材成分数", 1),
    "candidate_score": ("候选形态分线", 5),
    "max_candidates": ("可买上限", 1),
    "max_observe": ("当日新观察上限", 1),
    "observe_min_score": ("观察最低分", 5),
    "max_observe_pool": ("观察池总量", 1),
    "observe_replace_margin": ("替换分差", 1),
    "observe_alert_drop_pct": ("观察预警跌幅%", 0.5),
    "observe_max_miss_days": ("未命中移出天数", 1),
    "observe_max_same_theme": ("观察同题材上限", 1),
    "observe_max_age_days": ("观察最长寿命", 1),
    "promotion_attack": ("晋级率·进攻", 0.05),
    "promotion_empty": ("晋级率·空仓", 0.05),
    "broken_empty": ("炸板率·空仓", 0.05),
    "broken_attack_max": ("炸板率·进攻上限", 0.05),
    "min_height_attack": ("梯队高度下限", 1),
    "theme_strength_attack": ("主线强度·进攻", 5),
    "theme_strength_empty": ("主线强度·空仓", 5),
    "breadth_attack": ("市场宽度·进攻", 0.05),
    "breadth_empty": ("市场宽度·空仓", 0.05),
    "temperature_attack": ("市场温度·进攻", 5),
    "temperature_empty": ("市场温度·空仓", 5),
    "leader_min_level": ("龙头最低连板", 1),
    "leader_min_gain_20": ("龙头最低20日涨幅", 5),
    "secondary_min_level": ("中军最低连板", 1),
    "weakened_drawdown": ("走弱回撤线", 5),
    "failed_ma20_ratio": ("破位MA20系数", 0.01),
    "failed_vol_ratio": ("破位量比", 0.1),
    "strong_gap_pct": ("强确认高开%", 0.5),
    "downgrade_gap_pct": ("降级低开%", 0.5),
    "abandon_gap_pct": ("放弃低开%", 0.5),
    "pool_top_n": ("入池·涨幅前N", 1),
    "watch_days": ("监控交易日", 1),
    "ma_window": ("触发均线", 1),
    "breadth_min": ("市场宽度下限%", 1),
    "peak_days_max": ("距高点天数上限", 1),
    "min_strength": ("强度下限", 5),
    "amount_min_wan": ("成交额下限(万)", 500),
}

_SECTIONS: dict[str, dict[str, float]] = {
    "gate": DEFAULT_GATE_PARAMS,
    "roles": DEFAULT_ROLE_PARAMS,
    "scan": DEFAULT_SCAN,
    "auction": DEFAULT_AUCTION,
    "second_wave": DEFAULT_SECOND_WAVE,
}


def default_tuning() -> dict[str, Any]:
    return {
        "stages": dict(DEFAULT_STAGES),
        **{name: dict(defaults) for name, defaults in _SECTIONS.items()},
    }


def list_presets() -> list[dict[str, str]]:
    """预设清单（id / 中文标签 / 摘要），供调参面板一键套用。"""
    return [dict(item) for item in PRESET_META]


def preset_tuning(preset_id: str) -> dict[str, Any]:
    """按预设 id 生成完整调参；未知 id 抛 ValueError。"""
    if preset_id not in _PRESET_IDS:
        raise ValueError(f"未知预设：{preset_id}")
    patch = _PRESET_PATCHES.get(preset_id) or {}
    merged = default_tuning()
    for section_name, fields in patch.items():
        if section_name in _SECTIONS and isinstance(fields, Mapping):
            merged[section_name] = {**merged[section_name], **dict(fields)}
    return normalize_tuning(merged)


def tuning_schema() -> dict[str, Any]:
    """字段清单交给后端描述，前端照着渲染。

    只有一份字段表，新增阈值不会出现「代码里能调、界面上看不到」。
    """
    return {
        "presets": list_presets(),
        "stages": [
            {
                "key": key,
                "label": STAGE_META.get(key, (key, ""))[0],
                "hint": STAGE_META.get(key, (key, ""))[1],
                "default": default,
            }
            for key, default in DEFAULT_STAGES.items()
        ],
        "sections": [
            {
                "name": name,
                "label": SECTION_META.get(name, name),
                "fields": [
                    {
                        "key": key,
                        "label": FIELD_META.get(key, (key, 1))[0],
                        "step": FIELD_META.get(key, (key, 1))[1],
                        "min": _RANGES.get(key, (None, None))[0],
                        "max": _RANGES.get(key, (None, None))[1],
                        "default": default,
                    }
                    for key, default in defaults.items()
                ],
            }
            for name, defaults in _SECTIONS.items()
        ],
    }


def _clamp(key: str, value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if number != number:  # NaN
        return fallback
    low, high = _RANGES.get(key, (-1e9, 1e9))
    number = max(low, min(high, number))
    return float(int(number)) if key in _INT_KEYS else number


def normalize_tuning(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """把任意输入收敛成合法调参；未知键丢弃，越界值钳到边界。"""
    source = dict(raw or {})
    stages = source.get("stages") if isinstance(source.get("stages"), Mapping) else {}
    out: dict[str, Any] = {
        "stages": {
            key: bool(stages.get(key, fallback)) for key, fallback in DEFAULT_STAGES.items()
        }
    }
    for name, defaults in _SECTIONS.items():
        section = source.get(name) if isinstance(source.get(name), Mapping) else {}
        out[name] = {
            key: _clamp(key, section.get(key, fallback), float(fallback))
            for key, fallback in defaults.items()
        }
    # 降级带须浅于放弃带（如 -2 > -5）；配反则把放弃压到降级外侧 0.5pct
    auction = out.get("auction") or {}
    downgrade = float(auction.get("downgrade_gap_pct", -2.0))
    abandon = float(auction.get("abandon_gap_pct", -5.0))
    if abandon >= downgrade:
        auction["abandon_gap_pct"] = _clamp(
            "abandon_gap_pct",
            downgrade - 0.5,
            float(_SECTIONS["auction"]["abandon_gap_pct"]),
        )
        out["auction"] = auction
    return out


def load_tuning(store: Any, slug: str) -> dict[str, Any]:
    """读回调参；没存过就给默认档，保证扫描器永远拿到完整结构。"""
    if store is None:
        return default_tuning()
    try:
        saved = store.get_setting(f"{SETTING_PREFIX}{slug}", None)
    except Exception:  # noqa: BLE001 — 配置读失败不该让监测整体挂掉
        saved = None
    return normalize_tuning(saved if isinstance(saved, Mapping) else None)


def save_tuning(store: Any, slug: str, patch: Mapping[str, Any] | None) -> dict[str, Any]:
    """按段合并保存：只传 stages 不会把阈值重置回默认。"""
    current = load_tuning(store, slug)
    merged = {
        "stages": {**current["stages"], **dict((patch or {}).get("stages") or {})},
        **{
            name: {**current[name], **dict((patch or {}).get(name) or {})}
            for name in _SECTIONS
        },
    }
    normalized = normalize_tuning(merged)
    store.set_setting(f"{SETTING_PREFIX}{slug}", normalized)
    return normalized


def reset_tuning(store: Any, slug: str) -> dict[str, Any]:
    store.delete_setting(f"{SETTING_PREFIX}{slug}")
    return default_tuning()


def apply_preset(store: Any, slug: str, preset_id: str) -> dict[str, Any]:
    """整档套用命名预设并写入 meta；段开关保留当前值。"""
    current = load_tuning(store, slug)
    normalized = preset_tuning(preset_id)
    normalized["stages"] = dict(current["stages"])
    store.set_setting(f"{SETTING_PREFIX}{slug}", normalized)
    return normalized


def stage_enabled(tuning: Mapping[str, Any] | None, stage: str) -> bool:
    stages = (tuning or {}).get("stages")
    if not isinstance(stages, Mapping):
        return bool(DEFAULT_STAGES.get(stage, True))
    return bool(stages.get(stage, DEFAULT_STAGES.get(stage, True)))


def section(tuning: Mapping[str, Any] | None, name: str) -> dict[str, Any]:
    values = (tuning or {}).get(name)
    defaults = _SECTIONS.get(name, {})
    if not isinstance(values, Mapping):
        return dict(defaults)
    return {**defaults, **{k: v for k, v in values.items() if k in defaults}}


__all__ = [
    "DEFAULT_AUCTION",
    "DEFAULT_SCAN",
    "DEFAULT_STAGES",
    "FIELD_META",
    "PRESET_META",
    "SECTION_META",
    "SETTING_PREFIX",
    "STAGE_META",
    "apply_preset",
    "default_tuning",
    "list_presets",
    "preset_tuning",
    "tuning_schema",
    "load_tuning",
    "normalize_tuning",
    "reset_tuning",
    "save_tuning",
    "section",
    "stage_enabled",
]
