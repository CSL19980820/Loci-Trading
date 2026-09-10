"""数据位置和桌面运行设置 HTTP。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from src.ops.api.schemas import DataLocationUpdate
from src.shared.api_deps import market_store


class DesktopPrefsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minimize_to_tray: bool | None = None


def build_system_settings_router(
    *,
    write_dependency,
    market_db: str | None = None,
    setup_access_allowed=None,
) -> APIRouter:
    """构造数据目录与桌面偏好路由。"""
    router = APIRouter()
    write_guard = Depends(write_dependency)

    def _market():
        return market_store(market_db)

    def _data_location_snapshot() -> dict[str, Any]:
        from src.shared.paths import (
            MARKET_POPULATED_BYTES,
            config_path,
            data_dir,
            default_data_dir,
            discover_data_dirs,
            load_config,
            market_db as current_market_db,
            market_db_size,
            needs_setup,
            setup_done,
            writable_root,
        )

        root = data_dir()
        size = market_db_size(root)
        needed = True
        coverage: dict[str, Any] = {}
        try:
            with _market() as store:
                coverage = store.coverage()
            needed = int(coverage.get("rows") or 0) == 0
        except Exception:
            needed = size < MARKET_POPULATED_BYTES
        config = load_config()
        must_setup = needs_setup()
        return {
            "data_dir": str(root),
            "default_dir": str(default_data_dir()),
            "install_dir": str(writable_root()),
            "config_path": str(config_path()),
            "market_db": str(current_market_db()),
            "market_bytes": size,
            "needed_bootstrap": needed,
            "setup_done": setup_done() and not must_setup,
            "needs_setup": must_setup,
            "coverage": coverage,
            "discovered_dirs": discover_data_dirs(),
            "config": {
                "data_dir": config.get("data_dir"),
                "setup_done": bool(config.get("setup_done")),
            },
        }

    def _reject_when_data_dir_is_pinned() -> None:
        """数据目录被环境变量钉住时，拒绝经接口改写。

        `src.shared.paths.data_dir()` 的取值顺序是 LOCI_DATA_DIR → PALACE_DATA_DIR →
        配置文件。生产镜像里 `ENV LOCI_DATA_DIR=/app/data` 是硬编码的，所以写进
        loci.config.json 的值**根本不会生效**——但旧实现照样会在请求给的任意绝对
        路径上 mkdir、写探针、建三个 SQLite 库，而生产容器以 root 跑。

        2026-09 安全审查（AUTHZ-DATA-LOCATION-002，high）：这个端点只挂 write guard，
        任何已登录租户都能调，等于「非管理员可在容器内任意路径以 root 造文件」。
        改路径本身在这种部署下是无效操作，所以这里直接拒绝：把「静默无效 + 真实副
        作用」换成「明确拒绝」。桌面单机不设这两个环境变量，行为不变。
        """
        pinned = os.environ.get("LOCI_DATA_DIR") or os.environ.get("PALACE_DATA_DIR")
        if not pinned:
            return
        raise HTTPException(
            status_code=409,
            detail=(
                f"本部署的数据目录由环境变量固定（{pinned}），不能经接口改写。"
                "要换目录请改部署配置后重启。"
            ),
        )

    @router.get("/api/ops/data-location", tags=["ops"])
    def get_data_location() -> dict[str, Any]:
        """当前数据目录、默认路径、是否需要初始化行情。"""
        return _data_location_snapshot()

    @router.post("/api/ops/data-location", tags=["ops"])
    def post_data_location(
        payload: DataLocationUpdate,
        request: Request,
    ) -> dict[str, Any]:
        """写入 loci.config.json，并初始化目录 / 三库空 schema。改路径通常需重启。

        首次向导仅允许组合根明确放行的本机请求免登录；其余情况需已登录。
        """
        from src.shared.paths import apply_data_dir, data_dir, initialize_data_layout, needs_setup

        initial_setup_allowed = bool(
            needs_setup()
            and setup_access_allowed is not None
            and setup_access_allowed(request)
        )
        if not initial_setup_allowed:
            write_dependency(request)
        _reject_when_data_dir_is_pinned()

        raw = (payload.data_dir or "").strip()
        if not raw:
            raise HTTPException(status_code=422, detail="数据目录不能为空")
        target = Path(raw).expanduser()
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".loci-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except OSError as exc:
            raise HTTPException(
                status_code=422, detail=f"无法写入该目录：{exc}"
            ) from exc

        before = data_dir().resolve()
        applied = apply_data_dir(target, mark_setup_done=payload.setup_done)
        try:
            initialize_data_layout(applied)
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"初始化数据目录失败：{exc}"
            ) from exc
        restart_required = applied.resolve() != before
        snapshot = _data_location_snapshot()
        # snapshot 仍读旧进程内的 data_dir()（env/已加载路径）；用 applied 覆盖展示
        snapshot["data_dir"] = str(applied)
        snapshot["pending_data_dir"] = str(applied)
        snapshot["restart_required"] = restart_required
        snapshot["setup_done"] = True if payload.setup_done else snapshot["setup_done"]
        snapshot["needs_setup"] = False if payload.setup_done else snapshot.get("needs_setup", True)
        snapshot["message"] = (
            "已保存并初始化。请关闭并重新打开 Loci 使新目录生效。"
            if restart_required
            else "已保存并完成目录初始化。"
        )
        return snapshot

    @router.post("/api/ops/desktop-shortcut", tags=["ops"])
    def post_desktop_shortcut(_write: None = write_guard) -> dict[str, Any]:
        """在当前用户桌面创建 Loci 快捷方式（仅桌面单机形态）。"""
        # 服务端部署没有桌面；这个端点只挂 write guard，留着等于给任意租户一个
        # 往容器文件系统写文件的入口。同一条守卫复用部署形态判断。
        _reject_when_data_dir_is_pinned()
        try:
            from src.shared.desktop_shortcut import create_desktop_shortcut

            info = create_desktop_shortcut()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"ok": True, **info}

    @router.get("/api/ops/desktop-prefs", tags=["ops"])
    def get_desktop_prefs() -> dict[str, Any]:
        from src.shared.desktop_prefs import load_desktop_prefs

        prefs = load_desktop_prefs()
        return {"minimize_to_tray": bool(prefs.get("minimize_to_tray", True))}

    @router.put("/api/ops/desktop-prefs", tags=["ops"])
    def put_desktop_prefs(
        payload: DesktopPrefsUpdate, _write: None = write_guard
    ) -> dict[str, Any]:
        from src.shared.desktop_prefs import save_desktop_prefs

        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=422, detail="没有可更新的字段")
        prefs = save_desktop_prefs(updates)
        return {"minimize_to_tray": bool(prefs.get("minimize_to_tray", True))}

    return router
