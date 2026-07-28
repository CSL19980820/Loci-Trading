"""选股股票池（Universe）：板块范围 + ST 等横切过滤。

战法只声明形态；范围在 screen/backtest 入口统一应用。
北交所可归类为 bse，但永不进入选股产品面（产品确认 2026-07-28）。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Sequence

ALLOWED_BOARDS: frozenset[str] = frozenset({"main", "chi_next", "star"})
BOARD_LABELS: dict[str, str] = {
    "main": "主板",
    "chi_next": "创业板",
    "star": "科创板",
    "bse": "北交所",
    "other": "其他",
}

DEFAULT_BOARDS: tuple[str, ...] = ("main", "chi_next", "star")


class UniverseError(ValueError):
    """股票池规格非法（含试图纳入北交所）。"""


@dataclass(frozen=True)
class UniverseSpec:
    preset: str | None = "default_a_share"
    boards: tuple[str, ...] | None = None
    exclude_st: bool | None = None
    exclude_delisting: bool | None = None
    exclude_suspended: bool | None = None
    min_list_days: int | None = None
    codes_include: tuple[str, ...] | None = None
    codes_exclude: tuple[str, ...] | None = None


@dataclass
class UniverseFunnel:
    instruments_total: int = 0
    after_type: int = 0
    after_board: int = 0
    after_st: int = 0
    after_status: int = 0
    after_list_days: int = 0
    panel_columns: int = 0
    signals_true: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass
class ResolvedUniverse:
    codes: list[str]
    meta: dict[str, dict[str, Any]]
    spec: dict[str, Any]
    funnel: UniverseFunnel = field(default_factory=UniverseFunnel)


_PRESET_BASE: dict[str, Any] = {
    "boards": list(DEFAULT_BOARDS),
    "exclude_st": True,
    "exclude_delisting": True,
    "exclude_suspended": True,
    "min_list_days": 60,
}

PRESETS: dict[str, dict[str, Any]] = {
    "default_a_share": {**_PRESET_BASE, "label": "默认 A 股（剔 ST，无北交）"},
    "main_only": {**_PRESET_BASE, "boards": ["main"], "label": "仅主板"},
    "growth_only": {
        **_PRESET_BASE,
        "boards": ["chi_next", "star"],
        "label": "创业+科创",
    },
    "all_listed_boards": {
        **_PRESET_BASE,
        "label": "主板+创业+科创（仍无北交）",
    },
    "include_st": {
        **_PRESET_BASE,
        "exclude_st": False,
        "label": "默认范围但含 ST",
    },
}


def classify_board(code: str) -> str:
    """按代码前缀归类板块。bse 仅标记，选股 resolve 会丢弃。"""
    text = str(code).strip().zfill(6)
    if text.startswith(("688", "689")):
        return "star"
    if text.startswith(("300", "301")):
        return "chi_next"
    if text.startswith(("4", "8", "92")):
        return "bse"
    if text.isdigit() and len(text) == 6:
        return "main"
    return "other"


def is_st_name(name: str) -> bool:
    return "ST" in str(name).upper()


def is_delisting_name(name: str) -> bool:
    return "退" in str(name)


def board_label(bucket: str) -> str:
    return BOARD_LABELS.get(bucket, bucket)


def list_presets() -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for key, value in PRESETS.items():
        boards = list(value["boards"])
        sig = (tuple(boards), value["exclude_st"], value.get("min_list_days"))
        if sig in seen:
            continue
        seen.add(sig)
        out.append(
            {
                "id": key,
                "label": value.get("label", key),
                "boards": boards,
                "exclude_st": bool(value["exclude_st"]),
                "exclude_delisting": bool(value["exclude_delisting"]),
                "exclude_suspended": bool(value["exclude_suspended"]),
                "min_list_days": value.get("min_list_days"),
            }
        )
    return out


def parse_universe(
    raw: Mapping[str, Any] | UniverseSpec | None,
    *,
    codes: Sequence[str] | None = None,
) -> UniverseSpec:
    """把 API/Job 字典或 None 收成 UniverseSpec。未传 → default_a_share。"""
    if raw is None:
        spec = UniverseSpec()
    elif isinstance(raw, UniverseSpec):
        spec = raw
    else:
        boards = raw.get("boards")
        include = raw.get("codes_include")
        exclude = raw.get("codes_exclude")
        spec = UniverseSpec(
            preset=raw.get("preset", "default_a_share"),
            boards=tuple(boards) if boards is not None else None,
            exclude_st=raw.get("exclude_st"),
            exclude_delisting=raw.get("exclude_delisting"),
            exclude_suspended=raw.get("exclude_suspended"),
            min_list_days=raw.get("min_list_days"),
            codes_include=tuple(include) if include is not None else None,
            codes_exclude=tuple(exclude) if exclude is not None else None,
        )
    if codes:
        include = tuple(str(c).strip().zfill(6) for c in codes)
        spec = UniverseSpec(
            preset=spec.preset or "custom",
            boards=spec.boards,
            exclude_st=spec.exclude_st,
            exclude_delisting=spec.exclude_delisting,
            exclude_suspended=spec.exclude_suspended,
            min_list_days=spec.min_list_days,
            codes_include=include,
            codes_exclude=spec.codes_exclude,
        )
    return spec


def expand_spec(spec: UniverseSpec) -> dict[str, Any]:
    """展开预设并校验：禁止 bse。"""
    preset_name = spec.preset or "default_a_share"
    if preset_name == "custom":
        base = {**_PRESET_BASE}
    elif preset_name in PRESETS:
        base = {k: v for k, v in PRESETS[preset_name].items() if k != "label"}
    else:
        raise UniverseError(f"未知股票池预设：{preset_name}")

    boards = list(spec.boards) if spec.boards is not None else list(base["boards"])
    _reject_bse(boards)

    unknown = [b for b in boards if b not in ALLOWED_BOARDS]
    if unknown:
        raise UniverseError(f"不支持的板块：{unknown}（允许 {sorted(ALLOWED_BOARDS)}）")
    if not boards:
        raise UniverseError("至少选择一个板块（主板/创业板/科创板）")

    return {
        "preset": preset_name,
        "boards": boards,
        "exclude_st": (
            base["exclude_st"] if spec.exclude_st is None else bool(spec.exclude_st)
        ),
        "exclude_delisting": (
            base["exclude_delisting"]
            if spec.exclude_delisting is None
            else bool(spec.exclude_delisting)
        ),
        "exclude_suspended": (
            base["exclude_suspended"]
            if spec.exclude_suspended is None
            else bool(spec.exclude_suspended)
        ),
        "min_list_days": (
            base.get("min_list_days")
            if spec.min_list_days is None
            else int(spec.min_list_days)
        ),
        "codes_include": (
            [str(c).zfill(6) for c in spec.codes_include] if spec.codes_include else None
        ),
        "codes_exclude": (
            [str(c).zfill(6) for c in spec.codes_exclude] if spec.codes_exclude else None
        ),
    }


def _reject_bse(boards: Iterable[str]) -> None:
    if any(str(b).lower() == "bse" for b in boards):
        raise UniverseError("北交所已屏蔽，不可纳入选股股票池")


def _list_age_days(list_date: str, as_of: str | None) -> int | None:
    text = str(list_date or "").strip()[:10]
    if not text or text.count("-") != 2:
        return None
    try:
        listed = date.fromisoformat(text)
        end = date.fromisoformat(as_of[:10]) if as_of else date.today()
    except ValueError:
        return None
    return max(0, (end - listed).days)


def resolve_universe(
    store: Any,
    spec: UniverseSpec | Mapping[str, Any] | None = None,
    *,
    codes: Sequence[str] | None = None,
    as_of: str | None = None,
    skip_safety: bool = False,
) -> ResolvedUniverse:
    """从 instruments 解析可选代码集合。skip_safety 仅调试用。"""
    parsed = parse_universe(spec, codes=codes)
    final = expand_spec(parsed)
    funnel = UniverseFunnel()

    rows: list[dict[str, Any]] = list(
        store.list_instruments(instrument_type="STOCK", status="")
    )
    funnel.instruments_total = len(rows)
    funnel.after_type = len(rows)

    board_set = set(final["boards"])
    include = set(final["codes_include"] or [])
    exclude = set(final["codes_exclude"] or [])
    meta: dict[str, dict[str, Any]] = {}
    kept: list[str] = []

    after_board = after_st = after_status = after_list = 0

    for row in rows:
        code = str(row.get("code", "")).zfill(6)
        name = str(row.get("name", ""))
        bucket = classify_board(code)
        status = str(row.get("status") or "normal")

        if bucket not in board_set:
            continue
        after_board += 1

        st = is_st_name(name)
        if not skip_safety and final["exclude_st"] and st:
            continue
        after_st += 1

        if not skip_safety and final["exclude_delisting"]:
            if status == "delisted" or is_delisting_name(name):
                continue

        if not skip_safety and final["exclude_suspended"] and status == "suspended":
            continue
        after_status += 1

        min_days = final.get("min_list_days")
        if not skip_safety and min_days:
            age = _list_age_days(str(row.get("list_date") or ""), as_of)
            if age is not None and age < int(min_days):
                continue
        after_list += 1

        if include and code not in include:
            continue
        if exclude and code in exclude:
            continue

        kept.append(code)
        meta[code] = {
            "name": name,
            "board_bucket": bucket,
            "board_label": board_label(bucket),
            "is_st": st,
            "status": status,
        }

    funnel.after_board = after_board
    funnel.after_st = after_st
    funnel.after_status = after_status
    funnel.after_list_days = after_list

    # include 里有 instruments 没有的代码时，仍按代码归类补进（调试单票）
    if include:
        for code in sorted(include):
            if code in meta:
                continue
            bucket = classify_board(code)
            if bucket == "bse" or bucket not in board_set:
                continue
            if code in exclude:
                continue
            kept.append(code)
            meta[code] = {
                "name": "",
                "board_bucket": bucket,
                "board_label": board_label(bucket),
                "is_st": False,
                "status": "normal",
            }

    return ResolvedUniverse(codes=sorted(set(kept)), meta=meta, spec=final, funnel=funnel)


def universe_stats(store: Any) -> dict[str, Any]:
    """当前库各板块 / ST 计数，供仪表盘。"""
    rows = store.list_instruments(instrument_type="STOCK", status="")
    by_board: dict[str, int] = {k: 0 for k in ("main", "chi_next", "star", "bse", "other")}
    st_count = 0
    for row in rows:
        bucket = classify_board(str(row.get("code", "")))
        by_board[bucket] = by_board.get(bucket, 0) + 1
        if is_st_name(str(row.get("name", ""))):
            st_count += 1
    selectable = by_board["main"] + by_board["chi_next"] + by_board["star"]
    return {
        "total": len(rows),
        "by_board": by_board,
        "st_count": st_count,
        "selectable_default": selectable,  # 含 ST；实际入池还要剔 ST
        "bse_blocked": True,
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def enrich_picks(
    picks: list[dict[str, Any]], meta: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for pick in picks:
        code = str(pick.get("code", "")).zfill(6)
        info = meta.get(code, {})
        row = dict(pick)
        row["code"] = code
        row.setdefault("name", info.get("name", ""))
        row.setdefault("board_bucket", info.get("board_bucket", classify_board(code)))
        row.setdefault(
            "board_label",
            info.get("board_label") or board_label(str(row["board_bucket"])),
        )
        row.setdefault("is_st", bool(info.get("is_st", False)))
        out.append(row)
    return out
