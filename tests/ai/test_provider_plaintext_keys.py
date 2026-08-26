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
