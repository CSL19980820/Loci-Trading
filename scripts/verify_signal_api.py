"""新增信号接口的端到端自检（TestClient，不依赖真实行情）。

跑：.venv/Scripts/python scripts/verify_signal_api.py

验三件事，全部按用户需求的原话：
  4. 规则「能到系统里面维护」——列得出来、改得动、改完读回来是新值
  5. 「超过 7 天自动销毁，只看最新的 80 条」——落库两道闸门真的生效
"""

from __future__ import annotations

from datetime import datetime, timedelta
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    from fastapi.testclient import TestClient

    from src.app.main import create_app

    app = create_app()
    client = TestClient(app)
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"{'PASS' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}")
        if not ok:
            failures.append(name)

    # —— 需求 4：规则可维护 ——
    resp = client.get("/api/market/signals/rules")
    check("GET /signals/rules 通", resp.status_code == 200, f"HTTP {resp.status_code}")
    payload = resp.json() if resp.status_code == 200 else {}
    rules = payload.get("rules", payload) if isinstance(payload, dict) else payload
    ids = [r.get("rule_id") or r.get("id") for r in rules] if isinstance(rules, list) else []
    check("六条规则都在", len(ids) == 6, str(ids))
    check(
        "每条都带中文名与口径说明",
        all(r.get("label") and r.get("description") for r in rules),
        "",
    )

    # 改一个阈值，读回来必须是新值
    resp = client.put(
   "/api/market/signals/rules/fast_surge",
        json={"params": {"speed_pct": 5.0}},
    )
    check("PUT 改阈值通", resp.status_code == 200, f"HTTP {resp.status_code} {resp.text[:120]}")
    resp = client.get("/api/market/signals/rules")
    got = next(
        (
        r
            for r in resp.json().get("rules", [])
        if (r.get("rule_id") or r.get("id")) == "fast_surge"
   ),
        {},
    )
    check("改完读回来是新值", got.get("params", {}).get("speed_pct") == 5.0, str(got.get("params")))

    # 越界要被挡回，且给人话
    resp = client.put("/api/market/signals/rules/fast_surge", json={"params": {"speed_pct": 0}})
    check("越界被 400 挡回", resp.status_code == 400, f"HTTP {resp.status_code}")
    check("400 带人话原因", "speed_pct" in resp.text, resp.text[:160])

    # 未知规则 404
    resp = client.put("/api/market/signals/rules/nope", json={"enabled": False})
    check("未知规则 404", resp.status_code == 404, f"HTTP {resp.status_code}")

    # 停用/恢复
    client.put("/api/market/signals/rules/fast_surge", json={"enabled": False})
    resp = client.get("/api/market/signals/rules")
    got = next(
    (
            r
  for r in resp.json().get("rules", [])
            if (r.get("rule_id") or r.get("id")) == "fast_surge"
    ),
 {},
    )
    check("停用状态落库", got.get("enabled") is False, str(got.get("enabled")))
    client.put(
        "/api/market/signals/rules/fast_surge",
        json={"enabled": True, "params": {"speed_pct": 2.0}},
    )

    # —— 需求 5：保留策略 ——
    resp = client.get("/api/market/signals/recent?limit=80")
    check("GET /signals/recent 通", resp.status_code == 200, f"HTTP {resp.status_code}")
    body = resp.json() if resp.status_code == 200 else {}
    items = body.get("items", body if isinstance(body, list) else [])
    check("recent 返回列表", isinstance(items, list), type(items).__name__)
    check("不超过 80 条", len(items) <= 80, f"{len(items)} 条")

    # 直接压库验两道闸门
    from src.ops.infrastructure.store import OpsStore
    from src.ops.infrastructure.store_signals import (
      SIGNAL_JOURNAL_MAX_ROWS,
        SIGNAL_RETENTION_DAYS,
    )

    check("保留天数常量 = 7", SIGNAL_RETENTION_DAYS == 7, str(SIGNAL_RETENTION_DAYS))
    check("条数上限常量 = 80", SIGNAL_JOURNAL_MAX_ROWS == 80, str(SIGNAL_JOURNAL_MAX_ROWS))

    store = OpsStore()
    tenant = "default"
    # 去重键 = (tenant, code, rule_id, trade_day) 且 ON CONFLICT DO NOTHING：
    # 同一天重复跑本脚本，若 code 固定，断言看到的会是上一次跑留下的旧行（血泪）。
    now = datetime.now()
    tag = now.strftime("%H%M%S")
    stale = (now - timedelta(days=SIGNAL_RETENTION_DAYS + 1)).strftime("%Y-%m-%d %H:%M:%S")
    fresh = now.strftime("%Y-%m-%d %H:%M:%S")

    def row(idx: int, at: str) -> dict:
        return {
            # code 带本次运行的时间戳：去重键是 (tenant, code, rule_id, trade_day) 且
            # ON CONFLICT DO NOTHING，code 固定的话同一天重复跑只会读到上一次的旧行。
            "code": f"9{tag}{idx % 10}",
            "name": f"自检{idx}",
            "rule_id": "fast_surge",
            "rule_label": "快速拉升",
            "title": "自检",
            "detail": "verify_signal_api",
            "direction": "long",
            "strength": 50.0,
            "price": 10.0,
            "pct": 1.0,
            # 引擎产出的字段名是 at；triggered_at 是列名，写进来会被忽略
            "at": at,
            "trade_day": at[:10],
        }

    stale_row = row(1, stale)
    stale_code = str(stale_row["code"])
    store.append_signal_journal([stale_row], tenant=tenant)
    seen = store.list_signal_journal(tenant=tenant, limit=200, now=now)
    check(
        "超 7 天的信号读不出来",
        not any(str(r.get("code")) == stale_code for r in seen),
        f"读到 {len(seen)} 条",
    )
    # 再压一遍闸门，确认是**物理删除**而不只是查询过滤
    store.prune_signal_journal(tenant=tenant, now=now)
    left = store.conn.execute(
        "SELECT COUNT(*) FROM signal_journal WHERE tenant=? AND code=?",
        (tenant, stale_code),
    ).fetchone()[0]
    check("超 7 天的行被物理删除", int(left) == 0, f"库内残留 {left} 行")

    store.append_signal_journal([row(i, fresh) for i in range(90)], tenant=tenant)
    total = store.conn.execute(
        "SELECT COUNT(*) FROM signal_journal WHERE tenant=?", (tenant,)
    ).fetchone()[0]
    check("写 90 条后库内只剩 ≤80", int(total) <= SIGNAL_JOURNAL_MAX_ROWS, f"库内 {total} 行")

    # 时间旅行：8 天后再读，今天这批必须自动消失
    future = now + timedelta(days=SIGNAL_RETENTION_DAYS + 1)
    later = store.list_signal_journal(tenant=tenant, limit=200, now=future)
    check("8 天后信号自动销毁", len(later) == 0, f"仍读到 {len(later)} 条")

    print()
    if failures:
        print(f"FAILED {len(failures)} 项：" + "; ".join(failures))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
