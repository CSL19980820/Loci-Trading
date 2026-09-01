"""行情 CLI 的盘中留存带子命令。

从 ``cli/market.py`` 拆出来：那个文件已经贴到 600 行硬上限。
留存带的口径与安全闸门见 ``docs/adr/ADR-014-encrypted-intraday-tape-retention.md``。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def cmd_intraday_capture(args: argparse.Namespace) -> int:
    """采集今日盘中快照并加密落盘。单项失败不影响其余项。"""
    from src.market import capture_snapshots, default_specs

    specs = default_specs()
    if args.only:
        wanted = {name.strip() for name in args.only.split(',') if name.strip()}
        specs = [item for item in specs if item.dataset in wanted]
        if not specs:
            print(f"没有匹配的数据集：{args.only}")
            return 2
    report = capture_snapshots(_data_dir(args), specs, trade_date=args.date)
    body = report.to_dict()
    if args.json:
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return 0 if report.ok else 1
    print(f"交易日 {body['trade_date']}｜加密 {body['protection']}")
    for item in body['captured']:
        print(f"  ✓ {item['dataset']:<24} {item['rows']:>7,} 行  {item['bytes'] / 1e6:>6.2f} MB")
    for item in body['failures']:
        print(f"  ✗ {item['dataset']:<24} [{item['stage']}] {item['error']}")
    print(f"成功 {body['captured_count']}｜失败 {body['failure_count']}")
    return 0 if report.ok else 1


def cmd_intraday_prune(args: argparse.Namespace) -> int:
    """删掉过期的盘中留存目录。三道安全闸门见 intraday_prune 模块。"""
    from src.market import prune_intraday

    report = prune_intraday(
        _data_dir(args),
        retention_days=args.keep_days,
        dry_run=args.dry_run,
        max_delete=args.max_delete,
    )
    body = report.to_dict()
    if args.json:
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return 0
    mode = "试运行" if args.dry_run else "已删除"
    print(f"保留 {body['retention_days']} 天（早于 {body['cutoff']} 的淘汰）")
    print(f"{mode} {body['deleted_count']} 天，释放 {body['freed_mb']:,.2f} MB；保留 {body['kept']} 天")
    for name in body['deleted']:
        print(f"  - {name}")
    return 0


def cmd_intraday_status(args: argparse.Namespace) -> int:
    """盘中留存带现状。"""
    from src.market import intraday_status

    body = intraday_status(_data_dir(args))
    if args.json:
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return 0
    print(f"留存带：{body['root']}")
    print(f"天数：{body['days']}（{body['first_day']} ~ {body['last_day']}）")
    print(f"体积：{body['total_mb']:,.2f} MB｜DPAPI 可用：{body['dpapi_available']}")
    for name, days in body['datasets'].items():
        print(f"  {name:<24} {days:>4} 天")
    return 0


def _data_dir(args: argparse.Namespace) -> Path:
    """留存带跟随行情库所在目录，避免又造一套路径配置。"""
    from src.shared.paths import data_dir

    return Path(args.db).parent if args.db else data_dir()
