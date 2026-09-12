"""压缩仅覆盖状态JSON，仍继承认证来源头与流式连接设置。"""
from pathlib import Path
import re
import pytest

CONFIG = Path(__file__).resolve().parents[2] / "deploy/nginx/qianlong.chenkit.cloud.conf"
pytestmark = pytest.mark.skipif(not CONFIG.exists(), reason="部署配置按仓库约定不入库，仅在本地部署环境验收")


def test_status_compression_is_scoped_to_json_endpoint() -> None:
    text = (Path(__file__).resolve().parents[2] / "deploy/nginx/qianlong.chenkit.cloud.conf").read_text(encoding="utf-8")
    match = re.search(r"location = /api/screen/run\s*\{([^}]+)\}", text)
    assert match is not None
    block = match.group(1)
    assert "gzip on;" in block
    assert "gzip_types application/json;" in block
    assert "gzip_vary on;" in block
    assert "proxy_pass http://127.0.0.1:__LOCI_HOST_PORT__;" in block
    remaining = text[:match.start()] + text[match.end():]
    assert not re.search(r"^\s*gzip\s+on;", remaining, re.MULTILINE)


def test_status_and_default_proxy_share_auth_and_streaming_settings() -> None:
    text = (Path(__file__).resolve().parents[2] / "deploy/nginx/qianlong.chenkit.cloud.conf").read_text(encoding="utf-8")
    shared = text[:text.index("location = /api/screen/run")]
    for directive in (
        "proxy_set_header Host $host;", "proxy_set_header X-Real-IP $remote_addr;",
        "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
        "proxy_set_header X-Forwarded-Proto $scheme;",
        "proxy_set_header Connection $qianlong_connection_upgrade;",
        "proxy_buffering off;", "proxy_request_buffering off;",
    ):
        assert directive in shared
