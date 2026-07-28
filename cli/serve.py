"""运行 Loci 本地服务（无桌面窗口）。推荐用 ``python loci.py``。"""
from __future__ import annotations

import uvicorn

from src.shared.paths import ensure_data_dir


if __name__ == "__main__":
    ensure_data_dir()
    uvicorn.run("src.app.main:app", host="127.0.0.1", port=8787, reload=False)
