"""Replay仍返回完整JSON，但comparison从已验证artifact有界发送。"""
import asyncio
from contextlib import nullcontext
import hashlib
import json
from types import SimpleNamespace
import weakref

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.responses import JSONResponse

from src.research.api import backtest_router
from src.research.api.replay_response import CHUNK_BYTES, json_chunks, replay_json_response
from src.research.application import ResearchReplayError


def write_comparison(root, comparison):
    folder = root / "run-stream"
    folder.mkdir(exist_ok=True)
    raw = json.dumps(comparison, ensure_ascii=False, indent=2).encode("utf8") + b"\n"
    (folder / "replay-comparison.json").write_bytes(raw)
    return {"path": "replay-comparison.json", "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw), "created_at": "2026-09-12T00:00:00Z",
            "artifact_type": "replay_comparison", "metadata": {"source_manifest_sha256": "a" * 64}}


def test_batched_unicode_json_and_comparison_keep_full_contract(tmp_path):
    comparison = {"expected_execution": {"全部": ["数据😀", 1, None] * 30000},
                  "observed_execution": {"result": {"净值": 1.25}},
                  "control": {"trades": [{"code": "300001", "net": -.2}]},
                  "phases": {"train": {}, "oos": {}}}
    receipt = write_comparison(tmp_path, comparison)
    card = {"data_snapshot": {"linked": "中文😀" * 60000}}
    workflow = {"状态": "已回放"}
    response = replay_json_response(root=tmp_path, run_id="run-stream", run_card=card,
                                    workflow=workflow, receipt=receipt)

    async def collect():
        return [chunk async for chunk in response.body_iterator]

    chunks = asyncio.run(collect())
    assert response.status_code == 200 and response.media_type == "application/json"
    assert all(isinstance(chunk, bytes) and 0 < len(chunk) <= CHUNK_BYTES for chunk in chunks)
    assert len(chunks) < 100  # 不能逐个JSON token形成数十万个网络包
    assert json.loads(b"".join(chunks)) == {
        "run_card": card, "workflow": workflow, "comparison": comparison, "receipt": receipt,
    }
    assert b"".join(json_chunks(card)).decode("utf8") == json.dumps(card, ensure_ascii=False, separators=(",", ":"))


@pytest.mark.parametrize("bad", ["tamper", "missing", "wrong_size", "wrong_path", "nan_wrapper"])
def test_response_is_not_created_until_all_input_checks_pass(tmp_path, bad):
    receipt = write_comparison(tmp_path, {"matches": True})
    card = {"run_id": "run-stream"}
    path = tmp_path / "run-stream/replay-comparison.json"
    if bad == "tamper":
        path.write_bytes(b'{"matches":false}')
    elif bad == "missing":
        path.unlink()
    elif bad == "wrong_size":
        receipt["size_bytes"] += 1
    elif bad == "wrong_path":
        receipt["path"] = "../other.json"
    else:
        card["invalid"] = float("nan")
    with pytest.raises((ResearchReplayError, ValueError)):
        replay_json_response(root=tmp_path, run_id="run-stream", run_card=card,
                             workflow={}, receipt=receipt)


def app_for(tmp_path, monkeypatch, replay):
    card_body = {"run_id": "run-stream", "data_snapshot": {"linked": ["完整😀", {"原价": 10.25}]}}
    card = SimpleNamespace(run_id="run-stream", artifact_manifest=(), to_dict=lambda: card_body)
    cards = SimpleNamespace(root=tmp_path, require=lambda _: card)
    monkeypatch.setattr(backtest_router, "replay_research_backtest", replay)
    app = FastAPI()
    app.include_router(backtest_router.build_research_backtest_router(
        write_dependency=lambda: None, market_store_factory=lambda _: nullcontext(None),
        run_card_store_factory=lambda: cards,
        workflow_store_factory=lambda: SimpleNamespace(load=lambda _: SimpleNamespace(to_dict=lambda: {"stage": "done"})),
        backtest_job_store_factory=lambda: SimpleNamespace(recover_interrupted=lambda: []),
    ))
    return app, cards, card_body


def test_route_releases_comparison_before_loading_card_and_bypasses_jsonresponse(tmp_path, monkeypatch):
    class Comparison(dict):
        pass

    observed = {}
    expected = {"expected_execution": {"rows": [1, 2]}, "observed_execution": {"rows": [1, 2]},
                "control": {"all": "保留"}, "matches_all_recomputed_execution": True}

    def replay(*_args, **_kwargs):
        comparison = Comparison(expected)
        receipt = write_comparison(tmp_path, comparison)
        observed["ref"] = weakref.ref(comparison)
        observed["computed"] = True
        observed["receipt"] = receipt
        return {"comparison": comparison, "receipt": receipt}

    app, cards, card_body = app_for(tmp_path, monkeypatch, replay)
    original = cards.require

    def require(run_id):
        assert observed["computed"] and observed["ref"]() is None
        return original(run_id)

    cards.require = require

    def reject_materialization(*_args, **_kwargs):
        raise AssertionError("Replay成功响应不得经过JSONResponse整份物化")

    monkeypatch.setattr(JSONResponse, "render", reject_materialization)
    with TestClient(app) as client:
        response = client.post("/api/research/backtest-runs/run-stream/replay")
    assert response.status_code == 200
    assert response.json() == {"run_card": {**card_body, "artifact_manifest_sha256": response.json()["run_card"]["manifest_sha256"],
                                          "manifest_sha256": response.json()["run_card"]["manifest_sha256"]},
                               "workflow": {"stage": "done"}, "comparison": expected, "receipt": observed["receipt"]}


@pytest.mark.parametrize("error,status", [(ResearchReplayError("不一致"), 409), (ValueError("无效输入"), 422)])
def test_replay_errors_keep_status_before_any_success_headers(tmp_path, monkeypatch, error, status):
    def fail(*_args, **_kwargs):
        raise error

    app, _, _ = app_for(tmp_path, monkeypatch, fail)
    with TestClient(app) as client:
        response = client.post("/api/research/backtest-runs/run-stream/replay")
    assert response.status_code == status
    assert response.json() == {"detail": str(error)}
