"""供应商配置的增删改查：把明文 Key 加密落库，再在调用前解回内存。

明文 Key 的生命周期被压到最短：进来 → 校验 → 加密 → 落库，此后只有
真正要发请求的那一刻才解密成局部变量。任何列表/详情接口都只回末四位。
模型目录（启用、上下文、输出上限）经 ops.model_catalog 规范化后落 models_json。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.ai.infrastructure.client import (
    LLMError,
    PROTOCOLS,
    ProviderConfig,
    list_models as fetch_models,
    validate as probe_provider,
)
from src.ai.infrastructure.crypto import decrypt_secret, encrypt_secret, mask_secret
from src.ops import (
    OpsError,
    OpsStore,
    ensure_default_in_catalog,
    find_model_entry,
    merge_discovered,
    new_id,
    normalize_models,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _catalog_from_record(record: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not record:
        return []
    if record.get("model_catalog") is not None:
        return normalize_models(record.get("model_catalog"))
    return normalize_models(record.get("models"))


def _resolve_runtime_model(
    record: dict[str, Any], catalog: list[dict[str, Any]], requested_model: str
) -> tuple[str, dict[str, Any] | None]:
    """解析运行期模型，并兼容旧库中已停用的默认模型。"""
    default_model = str(record.get("default_model") or "").strip()
    requested = str(requested_model or "").strip()
    chosen = requested or default_model
    entry = find_model_entry(catalog, chosen)
    if entry and entry.get("enabled"):
        return chosen, entry

    # 助手会把会话中缓存的默认模型显式带回；只要它仍等于当前默认值，
    # 就和未传模型一样按目录顺序降级，且不静默改写用户的持久化配置。
    uses_default = not requested or chosen == default_model
    if uses_default:
        fallback = next((item for item in catalog if item.get("enabled")), None)
        if fallback is not None:
            return str(fallback["id"]), fallback
        if catalog:
            raise OpsError(f"供应商 {record['name']} 没有可用的启用模型")

    if not chosen:
        raise OpsError(f"供应商 {record['name']} 未指定模型")
    if entry is not None:
        raise OpsError(f"供应商 {record['name']} 的模型 {chosen} 已停用")
    return chosen, None


def save_provider(
    store: OpsStore,
    *,
    name: str,
    protocol: str,
    base_url: str,
    api_key: str | None = None,
    model: str = "",
    proxy_url: str = "",
    note: str = "",
    validate: bool = True,
    discover_models: bool = True,
    is_default: bool = False,
    master_key: str | None = None,
) -> dict[str, Any]:
    """新增或更新一个供应商。

    api_key 为空表示"只改其他字段，保留原密钥"——这样改 base_url 或
    换默认模型时不必让用户重新粘贴一遍密钥。
    """
    name = name.strip()
    protocol = protocol.strip()
    if not name:
        raise OpsError("供应商名称不能为空")
    if protocol not in PROTOCOLS:
        raise OpsError(f"未知协议：{protocol}（可选 {list(PROTOCOLS)}）")
    base_url = base_url.strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise OpsError("Base URL 必须以 http:// 或 https:// 开头")

    existing = store.get_provider(name, include_secret=True)
    provider_id = existing["id"] if existing else new_id("LLM")

    encrypted: bytes | None = None
    last4 = ""
    if api_key:
        # AAD 绑定 provider_id：密文被搬到另一行会直接解不开。
        encrypted = encrypt_secret(api_key.strip(), aad=provider_id, master_key=master_key)
        last4 = mask_secret(api_key.strip())
    elif not existing:
        raise OpsError("新建供应商必须提供 API Key")

    plaintext = api_key.strip() if api_key else _decrypt_existing(existing, master_key)

    validated_at = existing.get("validated_at", "") if existing else ""
    catalog = _catalog_from_record(existing)
    models_synced_at = existing.get("models_synced_at", "") if existing else ""

    if validate or discover_models:
        config = ProviderConfig(
            name=name, protocol=protocol, base_url=base_url,
            api_key=plaintext, model=model, proxy_url=proxy_url,
        )
        if discover_models:
            discovered = fetch_models(config)
            if discovered:
                catalog = merge_discovered(catalog, discovered)
                models_synced_at = _now()
                if not model:
                    model = str(discovered[0]["id"])
        if validate:
            if not model:
                raise OpsError(
                    "未能自动发现模型列表，请显式指定默认模型（该供应商可能不提供 /models 接口）"
                )
            try:
                probe_provider(config if config.model else ProviderConfig(
                    name=name, protocol=protocol, base_url=base_url,
                    api_key=plaintext, model=model, proxy_url=proxy_url,
                ))
            except LLMError as exc:
                # 校验失败绝不落库：宁可让用户当场改，也不要留一个半死的配置
                # 等到半夜的定时任务去发现。
                raise OpsError(f"API Key 校验未通过，未保存：{exc}") from exc
            validated_at = _now()

    catalog = ensure_default_in_catalog(catalog, model)

    store.upsert_provider(
        {
            "id": provider_id,
            "name": name,
            "protocol": protocol,
            "base_url": base_url,
            "encrypted_key": encrypted,
            "key_last4": last4,
            "default_model": model,
            "models": catalog,
            "models_synced_at": models_synced_at,
            "proxy_url": proxy_url,
            "is_active": True,
            "validated_at": validated_at,
            "note": note,
            **({"is_default": True} if is_default else {}),
        }
    )
    if is_default:
        store.set_default_provider(name)
    saved = store.get_provider(name)
    if saved is None:  # pragma: no cover - upsert 后必然存在
        raise OpsError("保存供应商后读取失败")
    return saved


def _decrypt_existing(existing: dict[str, Any] | None, master_key: str | None) -> str:
    if not existing or not existing.get("encrypted_key"):
        raise OpsError("该供应商没有已保存的 API Key，请提供")
    return decrypt_secret(
        existing["encrypted_key"], aad=existing["id"], master_key=master_key
    )


def resolve_config(
    store: OpsStore,
    name_or_id: str = "",
    *,
    model: str = "",
    master_key: str | None = None,
    timeout: float | None = None,
) -> ProviderConfig:
    """取出可直接发起调用的配置。明文密钥只存在于返回值里，用完即弃。

    name_or_id 为空时优先使用 is_default=1 的供应商。
    目录里若有该模型的上下文/输出上限，一并挂到 ProviderConfig（本批不改 chat 公式）。
    """
    record: dict[str, Any] | None
    if not str(name_or_id).strip():
        record = store.get_default_provider(include_secret=True)
        if record is None:
            raise OpsError("未指定 LLM 供应商，且没有设置默认供应商")
    else:
        record = store.get_provider(name_or_id, include_secret=True)
    if record is None:
        raise OpsError(f"未配置的供应商：{name_or_id}")
    if not record.get("is_active"):
        raise OpsError(f"供应商 {record['name']} 已停用")
    if not record.get("encrypted_key"):
        raise OpsError(f"供应商 {record['name']} 没有保存 API Key")

    catalog = _catalog_from_record(record)
    chosen, entry = _resolve_runtime_model(record, catalog, model)
    plaintext = decrypt_secret(
        record["encrypted_key"], aad=record["id"], master_key=master_key
    )
    config = ProviderConfig(
        name=record["name"],
        protocol=record["protocol"],
        base_url=record["base_url"],
        api_key=plaintext,
        model=chosen,
        proxy_url=record.get("proxy_url", ""),
        context_window=entry.get("context_window") if entry else None,
        max_output_tokens=entry.get("max_output_tokens") if entry else None,
    )
    if timeout is not None:
        config.timeout = timeout
    return config


def get_model_entry(
    store: OpsStore, name_or_id: str, model_id: str = ""
) -> dict[str, Any] | None:
    """读取供应商目录里某模型的元数据；model_id 空则用默认模型。"""
    record = store.get_provider(name_or_id)
    if record is None:
        return None
    catalog = _catalog_from_record(record)
    if not str(model_id).strip():
        _, entry = _resolve_runtime_model(record, catalog, "")
        return entry
    return find_model_entry(catalog, str(model_id).strip())


def update_provider_models(
    store: OpsStore,
    name_or_id: str,
    *,
    models: list[dict[str, Any]] | list[str],
    default_model: str | None = None,
) -> dict[str, Any]:
    """整表替换模型目录（启停、上下文、增删手动项、默认模型）。"""
    record = store.get_provider(name_or_id)
    if record is None:
        raise OpsError(f"未配置的供应商：{name_or_id}")
    catalog = normalize_models(models)
    chosen = (
        str(default_model).strip()
        if default_model is not None
        else str(record.get("default_model") or "")
    )
    if chosen:
        default_entry = find_model_entry(catalog, chosen)
        if default_entry is None:
            raise OpsError(f"默认模型不在目录中：{chosen}")
        if not default_entry.get("enabled"):
            raise OpsError(f"默认模型已停用：{chosen}")
    store.upsert_provider(
        {
            "id": record["id"],
            "name": record["name"],
            "protocol": record["protocol"],
            "base_url": record["base_url"],
            "encrypted_key": None,
            "default_model": chosen,
            "models": catalog,
            "models_synced_at": record.get("models_synced_at", ""),
            "proxy_url": record.get("proxy_url", ""),
            "is_active": record["is_active"],
            "validated_at": record.get("validated_at", ""),
            "note": record.get("note", ""),
        }
    )
    saved = store.get_provider(name_or_id)
    if saved is None:  # pragma: no cover
        raise OpsError("更新模型目录后读取失败")
    return saved


def refresh_models(
    store: OpsStore, name_or_id: str, *, master_key: str | None = None
) -> list[dict[str, Any]]:
    """重新拉取模型并合并进目录。供应商上新模型后不必删了重配。"""
    config = resolve_config(store, name_or_id, master_key=master_key)
    discovered = fetch_models(config)
    record = store.get_provider(name_or_id)
    if record is None:
        raise OpsError(f"未配置的供应商：{name_or_id}")
    catalog = merge_discovered(_catalog_from_record(record), discovered)
    catalog = ensure_default_in_catalog(catalog, str(record.get("default_model") or ""))
    store.upsert_provider(
        {
            "id": record["id"],
            "name": record["name"],
            "protocol": record["protocol"],
            "base_url": record["base_url"],
            "encrypted_key": None,  # 保留原密钥
            "default_model": record["default_model"],
            "models": catalog,
            "models_synced_at": _now() if discovered else record.get("models_synced_at", ""),
            "proxy_url": record.get("proxy_url", ""),
            "is_active": record["is_active"],
            "validated_at": record.get("validated_at", ""),
            "note": record.get("note", ""),
        }
    )
    return catalog
