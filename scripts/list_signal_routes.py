"""列出应用里所有与信号相关的路由（含被 include 的子路由）。

用途：部署后核验新端点真的挂上了。容器里跑：
    docker exec qianlong-loci python /tmp/list_signal_routes.py
"""

from __future__ import annotations


def main() -> None:
    from src.app.main import create_app

    app = create_app()
    spec = app.openapi()
    paths = sorted(spec.get("paths", {}))
    hits = [p for p in paths if "signal" in p]
    print("TOTAL_PATHS=%d" % len(paths))
    print("SIGNAL_PATHS=%s" % hits)
    for p in hits:
        methods = sorted(m.upper() for m in spec["paths"][p])
        print("  %-45s %s" % (p, ",".join(methods)))


if __name__ == "__main__":
    main()
