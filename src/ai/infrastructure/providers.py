"""供应商配置的增删改查：把明文 Key 加密落库，再在调用前解回内存。

明文 Key 的生命周期被压到最短：进来 → 校验 → 加密 → 落库，此后只有
真正要发请求的那一刻才解密成局部变量。任何列表/详情接口都只回末四位。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.ai.infrastructure.client import (
    LLMError,
    ProviderConfig,
    list_models as fetch_models,
    validate as probe_provider,
)
from src.ai.infrastructure.crypto import decrypt_secret, encrypt_secret, mask_secret
from src.ops import OpsError, OpsStore, new_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
    if not name:
        raise OpsError("供应商名称不能为空")
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
    models = existing.get("models", []) if existing else []
    models_synced_at = existing.get("models_synced_at", "") if existing else ""

    if validate or discover_models:
        config = ProviderConfig(
            name=name, protocol=protocol, base_url=base_url,
            api_key=plaintext, model=model, proxy_url=proxy_url,
        )
        if discover_models:
            discovered = fetch_models(config)
            if discovered:
                models = discovered
                models_synced_at = _now()
                if not model:
                    model = discovered[0]
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

    store.upsert_provider(
        {
            "id": provider_id,
            "name": name,
            "protocol": protocol,
            "base_url": base_url,
            "encrypted_key": encrypted,
            "key_last4": last4,
            "default_model": model,
            "models": models,
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

    plaintext = decrypt_secret(
        record["encrypted_key"], aad=record["id"], master_key=master_key
    )
    chosen = model or record.get("default_model") or ""
    if not chosen:
        raise OpsError(f"供应商 {record['name']} 未指定模型")

    config = ProviderConfig(
        name=record["name"],
        protocol=record["protocol"],
        base_url=record["base_url"],
        api_key=plaintext,
        model=chosen,
        proxy_url=record.get("proxy_url", ""),
    )
    if timeout is not None:
        config.timeout = timeout
    return config


def refresh_models(
    store: OpsStore, name_or_id: str, *, master_key: str | None = None
) -> list[str]:
    """重新拉取模型列表。供应商上新模型后不必删了重配。"""
    config = resolve_config(store, name_or_id, master_key=master_key)
    models = fetch_models(config)
    record = store.get_provider(name_or_id)
    if record and models:
        store.upsert_provider(
            {
                "id": record["id"],
                "name": record["name"],
                "protocol": record["protocol"],
                "base_url": record["base_url"],
                "encrypted_key": None,  # 保留原密钥
                "default_model": record["default_model"],
                "models": models,
                "models_synced_at": _now(),
                "proxy_url": record.get("proxy_url", ""),
                "is_active": record["is_active"],
                "validated_at": record.get("validated_at", ""),
                "note": record.get("note", ""),
            }
        )
    return models
