from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient


def test_app_and_mcp_catalog_work_without_materializing_wudao_entry(
    tmp_path: Path,
) -> None:
    """缺少悟道配置是正常状态：启动可建空配置，但不得注入悟道条目。"""
    mcp_path = Path(os.environ["PALACE_MCP_JSON"])
    assert not mcp_path.exists()

    from src.app.main import create_app
    from src.ai.application.toolbus import build_toolbus
    from src.intel import wudao_availability
    from src.shared.paths import ensure_data_dir

    # 空壳 mcp.json 由数据目录初始化落盘；不依赖「碰巧第一次 import create_app」的副作用。
    ensure_data_dir()
    assert json.loads(mcp_path.read_text(encoding="utf-8")) == {"mcpServers": {}}
    assert wudao_availability()["available"] is False
    bus = build_toolbus(
        {"mcp_servers": ["wudao"]},
        hitl_enabled=False,
    )
    # 无悟道时仍可挂内置 ask_user 等；不得挂上悟道 MCP 工具
    assert bus is not None
    mcp_names = [
        name
        for name, route in bus.routing.items()
        if str(route).startswith("mcp:")
    ]
    assert mcp_names == []
    assert not any("wudao" in name for name in bus.routing)

    app = create_app(db_path=tmp_path / "palace.db", static_dir=tmp_path / "missing-dist")
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200

        response = client.get("/api/mcp")
        assert response.status_code == 200
        rows = response.json()
        wudao = next(row for row in rows if row["name"] == "wudao")
        assert wudao["is_usable"] is False
        assert "Key" in wudao["skip_reason"]

        brief = client.get("/api/intel/brief")
        assert brief.status_code == 200
        assert brief.json()["available"] is False

    persisted = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert persisted == {"mcpServers": {}}
    assert "wudao" not in persisted["mcpServers"]
