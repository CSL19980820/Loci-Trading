"""\u6a21\u5757\u7ea7\u7b26\u53f7\u5b88\u536b\uff1a\u90e8\u7f72\u5165\u53e3\u4e0e\u5404\u4e0a\u4e0b\u6587\u516c\u5f00 API \u5fc5\u987b\u771f\u7684\u5b58\u5728\u3002

\u4e3a\u4ec0\u4e48\u9700\u8981\u5b83\uff1a`compileall` \u4e0e `import` \u90fd\u53ea\u80fd\u544a\u8bc9\u4f60\u300c\u6587\u4ef6\u80fd\u8dd1\u300d\uff0c\u544a\u8bc9\u4e0d\u4e86\u4f60
\u300c\u8be5\u5728\u6a21\u5757\u9876\u5c42\u7684\u4e1c\u897f\u8fd8\u5728\u4e0d\u5728\u9876\u5c42\u300d\u3002\u771f\u8e29\u8fc7\uff1a`app = create_app()` \u88ab\u7f29\u8fdb\u5230
`create_app` \u7684\u51fd\u6570\u4f53\u91cc\uff0c\u8bed\u6cd5\u5b8c\u5168\u5408\u6cd5\u3001import \u4e5f\u4e0d\u62a5\u9519\uff0c\u4f46 uvicorn \u542f\u52a8\u65f6
`Attribute "app" not found in module "src.app.main"`\u2014\u2014\u6574\u4e2a\u5bb9\u5668\u8d77\u4e0d\u6765\u3002

\u8fd9\u7c7b\u7f3a\u9677\u53ea\u6709\u300c\u65ad\u8a00\u7b26\u53f7\u5b58\u5728\u300d\u80fd\u62d3\u5230\u3002
"""
from __future__ import annotations

import importlib

import pytest


def test_asgi_entrypoint_exists_at_module_level() -> None:
    """Dockerfile / cli.serve \u90fd\u662f `uvicorn src.app.main:app`\u3002"""
    main = importlib.import_module("src.app.main")
    app = getattr(main, "app", None)
    assert app is not None, "src.app.main.app \u4e0d\u5728\u6a21\u5757\u9876\u5c42\uff08\u5bb9\u5668\u4f1a\u76f4\u63a5\u8d77\u4e0d\u6765\uff09"
    assert callable(getattr(app, "openapi", None)), "src.app.main.app \u4e0d\u662f FastAPI \u5b9e\u4f8b"
    assert getattr(main, "create_app", None) is not None


@pytest.mark.parametrize(
    ("module", "symbols"),
    [
        (
            "src.identity",
            (
                "IdentityStore",
                "AuthContext",
                "build_auth_router",
                "build_admin_router",
                "build_auth_dependency",
                "seed_default_admin",
            ),
        ),
        (
            "src.shared.tenancy",
            ("PRIMARY_TENANT", "current_tenant", "tenant_scope", "tenant_paths", "list_tenant_ids"),
        ),
        (
            "src.shared.paths",
            (
                "palace_db",
                "ops_db",
                "market_db",
                "market_hot_db",
                "identity_db",
                "community_db",
            ),
        ),
    ],
)
def test_public_symbols_are_importable(module: str, symbols: tuple[str, ...]) -> None:
    loaded = importlib.import_module(module)
    missing = [name for name in symbols if not hasattr(loaded, name)]
    assert not missing, f"{module} \u7f3a\u5c11\u516c\u5f00\u7b26\u53f7\uff1a{missing}"


def test_optional_contexts_expose_their_router_factory() -> None:
    """community \u662f\u53ef\u9009\u80fd\u529b\uff08\u7ec4\u5408\u6839 try/except ImportError\uff09\uff0c

        \u4f46\u4e00\u65e6\u5305\u80fd\u5bfc\u5165\uff0c\u5de5\u5382\u51fd\u6570\u5c31\u5fc5\u987b\u5728\u2014\u2014\u5426\u5219\u4f1a\u9000\u5316\u6210\u300c\u9759\u9ed8\u5730\u4e0d\u6302\u8def\u7531\u300d\uff0c
        \u524d\u7aef\u62ff\u5230\u4e00\u5806 404 \u800c\u670d\u52a1\u7aef\u65e5\u5fd7\u91cc\u53ea\u6709\u4e00\u884c WARNING\u3002
        """
    community = pytest.importorskip("src.community")
    assert hasattr(community, "build_community_router")


def test_market_exposes_realtime_entrypoints() -> None:
    """\u5b9e\u65f6\u5927\u5c4f\u4f9d\u8d56\u8fd9\u51e0\u4e2a\u7b26\u53f7\uff1b\u5b83\u4eec\u6389\u4e86\u5927\u5c4f\u4f1a\u9759\u9ed8\u964d\u7ea7\u6210\u7a7a\u9875\u3002"""
    market = importlib.import_module("src.market")
    for name in ("get_live_hub", "resolve_preset"):
        assert hasattr(market, name), f"src.market \u7f3a\u5c11 {name}"
