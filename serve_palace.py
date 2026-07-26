"""运行潜龙记忆宫殿本地服务。"""
from __future__ import annotations

import uvicorn


if __name__ == "__main__":
    uvicorn.run("src.palace_api:app", host="127.0.0.1", port=8787, reload=False)
