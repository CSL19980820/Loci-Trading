"""One synthetic stop event; no market data, strategy selection or return calculation."""
from pathlib import Path
import hashlib
import json
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.backtest.application.engine import _one_word_masks, _resolve_exit  # noqa: E402
from src.backtest.application.execution_contract import strict_price_masks  # noqa: E402
from src.backtest.domain.models import BacktestConfig  # noqa: E402


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    sources = ["src/backtest/application/engine.py", "src/backtest/application/execution_contract.py",
               "src/backtest/domain/models.py"]
    before = {name: digest(ROOT / name) for name in sources}
    days = ["T-1", "T", "T+1", "T+2", "T+3"]
    data = {
        "open": np.array([10., 10., 9.8, 9.7, 9.6])[:, None],
        "high": np.array([10.2, 10.2, 10., 9.8, 9.7])[:, None],
        "low": np.array([9.8, 9.8, 9., 9.3, 9.5])[:, None],
        "close": np.array([10., 10., 9., 9.6, 9.6])[:, None],
        "volume": np.full((5, 1), 1000.),
    }
    factor = np.ones((5, 1))
    cfg = BacktestConfig(hold_days=3, stop_loss_pct=-6., take_profit_pct=None,
                         strict_limit_prices=True, economic_returns=True)
    rows = []
    for late_close in (9., 9.2):
        close = data["close"].copy()
        close[2, 0] = late_close
        _, close_blocked, known = strict_price_masks(data["open"], close, factor, ["600000"], data["volume"])
        _, native_one_word = _one_word_masks(data["high"], data["low"], close)
        assert known[2, 0] and not native_one_word[2, 0]
        for kind, mask in (("strict_current_close_mask", close_blocked), ("native_one_word_mask", native_one_word)):
            day, price, reason = _resolve_exit(
                col=0, entry_idx=1, entry_price=10., planned_exit=4, cfg=cfg,
                high_a=data["high"], low_a=data["low"], close_a=close, open_a=data["open"],
                one_word_down=mask, volume_a=data["volume"], last_index=4)
            rows.append({"late_close_T_plus_1": late_close, "mask": kind,
                         "T_plus_1_blocked": bool(mask[2, 0]), "native_one_word_on_T_plus_1": False,
                         "exit_day": days[day], "exit_price": price, "exit_reason": reason})
    assert rows[0]["exit_day"] == "T+2" and rows[0]["exit_price"] == 9.6
    assert all(row["exit_day"] == "T+1" and abs(row["exit_price"]-9.4) < 1e-12 for row in rows[1:])
    assert all(row["exit_reason"] == "stop_loss" for row in rows)
    assert before == {name: digest(ROOT / name) for name in sources}
    output = {
        "kind": "one_synthetic_event_with_late_close_intervention",
        "real_market_data_read": False, "alternative_real_returns_computed": False,
        "production_or_frozen_source_changed": False, "source_sha256": before,
        "days": days, "bars": {key: values[:, 0].tolist() for key, values in data.items()},
        "entry_day": "T", "entry_basis": 10., "stop_trigger": 9.4,
        "known_T_plus_1_lower_limit": 9., "planned_expiry": "T+3",
        "compatible_synthetic_intraday_prefix": [9.8, 10., 9.4, 9.],
        "intervention": "Keep T+1 open/high/low and all other days equal; only its final close is9.0 or9.2.",
        "current_results": rows,
        "interpretation": "Current strict close mask changes the earlier stop's simulated execution. Native OHLC fills are still proxies, not evidence of real fillability.",
    }
    target = Path(__file__).with_name("synthetic-event.json")
    with target.open("x", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"one_synthetic_event": True, "results": rows}, ensure_ascii=False))


if __name__ == "__main__":
    main()
