"""Central model routing with tenant-bound gateway credentials."""
from __future__ import annotations

import hmac
import os
import re
from typing import TYPE_CHECKING

from src.shared.tenancy import current_tenant

if TYPE_CHECKING:
    from src.ai.infrastructure.client import ProviderConfig

_TENANT = re.compile(r'[A-Za-z0-9_-]{1,64}')


def tenant_gateway_token(secret: str, tenant: str) -> str:
    """A token for tenant A cannot authenticate tenant B."""
    if not _TENANT.fullmatch(tenant):
        raise ValueError('Invalid gateway tenant')
    if len(secret) < 32 or not secret.isascii():
        raise ValueError('gRPC signing secret requires at least 32 ASCII characters')
    return hmac.new(secret.encode('ascii'), b'loci.grpc.tenant.v1\0' + tenant.encode('ascii'), 'sha256').hexdigest()


def configure_grpc_route(config: ProviderConfig) -> ProviderConfig:
    mode = os.getenv('LOCI_LLM_GRPC_MODE', 'selected').strip().lower()
    if mode == 'off':
        return config
    if mode not in {'selected', 'all'}:
        raise ValueError('LOCI_LLM_GRPC_MODE must be off, selected or all')
    tenant = current_tenant()
    if mode == 'all':
        endpoint = os.getenv('LOCI_LLM_GRPC_ENDPOINT', '').strip()
        secret = os.getenv('LOCI_LLM_GRPC_SECRET') or os.getenv('LOCI_GRPC_TOKEN', '')
        if not endpoint:
            raise ValueError('All-model gRPC routing requires LOCI_LLM_GRPC_ENDPOINT')
        config.grpc_tenant = tenant
        config.grpc_token = tenant_gateway_token(secret, tenant)
    elif (os.getenv('LOCI_LLM_GRPC_TENANT') == tenant
          and os.getenv('LOCI_LLM_GRPC_PROVIDER') == config.name):
        endpoint = os.getenv('LOCI_LLM_GRPC_ENDPOINT', '').strip()
        config.grpc_token = os.getenv('LOCI_LLM_GRPC_TOKEN', '')
    else:
        return config
    config.grpc_endpoint = endpoint
    config.grpc_ca_file = os.getenv('LOCI_LLM_GRPC_CA', '')
    config.grpc_fallback = os.getenv('LOCI_LLM_GRPC_FALLBACK', '0') == '1'
    return config
