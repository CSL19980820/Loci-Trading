"""运行 Loci 本地服务（无桌面窗口）。推荐用 ``python loci.py``。"""
from __future__ import annotations

import os

import uvicorn

from src.shared.paths import ensure_data_dir

# 工作台入口默认开调度器；pytest / 显式 PALACE_ENABLE_SCHEDULER=0 不受影响
os.environ.setdefault("PALACE_ENABLE_SCHEDULER", "1")


if __name__ == "__main__":
    ensure_data_dir()
    uvicorn.run("src.app.main:app", host="127.0.0.1", port=8787, reload=False)
