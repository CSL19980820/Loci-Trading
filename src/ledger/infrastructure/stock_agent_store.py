"""多智能体模拟账本：租户隔离、运行租约、配置/账户双版本与原子成交。"""
from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.ledger.domain.guardian_account import check_guardian_account, new_guardian_account
from src.ledger.domain.stock_agent_account import pending_watchlist, validate_stock_agent_transition
from src.ledger.infrastructure.stock_agent_history import (
    StockAgentConflict, StockAgentHistoryMixin, agent_now, encode_agent_json,
)
from src.ledger.infrastructure.stock_agent_schema import SCHEMA
from src.shared.paths import palace_db


def _exceeds_agent_limits(cfg: dict[str, Any], previous: dict[str, Any], state: dict[str, Any]) -> bool:
    """本轮使持仓/观察/当日入选数量越过上限并继续变大时拒绝提交。

    下调上限后账户本就越限：卖出、撤观察等不增加数量的收敛动作仍须能落账，
    否则每轮都在提交处失败，止损也执行不了。
    """
    def selected(value: dict[str, Any]) -> tuple[str, int]:
        today = value.get("selected_today") or {}
        return str(today.get("date") or ""), len(today.get("codes") or [])

    def grew(limit: Any, before: int, after: int) -> bool:
        return bool(limit) and after > limit and after > before

    day, chosen = selected(state)
    previous_day, previous_chosen = selected(previous)
    return (grew(cfg["temporary_position_limit"], len(previous.get("positions", [])), len(state["positions"]))
            or grew(cfg["watch_limit"], len(previous.get("watchlist", [])), len(state.get("watchlist", [])))
            or grew(cfg["daily_selection_limit"], previous_chosen if previous_day == day else 0, chosen))


