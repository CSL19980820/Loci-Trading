import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from src.ops.application.guardian_research_context import ResearchContext, evidence_snapshot
from src.shared.tenancy import tenant_scope


def read_all(archive, ref):
    offset, parts = 0, []
    while True:
        reply = json.loads(archive.read({"ref": ref, "offset": offset, "limit": 4000})["text"])
        parts.append(reply["text"])
        if reply["next_offset"] is None:
            assert len("".join(parts)) == reply["total_characters"]
            return "".join(parts)
        assert reply["next_offset"] > offset
        offset = reply["next_offset"]


def test_compaction_retains_full_signals_and_exact_portfolio():
    archive = ResearchContext()
    signal = {"code": "600001", "score": 88, "strategy_slug": "fixture",
              "observations": "complete evidence " * 600, "last_fact": "END_OF_SIGNAL"}
    portfolio = {"cash_cents": 12345678, "positions": [{"code": "600001", "quantity": 300,
        "cost_cents": 302100, "mark_at": "2026-09-15 10:00:00", "mark_price_cents": 1001}]}
    payload = {"portfolio": portfolio, "candidates": [{"code": "600001", "signals": [signal]}]}
    original = copy.deepcopy(payload)
    compact, metrics = archive.compact(payload)
    assert payload == original and compact["portfolio"] == portfolio
    assert metrics["prompt_characters"] < metrics["original_characters"]
    summarized = compact["candidates"][0]["signals"][0]
    assert summarized["score"] == 88 and summarized["strategy_slug"] == "fixture"
    assert json.loads(read_all(archive, summarized["source"]["evidence_ref"])) == signal
    assert summarized["source"]["requires_read"]


def test_large_tool_result_preserves_raw_receipt_and_exact_tail():
    archive = ResearchContext()
    full = "immutable data " * 6500 + "END_OF_TOOL_RESULT"
    response = archive.record("quotes", {"code": "600001"}, {"text": full, "is_error": False}, 23)
    ref = json.loads(response["text"])["evidence_ref"]
    assert len(response["text"]) < 3000 and read_all(archive, ref) == full
    assert archive.documents[ref]["sha256"] == hashlib.sha256(full.encode()).hexdigest()
    assert archive.receipts[0]["text"].endswith("END_OF_TOOL_RESULT")


def test_context_read_is_bound_to_original_tenant():
    with tenant_scope("research_snapshot_a"):
        archive = ResearchContext()
        ref = archive.store("private evidence", "fixture")["evidence_ref"]
        assert not archive.read({"ref": ref}).get("is_error")
    with tenant_scope("research_snapshot_b"):
        rejected = archive.read({"ref": ref})
        assert rejected["is_error"] and "private evidence" not in rejected["text"]
    with tenant_scope("research_snapshot_a"):
        assert archive.read({"ref": "unknown"})["is_error"]


def test_evidence_snapshot_cannot_change_after_late_tool_completion():
    archive = ResearchContext()
    args = {"codes": ["600001"]}
    archive.record("quotes", args, {"text": "before cancellation"}, 10)
    ref = archive.store("before cancellation", "fixture")["evidence_ref"]
    frozen = evidence_snapshot(archive)
    args["codes"].append("600002")
    archive.record("late", {}, {"text": "finished after cancellation"}, 20)
    archive.documents[ref]["text"] = "changed later"
    assert len(frozen["tools"]) == 1
    assert frozen["tools"][0]["arguments"] == {"codes": ["600001"]}
    assert frozen["context_documents"][ref]["text"] == "before cancellation"


def test_snapshot_waits_for_archive_lock():
    archive = ResearchContext()
    started = Event()
    def snapshot():
        started.set()
        return evidence_snapshot(archive)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with archive.lock:
            future = pool.submit(snapshot)
            assert started.wait(timeout=5) and not future.done()
            archive.record("quotes", {}, {"text": "committed together"}, 1)
            ref = archive.store("committed together", "fixture")["evidence_ref"]
        frozen = future.result(timeout=5)
    assert frozen["tools"][0]["text"] == frozen["context_documents"][ref]["text"]


def test_page_is_not_recursively_archived():
    archive = ResearchContext()
    ref = archive.store("x" * 100000, "fixture")["evidence_ref"]
    page = archive.read({"ref": ref, "offset": 90000, "limit": 24000})
    assert archive.record("guardian_context_read", {"ref": ref}, page, 1) == page
    assert json.loads(page["text"])["next_offset"] is None and len(archive.documents) == 1
