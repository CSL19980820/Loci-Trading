"""显式导入已核验的历史时点数据，不写行情库或交易账本。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.backtest import import_signal_dataset
from src.shared.tenancy import tenant_scope


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--tenant", default="__primary__")
    args = parser.parse_args()
    if args.source.stat().st_size > 50_000_000:
        parser.error("数据集文件超过50MB")
    body = json.loads(args.source.read_text(encoding="utf-8"))
    with tenant_scope(args.tenant):
        receipt = import_signal_dataset(body)
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