class StockAgentStore(StockAgentHistoryMixin):
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or palace_db())
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), timeout=15, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def __enter__(self) -> StockAgentStore:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def _write(self) -> Iterator[None]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    @staticmethod
    def _profile(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["config"] = json.loads(item.pop("config_json"))
        item["state"] = json.loads(item.pop("state_json"))
        if item["config"].get("kind") == "leader":
            item["state"]["watchlist"] = pending_watchlist(item["state"])
        item["latest_actions"] = json.loads(item.pop("latest_actions_json"))
        item["history_kept"] = item["total_runs"] - item["cleaned_runs"]
        return item

    def get(self, agent_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM stock_agent_profiles WHERE id=?", (agent_id,)).fetchone()
        if row is None:
            raise KeyError("智能体不存在")
        return self._profile(row)

    def list_profiles(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM stock_agent_profiles WHERE archived=0 OR ? ORDER BY created_at,id",
                                 (int(include_archived),)).fetchall()
        return [self._profile(row) for row in rows]

    def create(self, config: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        timestamp = agent_now(now).isoformat()
        amount = config.get("initial_capital_cents")
        if type(amount) is not int or not 10_000 <= amount <= 100_000_000_000:
            raise ValueError("初始模拟资金无效")
        state = new_guardian_account()
        state.update(initial_capital_cents=amount, cash_cents=amount, equity_cents=amount,
                     watchlist=[], selected_today={"date": timestamp[:10], "codes": []})
        check_guardian_account(state)
        agent_id = "agent-" + uuid4().hex
        with self._write():
            total, active = self.conn.execute("SELECT COUNT(*),COALESCE(SUM(archived=0),0) FROM stock_agent_profiles").fetchone()
            if active >= 20 or total >= 100:
                raise ValueError("每个租户最多20个在用智能体、100个含归档智能体")
            if self.conn.execute("SELECT 1 FROM stock_agent_profiles WHERE archived=0 AND json_extract(config_json,'$.name')=?",
                                 (config["name"],)).fetchone():
                raise StockAgentConflict("已有同名智能体，请使用不同名称")
            self.conn.execute("INSERT INTO stock_agent_profiles(id,config_json,state_json,created_at,updated_at) VALUES(?,?,?,?,?)",
                              (agent_id, encode_agent_json(config), encode_agent_json(state), timestamp, timestamp))
            self.conn.execute("INSERT INTO stock_agent_funding VALUES(?,?,?,?,?)", (agent_id, "initial", timestamp, "initial", amount))
            self._snapshot(agent_id, state, timestamp)
        return self.get(agent_id)

    def update_config(self, agent_id: str, config: dict[str, Any], *, revision: int) -> dict[str, Any]:
        with self._write():
            current = self.get(agent_id)
            if current["revision"] != revision or current["archived"]:
                raise StockAgentConflict("配置已变化或智能体已归档，请刷新后重试")
            for key in ("kind", "initial_capital_cents"):
                if config[key] != current["config"][key]:
                    raise ValueError("创建后不能改类型或初始资金；追加资金请使用资金流水入口")
            if self.conn.execute("SELECT 1 FROM stock_agent_profiles WHERE id<>? AND archived=0 AND json_extract(config_json,'$.name')=?",
                                 (agent_id, config["name"])).fetchone():
                raise StockAgentConflict("已有同名智能体")
            state = current["state"]
            if ((config["temporary_position_limit"] and len(state["positions"]) > config["temporary_position_limit"])
                    or (config["watch_limit"] and len(state.get("watchlist", [])) > config["watch_limit"])):
                raise ValueError("当前持仓或观察数量超过新上限，请先由智能体收敛后再降低")
            self.conn.execute("UPDATE stock_agent_profiles SET config_json=?,revision=revision+1,updated_at=?,cleanup_at=NULL WHERE id=?",
                              (encode_agent_json(config), agent_now().isoformat(), agent_id))
        return self.get(agent_id)

    def deposit(self, agent_id: str, amount_cents: int, request_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        if type(amount_cents) is not int or not 1 <= amount_cents <= 100_000_000_000 or not 8 <= len(request_id) <= 80:
            raise ValueError("追加金额或幂等请求号无效")
        timestamp = agent_now(now).isoformat()
        with self._write():
            current = self.get(agent_id)
            if current["archived"]:
                raise StockAgentConflict("归档智能体不能追加资金")
            previous = self.conn.execute("SELECT amount_cents FROM stock_agent_funding WHERE agent_id=? AND request_id=?",
                                         (agent_id, request_id)).fetchone()
            if previous:
                if previous[0] != amount_cents:
                    raise StockAgentConflict("同一追加请求号不能使用不同金额")
                return current
            state = current["state"]
            if state["initial_capital_cents"] + amount_cents > 100_000_000_000:
                raise ValueError("累计模拟投入超过账户上限")
            # 撮合内核的 initial_capital 字段代表累计注资；真正初始资金留在不可变配置和流水中。
            for key in ("initial_capital_cents", "cash_cents", "equity_cents"):
                state[key] += amount_cents
            check_guardian_account(state)
            self.conn.execute("INSERT INTO stock_agent_funding VALUES(?,?,?,?,?)", (agent_id, request_id, timestamp, "deposit", amount_cents))
            self.conn.execute("UPDATE stock_agent_profiles SET state_json=?,state_version=state_version+1,updated_at=? WHERE id=?",
                              (encode_agent_json(state), timestamp, agent_id))
            self._snapshot(agent_id, state, timestamp)
        return self.get(agent_id)

    def archive(self, agent_id: str, *, revision: int) -> None:
        with self._write():
            current = self.get(agent_id)
            if current["revision"] != revision:
                raise StockAgentConflict("配置已变化，请刷新")
            if current["state"]["positions"]:
                raise ValueError("仍有模拟持仓，不能归档并停止管理")
            config = {**current["config"], "enabled": False}
            self.conn.execute("UPDATE stock_agent_profiles SET archived=1,revision=revision+1,config_json=?,updated_at=? WHERE id=?",
                              (encode_agent_json(config), agent_now().isoformat(), agent_id))

    def claim_run(self, agent_id: str, slot: str, phase: str, *, now: datetime | None = None) -> dict[str, Any] | None:
        current_time = agent_now(now)
        if not slot.startswith(current_time.date().isoformat() + ":") or len(slot) > 160:
            raise ValueError("只允许认领当天的运行槽，历史日记清理后不能重放旧成交")
        timestamp, run_id = current_time.isoformat(), uuid4().hex
        with self._write():
            profile = self.get(agent_id)
            if profile["archived"] or not profile["config"].get("enabled"):
                return None
            if profile["active_run"] and (profile["lease_until"] or "") > timestamp:
                return None
            if self.conn.execute("SELECT 1 FROM stock_agent_runs WHERE agent_id=? AND slot=?", (agent_id, slot)).fetchone():
                return None
            active = self.conn.execute("SELECT COUNT(*) FROM stock_agent_profiles WHERE active_run IS NOT NULL AND lease_until>?", (timestamp,)).fetchone()[0]
            if active >= 2:
                return None
            if profile["active_run"]:
                self.conn.execute("UPDATE stock_agent_runs SET status='failed',finished_at=?,summary=? WHERE id=? AND status='running'",
                                  (timestamp, "运行租约超时；未提交的交易没有落账", profile["active_run"]))
            lease = (current_time + timedelta(seconds=int(profile["config"].get("timeout_seconds", 240)) + 60)).isoformat()
            self.conn.execute("""INSERT INTO stock_agent_runs(id,agent_id,slot,phase,started_at,status,config_revision,state_version)
                VALUES(?,?,?,?,?,'running',?,?)""", (run_id, agent_id, slot, phase, timestamp, profile["revision"], profile["state_version"]))
            self.conn.execute("""UPDATE stock_agent_profiles SET active_run=?,lease_until=?,total_runs=total_runs+1,
                latest_at=?,latest_phase=?,latest_status='running' WHERE id=?""", (run_id, lease, timestamp, phase, agent_id))
        return {**self.get(agent_id), "run_id": run_id}

    def assert_owner(self, agent_id: str, run_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        profile = self.get(agent_id)
        run = self.conn.execute("SELECT * FROM stock_agent_runs WHERE id=? AND agent_id=?", (run_id, agent_id)).fetchone()
        if (run is None or run["status"] != "running" or profile["active_run"] != run_id
                or (profile["lease_until"] or "") <= agent_now(now).isoformat()
                or profile["archived"] or not profile["config"].get("enabled")
                or profile["revision"] != run["config_revision"] or profile["state_version"] != run["state_version"]):
            raise StockAgentConflict("运行失效：配置、账户资金或运行所有权已改变，本轮不提交成交")
        return profile

    def finish_run(self, agent_id: str, run_id: str, state: dict[str, Any], result: dict[str, Any],
                   *, now: datetime | None = None, before_commit: Callable[[], None] | None = None) -> None:
        current_time = agent_now(now)
        check_guardian_account(state)
        detail = encode_agent_json(result)
        fills, actions = result.get("fills", []), result.get("actions", [])[:12]
        summary, timestamp = str(result.get("summary") or "本轮无操作")[:2000], current_time.isoformat()
        with self._write():
            profile = self.assert_owner(agent_id, run_id, now=current_time)
            if state["initial_capital_cents"] != profile["state"]["initial_capital_cents"]:
                raise StockAgentConflict("交易不能修改累计投入")
            cfg = profile["config"]
            if cfg.get("kind") == "leader":
                state = {**state, "watchlist": pending_watchlist(state)}
                phase = self.conn.execute("SELECT phase FROM stock_agent_runs WHERE id=?", (run_id,)).fetchone()[0]
                if phase in {"intraday", "closeout"}:
                    held = {p["code"] for p in profile["state"]["positions"] if p["quantity"] > 0}
                    if state["watchlist"] != profile["state"].get("watchlist", []) or any(
                            f.get("side") == "buy" or f.get("code") not in held for f in fills):
                        raise ValueError("龙头选手盘中仅管理已有持仓，禁止修改观察池或提交新增买入")
            state_json = encode_agent_json(state)
            if _exceeds_agent_limits(cfg, profile["state"], state):
                raise ValueError("账户超出智能体数量约束")
            if before_commit:
                before_commit()
            validate_stock_agent_transition(profile["state"], state, fills)
            for index, fill in enumerate(fills):
                self.conn.execute("INSERT INTO stock_agent_trades(agent_id,run_id,seq,at,detail_json) VALUES(?,?,?,?,?)",
                                  (agent_id, run_id, index, timestamp, encode_agent_json(fill)))
            self.conn.execute("""UPDATE stock_agent_runs SET status='success',finished_at=?,summary=?,actions_json=?,detail_json=?
                WHERE id=? AND agent_id=? AND status='running'""", (timestamp, summary, encode_agent_json(actions), detail, run_id, agent_id))
            self.conn.execute("""UPDATE stock_agent_profiles SET state_json=?,state_version=state_version+1,active_run=NULL,
                lease_until=NULL,updated_at=?,total_trades=total_trades+?,total_actions=total_actions+?,
                latest_status='success',latest_summary=?,latest_actions_json=? WHERE id=?""",
                (state_json, timestamp, len(fills), len(result.get("decisions", [])), summary, encode_agent_json(actions), agent_id))
            self._snapshot(agent_id, state, timestamp)
            if before_commit:
                before_commit()

    def fail_run(self, agent_id: str, run_id: str, message: str, *, cancelled: bool = False, now: datetime | None = None) -> None:
        timestamp, status = agent_now(now).isoformat(), "cancelled" if cancelled else "failed"
        with self._write():
            changed = self.conn.execute("UPDATE stock_agent_runs SET status=?,finished_at=?,summary=? WHERE id=? AND agent_id=? AND status='running'",
                                        (status, timestamp, message[:2000], run_id, agent_id)).rowcount
            if changed:
                self.conn.execute("""UPDATE stock_agent_profiles SET active_run=NULL,lease_until=NULL,latest_status=?,
                    latest_summary=?,latest_actions_json='[]' WHERE id=? AND active_run=?""", (status, message[:2000], agent_id, run_id))

    def run_share_token(self, agent_id: str, run_id: str) -> str:
        """分享地址绑定本租户的一次已完成工作，不读取其他智能体状态。"""
        with self._write():
            row = self.conn.execute("SELECT detail_json FROM stock_agent_runs WHERE id=? AND agent_id=? AND status='success'",
                                    (run_id, agent_id)).fetchone()
            if row is None:
                raise ValueError("只能分享已完成的智能体工作")
            detail = json.loads(row[0])
            token = detail.get('share_token')
            if not token:
                token = secrets.token_urlsafe(32)
                detail['share_token'] = token
                self.conn.execute("UPDATE stock_agent_runs SET detail_json=? WHERE id=? AND agent_id=?",
                                  (encode_agent_json(detail), run_id, agent_id))
            return token

    def save_notification(self, agent_id: str, run_id: str, receipt: dict[str, Any]) -> None:
        with self._write():
            row = self.conn.execute("SELECT detail_json FROM stock_agent_runs WHERE id=? AND agent_id=? AND status='success'",
                                    (run_id, agent_id)).fetchone()
            if row is None:
                raise ValueError("只能保存已完成研究的推送回执")
            detail = json.loads(row[0])
            detail["notify"] = receipt
            self.conn.execute("UPDATE stock_agent_runs SET detail_json=? WHERE id=? AND agent_id=?",
                              (encode_agent_json(detail), run_id, agent_id))

    def _snapshot(self, agent_id: str, state: dict[str, Any], timestamp: str) -> None:
        self.conn.execute("""INSERT INTO stock_agent_equity VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(agent_id,day) DO UPDATE SET
            at=excluded.at,equity_cents=excluded.equity_cents,funded_cents=excluded.funded_cents,pnl_cents=excluded.pnl_cents,
            realized_pnl_cents=excluded.realized_pnl_cents,fees_cents=excluded.fees_cents,stale=excluded.stale""",
            (agent_id, timestamp[:10], timestamp, state["equity_cents"], state["initial_capital_cents"],
             state["equity_cents"] - state["initial_capital_cents"], state["realized_pnl_cents"], state["fees_cents"],
             int(bool(state.get("stale_codes")))))
