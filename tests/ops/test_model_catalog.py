"""模型目录 normalize / merge / 兼容旧 string[]。"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.ai.infrastructure.providers import get_model_entry, resolve_config, update_provider_models
from src.ops import OpsError, OpsStore
from src.ops.infrastructure.model_catalog import (
    ensure_default_in_catalog,
    find_model_entry,
    merge_discovered,
    normalize_models,
    present_provider_models,
)


class ModelCatalogTests(unittest.TestCase):
    def test_normalize_legacy_string_list(self) -> None:
        catalog = normalize_models(["b", "a", "a", ""])
        self.assertEqual([item["id"] for item in catalog], ["b", "a"])
        self.assertTrue(all(item["enabled"] for item in catalog))
        self.assertTrue(all(item["source"] == "discovered" for item in catalog))

    def test_normalize_objects_and_drop_dupes(self) -> None:
        catalog = normalize_models(
            [
                {"id": "x", "enabled": False, "context_window": 8192, "source": "manual"},
                {"id": "x", "enabled": True},
                {"id": "y", "name": "Why", "max_output_tokens": 1024},
            ]
        )
        self.assertEqual(len(catalog), 2)
        self.assertFalse(catalog[0]["enabled"])
        self.assertEqual(catalog[0]["context_window"], 8192)
        self.assertEqual(catalog[1]["name"], "Why")
        self.assertEqual(catalog[1]["max_output_tokens"], 1024)

    def test_merge_keeps_user_overrides(self) -> None:
        existing = normalize_models(
            [
                {
                    "id": "keep",
                    "enabled": False,
                    "context_window": 32000,
                    "name": "Kept",
                    "source": "discovered",
                },
                {"id": "manual-only", "source": "manual", "enabled": True},
            ]
        )
        discovered = [
            {"id": "keep", "context_window": 64000, "name": "Remote"},
            {"id": "new", "context_window": 128000},
        ]
        merged = merge_discovered(existing, discovered)
        by_id = {item["id"]: item for item in merged}
        self.assertFalse(by_id["keep"]["enabled"])
        self.assertEqual(by_id["keep"]["context_window"], 32000)
        self.assertEqual(by_id["keep"]["name"], "Kept")
        self.assertIn("manual-only", by_id)
        self.assertEqual(by_id["new"]["context_window"], 128000)
        self.assertTrue(by_id["new"]["enabled"])

    def test_merge_fills_empty_context_from_discovery(self) -> None:
        existing = normalize_models([{"id": "m", "source": "discovered"}])
        merged = merge_discovered(existing, [{"id": "m", "context_window": 65536}])
        self.assertEqual(merged[0]["context_window"], 65536)

    def test_ensure_default_adds_manual(self) -> None:
        catalog = ensure_default_in_catalog([], "custom-model")
        self.assertEqual(catalog[0]["id"], "custom-model")
        self.assertEqual(catalog[0]["source"], "manual")

    def test_present_splits_enabled_ids(self) -> None:
        presented = present_provider_models(
            [
                {"id": "on", "enabled": True},
                {"id": "off", "enabled": False},
            ]
        )
        self.assertEqual(presented["models"], ["on"])
        self.assertEqual(len(presented["model_catalog"]), 2)

    def test_find_model_entry(self) -> None:
        catalog = normalize_models(["a", "b"])
        self.assertEqual(find_model_entry(catalog, "b")["id"], "b")
        self.assertIsNone(find_model_entry(catalog, "nope"))


class ProviderDefaultModelValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = OpsStore(Path(self.temp.name) / "ops.db")
        self.store.upsert_provider(
            {
                "name": "catalog-provider",
                "protocol": "openai_compatible",
                "base_url": "https://llm.example.test/v1",
                "encrypted_key": b"test-key",
                "default_model": "model-a",
                "models": [
                    {"id": "model-a", "enabled": True},
                    {"id": "model-b", "enabled": True},
                ],
            }
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_update_rejects_disabled_default_model_without_persisting(self) -> None:
        with self.assertRaisesRegex(OpsError, "默认模型已停用"):
            update_provider_models(
                self.store,
                "catalog-provider",
                models=[
                    {"id": "model-a", "enabled": False},
                    {"id": "model-b", "enabled": True},
                ],
                default_model="model-a",
            )

        saved = self.store.get_provider("catalog-provider")
        assert saved is not None
        self.assertEqual(saved["default_model"], "model-a")
        self.assertTrue(find_model_entry(saved["model_catalog"], "model-a")["enabled"])

    def test_update_rejects_default_model_missing_from_catalog(self) -> None:
        with self.assertRaisesRegex(OpsError, "默认模型不在目录中"):
            update_provider_models(
                self.store,
                "catalog-provider",
                models=[{"id": "model-b", "enabled": True}],
                default_model="model-a",
            )

    def test_legacy_disabled_default_falls_back_without_persisting(self) -> None:
        self.store.upsert_provider(
            {
                "name": "catalog-provider",
                "protocol": "openai_compatible",
                "base_url": "https://llm.example.test/v1",
                "encrypted_key": b"test-key",
                "default_model": "model-a",
                "models": [
                    {"id": "model-a", "enabled": False},
                    {"id": "model-b", "enabled": True, "context_window": 8192},
                    {"id": "model-c", "enabled": True},
                ],
            }
        )

        for requested in ("", "model-a"):
            with self.subTest(requested=requested):
                config = resolve_config(self.store, "catalog-provider", model=requested)
                self.assertEqual(config.model, "model-b")
                self.assertEqual(config.context_window, 8192)

        resolved_entry = get_model_entry(self.store, "catalog-provider")
        assert resolved_entry is not None
        self.assertEqual(resolved_entry["id"], "model-b")

        saved = self.store.get_provider("catalog-provider")
        assert saved is not None
        self.assertEqual(saved["default_model"], "model-a")
        default_entry = find_model_entry(saved["model_catalog"], "model-a")
        assert default_entry is not None
        self.assertFalse(default_entry["enabled"])

    def test_legacy_disabled_default_reports_unavailable_without_enabled_model(self) -> None:
        self.store.upsert_provider(
            {
                "name": "catalog-provider",
                "protocol": "openai_compatible",
                "base_url": "https://llm.example.test/v1",
                "encrypted_key": b"test-key",
                "default_model": "model-a",
                "models": [
                    {"id": "model-a", "enabled": False},
                    {"id": "model-b", "enabled": False},
                ],
            }
        )

        with self.assertRaisesRegex(OpsError, "没有可用的启用模型"):
            resolve_config(self.store, "catalog-provider", model="model-a")


if __name__ == "__main__":
    unittest.main()
