"""共享内核：路径与桌面快捷方式等横切能力。"""
from src.shared.paths import (
    PROJECT_ROOT,
    data_dir,
    ensure_data_dir,
    market_db,
    ops_db,
    palace_db,
    writable_root,
)

__all__ = [
    "PROJECT_ROOT",
    "data_dir",
    "ensure_data_dir",
    "market_db",
    "ops_db",
    "palace_db",
    "writable_root",
]
