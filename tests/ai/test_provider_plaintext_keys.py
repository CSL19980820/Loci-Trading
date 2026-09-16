"""LLM 供应商 Key：明文落库；旧密文启动清理。"""

from __future__ import annotations

from src.ai.infrastructure.providers import (
    decode_provider_secret,
    encode_provider_secret,
    migrate_encrypted_llm_keys,
    resolve_config,
    save_provider,
)
from src.ops import OpsError, OpsStore


def test_save_defaults_to_offline_without_probe_or_model_discovery(tmp_path, monkeypatch) -> None:
    from unittest.mock import Mock
    from src.ai.api.schemas import ProviderCreate
    probe = Mock(side_effect=AssertionError("保存不应校验上游"))
    discover = Mock(side_effect=AssertionError("保存不应拉取模型目录"))
    monkeypatch.setattr("src.ai.infrastructure.providers.probe_provider", probe)
    monkeypatch.setattr("src.ai.infrastructure.providers.fetch_models", discover)
    payload = ProviderCreate(name="offline", base_url="https://example.invalid/v1", api_key="test-key", model="m")
    assert not payload.validate_key and not payload.discover_models
    with OpsStore(tmp_path / "offline.db") as store:
        saved = save_provider(store, name=payload.name, base_url=payload.base_url, api_key=payload.api_key, model=payload.model, protocol=payload.protocol)
        assert saved["default_model"] == "m" and saved["has_key"]
    probe.assert_not_called()
    discover.assert_not_called()
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.ai.api.router import build_ai_router
    app = FastAPI()
    app.include_router(build_ai_router(write_dependency=lambda: None, ops_db=str(tmp_path / "http.db")))
    with TestClient(app) as client:
        response = client.post("/api/providers", json={**payload.model_dump(), "validate_key": True, "discover_models": True})
        assert response.status_code == 201
    probe.assert_not_called()
    discover.assert_not_called()


def test_provider_key_plain_round_trip(tmp_path) -> None:
    store = OpsStore(tmp_path / "ops.db")
    try:
        saved = save_provider(
            store,
            name="plain",
            protocol="openai_compatible",
            base_url="https://example.com/v1",
            api_key="sk-live-abcd",
            model="m1",
            validate=False,
            discover_models=False,
        )
        row = store.get_provider(saved["id"], include_secret=True)
        assert row is not None
        assert row["encrypted_key"] == b"sk-live-abcd"
        cfg = resolve_config(store, "plain")
        assert cfg.api_key == "sk-live-abcd"
    finally:
        store.close()


def test_migrate_purges_legacy_ciphertext(tmp_path) -> None:
    store = OpsStore(tmp_path / "ops.db")
    try:
        provider_id = "LLM-legacy"
        store.upsert_provider(
            {
                "id": provider_id,
                "name": "legacy",
                "protocol": "openai_compatible",
                "base_url": "https://example.com/v1",
                "encrypted_key": b"\x00\x01\x02not-plain-secret-bytes!!!!",
                "key_last4": "****9999",
                "default_model": "m1",
                "models": [{"id": "m1", "enabled": True, "source": "manual"}],
                "is_active": True,
            }
        )
        assert migrate_encrypted_llm_keys(store) == 1
        row = store.get_provider("legacy", include_secret=True)
        assert row is not None
        assert row["encrypted_key"] is None
        assert row["has_key"] is False
        assert migrate_encrypted_llm_keys(store) == 0
    finally:
        store.close()


def test_decode_rejects_binary_blob() -> None:
    import pytest

    with pytest.raises(OpsError, match="旧加密格式已废弃"):
        decode_provider_secret(b"\xff\xfe\xfd binary", aad="x")


def test_encode_provider_secret_rejects_empty() -> None:
    import pytest

    with pytest.raises(OpsError):
        encode_provider_secret("   ")
