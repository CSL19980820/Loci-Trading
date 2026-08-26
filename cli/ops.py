#!/usr/bin/env python
"""技能包、定时任务与 LLM 供应商的命令行入口。

    # 技能包：给一个 zip，就多一个可定时运行的模式
    python ops.py skill install ./my-skill.zip
    python ops.py skill list
    python ops.py skill remove dragon-return

    # LLM 供应商：名称 + Base URL + Key + 协议，不硬编码厂商
    python ops.py provider add --name openrouter \
        --base-url https://openrouter.ai/api/v1 --key sk-xxx
    python ops.py provider list
    python ops.py provider models openrouter

    # 定时任务：选股、回测、行情同步、技能模式，四类走同一套调度与留痕
    python ops.py job add 盘后同步 sync --cron "35 15 * * 1-5"
    python ops.py job add 潜龙选股 screen --cron "47 15 * * 1-5" \
        --config '{"strategy":"qianlong-close"}'
    python ops.py job add 盘后简报 skill --cron "40 15 * * 1-5" \
        --config '{"skill":"dragon-return","provider":"openrouter","context":["screen"]}'
    python ops.py job run 盘后同步
    python ops.py job list
    python ops.py runs --limit 10

    # 前台常驻调度（生产环境由 FastAPI 生命周期接管）
    python ops.py serve
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
import time

from src.ops import (
    DEFAULT_DB,
    DEFAULT_SKILL_ROOT,
    JOB_KINDS,
    JobContext,
    JobScheduler,
    OpsStore,
    SkillError,
    discover_skills,
    install_skill,
    run_job,
    set_skill_enabled,
    uninstall_skill,
    validate_cron,
)

DISCLAIMER = "本工具仅用于信息整理与方法论辅助，输出不构成任何投资建议。"


def _store(args: argparse.Namespace) -> OpsStore:
    return OpsStore(args.db)


def _context(args: argparse.Namespace, store: OpsStore) -> JobContext:
    return JobContext(
        market_db=args.market_db or None,
        ops_store=store,
        skill_root=str(DEFAULT_SKILL_ROOT),
    )


# ---- 技能包 ---------------------------------------------------------

def cmd_skill_install(args: argparse.Namespace) -> int:
    package = install_skill(args.archive, overwrite=not args.no_overwrite)
    print(f"已安装技能：{package.slug}  ({package.name} v{package.version or '—'})")
    print(f"  描述      {package.description}")
    print(f"  安装位置  {package.install_path}")
    print(f"  文件      {len(package.files)} 个：{', '.join(package.files[:6])}"
          + (" ..." if len(package.files) > 6 else ""))
    if package.allowed_tools:
        print(f"  声明工具  {', '.join(package.allowed_tools)}")
    print("  调度方式  请在系统的「技能配置」中设置")
    return 0


def cmd_skill_list(args: argparse.Namespace) -> int:
    skills = discover_skills()
    if not skills:
        print("尚未安装任何技能。安装方式：python ops.py skill install <zip>")
        print("或复制目录到 data/skills/<slug>/SKILL.md")
        return 0
    for skill in skills:
        flag = "" if skill.enabled else "  [已停用]"
        print(f"{skill.slug:<24} {skill.name} v{skill.version or '—'}{flag}")
        print(f"  {skill.description}")
    return 0


def cmd_skill_remove(args: argparse.Namespace) -> int:
    removed_fs = uninstall_skill(args.slug)
    if not removed_fs:
        print(f"没有找到技能：{args.slug}", file=sys.stderr)
        return 1
    print(f"已卸载技能：{args.slug}")
    return 0


def cmd_skill_toggle(args: argparse.Namespace) -> int:
    try:
        set_skill_enabled(args.slug, args.enabled == "on")
    except SkillError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"技能 {args.slug} 已{'启用' if args.enabled == 'on' else '停用'}")
    return 0


# ---- LLM 供应商 -----------------------------------------------------

def cmd_provider_add(args: argparse.Namespace) -> int:
    from src.ai import save_provider

    with _store(args) as store:
        record = save_provider(
            store,
            name=args.name,
            protocol=args.protocol,
            base_url=args.base_url,
            api_key=args.key or None,
            model=args.model,
            proxy_url=args.proxy,
            note=args.note,
            validate=not args.no_validate,
            discover_models=not args.no_discover,
        )
    print(f"已保存供应商：{record['name']}（{record['protocol']}）")
    print(f"  Base URL   {record['base_url']}")
    print(f"  密钥       {record['key_last4'] or '（沿用原有）'}")
    print(f"  默认模型   {record['default_model'] or '—'}")
    if record["models"]:
        print(f"  可用模型   {len(record['models'])} 个，例：{', '.join(record['models'][:4])}")
    if record["validated_at"]:
        print(f"  已校验     {record['validated_at']}")
    if record.get("proxy_url"):
        print(f"  代理       {record['proxy_url']}")
    return 0


def cmd_provider_list(args: argparse.Namespace) -> int:
    with _store(args) as store:
        providers = store.list_providers()
    if not providers:
        print("尚未配置任何 LLM 供应商。")
        print("实测服务器直连可达且无需代理：OpenRouter、DeepSeek。")
        return 0
    for item in providers:
        state = "" if item["is_active"] else "  [停用]"
        print(f"{item['name']:<18} {item['protocol']:<20} {item['base_url']}{state}")
        print(f"  密钥 {item['key_last4'] or '未设置'}   默认模型 {item['default_model'] or '—'}"
              f"   模型数 {len(item.get('model_catalog') or item['models'])}"
              f"   启用 {len(item['models'])}")
    return 0


def cmd_provider_models(args: argparse.Namespace) -> int:
    from src.ai import refresh_models

    with _store(args) as store:
        catalog = refresh_models(store, args.name)
    if not catalog:
        print("该供应商未提供模型列表接口（例如 Anthropic 官方），请手动指定模型名。")
        return 0
    print(f"共 {len(catalog)} 个模型：")
    for item in catalog:
        flag = "" if item.get("enabled", True) else " [停用]"
        ctx = item.get("context_window")
        ctx_s = f"  ctx={ctx}" if ctx else ""
        print(f"  {item['id']}{flag}{ctx_s}")
    return 0


def cmd_provider_remove(args: argparse.Namespace) -> int:
    with _store(args) as store:
        if not store.delete_provider(args.name):
            print(f"没有找到供应商：{args.name}", file=sys.stderr)
            return 1
    print(f"已删除供应商：{args.name}")
    return 0


# ---- MCP server -----------------------------------------------------

def cmd_mcp_add(args: argparse.Namespace) -> int:
    from src.intel import save_server

    record = save_server(
        name=args.name,
        url=args.url,
        token=args.token or None,
        proxy_url=args.proxy,
        note=args.note,
        verify=not args.no_verify,
    )
    print(f"已注册 MCP server：{record['name']}（写入 data/mcp.json）")
    print(f"  URL        {record['url']}")
    print(f"  令牌       {record['token_last4'] or '（无）'}")
    print(f"  发现工具   {len(record['tools'])} 个")
    if record["tools"]:
        names = [t["name"] for t in record["tools"][:10]]
        print(f"  样例       {', '.join(names)}")
        print()
        print("在技能任务里这样用（tools 留空则用技能包 SKILL.md 声明的那几个）：")
        print(f"  --config '{{\"skill\":\"<技能>\",\"provider\":\"<供应商>\","
              f"\"mcp_servers\":[\"{record['name']}\"]}}'")
    return 0


def cmd_mcp_list(args: argparse.Namespace) -> int:
    from src.intel import list_effective_mcp_servers

    servers = list_effective_mcp_servers(active_only=False)
    if not servers:
        print("尚未注册任何 MCP server（检查 data/mcp.json）。")
        return 0
    for item in servers:
        state = "" if item["is_active"] else "  [停用]"
        print(f"{item['name']:<16} {item['url']}{state}")
        print(f"  令牌 {item['token_last4'] or '无'}   工具 {len(item['tools'])} 个"
              f"   同步于 {item['tools_synced_at'] or '—'}")
    return 0


def cmd_mcp_tools(args: argparse.Namespace) -> int:
    from src.intel import refresh_tools

    tools = refresh_tools(args.name)
    print(f"共 {len(tools)} 个工具：")
    for tool in tools:
        desc = " ".join((tool["description"] or "").split())[:88]
        print(f"  {tool['name']:<28} {desc}")
    return 0


def cmd_mcp_call(args: argparse.Namespace) -> int:
    from src.intel import build_client

    payload = json.loads(args.args) if args.args else {}
    client = build_client(args.name)
    result = client.call_tool(args.tool, payload)
    if result["is_error"]:
        print("调用返回错误：", file=sys.stderr)
    print(result["text"][:6000])
    return 1 if result["is_error"] else 0


def cmd_mcp_remove(args: argparse.Namespace) -> int:
    from src.intel import delete_server

    if not delete_server(args.name):
        print(f"没有找到 MCP server：{args.name}", file=sys.stderr)
        return 1
    print(f"已删除 MCP server：{args.name}")
    return 0


# ---- 定时任务 -------------------------------------------------------

def cmd_job_add(args: argparse.Namespace) -> int:
    config = json.loads(args.config) if args.config else {}
    if args.cron:
        validate_cron(args.cron)  # 写错的 cron 当场报错，不留到不触发时才发现
    with _store(args) as store:
        job_id = store.create_job(
            name=args.name, kind=args.kind, cron=args.cron, config=config
        )
    print(f"已创建任务：{args.name}（{args.kind}）id={job_id}")
    if args.cron:
        print(f"  调度 {args.cron}")
    else:
        print("  未设置 cron，只能手动触发：python ops.py job run " + args.name)
    return 0


def cmd_job_list(args: argparse.Namespace) -> int:
    with _store(args) as store:
        jobs = store.list_jobs()
    if not jobs:
        print("尚未创建任何任务。")
        return 0
    for job in jobs:
        state = "" if job["enabled"] else "  [已停用]"
        print(f"{job['name']:<20} {job['kind']:<10} {job['cron'] or '（手动）':<16}"
              f" 上次 {job['last_status'] or '—'} {job['last_run_at'] or ''}{state}")
        if job["config"]:
            print(f"  配置 {json.dumps(job['config'], ensure_ascii=False)}")
    return 0


def cmd_job_run(args: argparse.Namespace) -> int:
    with _store(args) as store:
        outcome = run_job(store, args.name, context=_context(args, store), trigger="manual")
    if outcome["status"] == "failed":
        print(f"任务失败：{outcome['error']}", file=sys.stderr)
        return 1
    print(f"任务完成，耗时 {outcome['duration_ms']} ms")
    print(json.dumps(outcome["result"], ensure_ascii=False, indent=2, default=str)[:4000])
    print()
    print(DISCLAIMER)
    return 0


def cmd_job_remove(args: argparse.Namespace) -> int:
    with _store(args) as store:
        job = store.get_job_by_name(args.name) or store.get_job(args.name)
        if job is None or not store.delete_job(job["id"]):
            print(f"没有找到任务：{args.name}", file=sys.stderr)
            return 1
    print(f"已删除任务：{args.name}")
    return 0


def cmd_job_toggle(args: argparse.Namespace) -> int:
    with _store(args) as store:
        job = store.get_job_by_name(args.name) or store.get_job(args.name)
        if job is None:
            print(f"没有找到任务：{args.name}", file=sys.stderr)
            return 1
        store.update_job(job["id"], enabled=args.enabled == "on")
    print(f"任务 {args.name} 已{'启用' if args.enabled == 'on' else '停用'}")
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    with _store(args) as store:
        runs = store.list_runs(limit=args.limit, status=args.status or None)
    if not runs:
        print("还没有执行记录。")
        return 0
    for run in runs:
        mark = {"success": "✓", "failed": "✗", "running": "…"}.get(run["status"], "?")
        print(f"{mark} {run['started_at']}  {run['job_name']:<18} {run['kind']:<10}"
              f" {run['trigger']:<9} {run['duration_ms']:>7} ms")
        if run["status"] == "failed" and run["error_text"]:
            print(f"    {run['error_text'].splitlines()[0][:150]}")
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    with _store(args) as store:
        removed = store.prune_runs(keep_per_job=args.keep)
    print(f"已清理 {removed} 条历史执行记录（每个任务保留最近 {args.keep} 条）")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    scheduler = JobScheduler(
        db_path=args.db,
        context_factory=lambda: JobContext(market_db=args.market_db or None),
    )
    scheduler.start()
    plan = scheduler.reload()
    print(f"调度器已启动，装载 {plan['count']} 个任务：{', '.join(plan['loaded']) or '（无）'}")
    for rejected in plan["rejected"]:
        print(f"  ✗ {rejected['name']}：{rejected['reason']}", file=sys.stderr)
    for item in scheduler.upcoming():
        print(f"  下次触发 {item['next_run_at']}  {item['name']}")
    print("Ctrl+C 退出。")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n正在停止调度器 ...")
        scheduler.shutdown(wait=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="潜龙运维：技能包 / 定时任务 / LLM 供应商",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help="运维库路径")
    parser.add_argument("--market-db", default="", help="行情库路径（任务执行时用）")
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    skill = sub.add_parser("skill", help="技能包管理").add_subparsers(dest="action", required=True)
    install = skill.add_parser("install", help="安装技能包 zip")
    install.add_argument("archive")
    install.add_argument("--no-overwrite", action="store_true", help="已存在时报错而非覆盖")
    install.set_defaults(func=cmd_skill_install)
    skill.add_parser("list", help="列出已安装技能").set_defaults(func=cmd_skill_list)
    remove = skill.add_parser("remove", help="卸载技能")
    remove.add_argument("slug")
    remove.set_defaults(func=cmd_skill_remove)
    toggle = skill.add_parser("toggle", help="启用/停用技能")
    toggle.add_argument("slug")
    toggle.add_argument("enabled", choices=["on", "off"])
    toggle.set_defaults(func=cmd_skill_toggle)

    provider = sub.add_parser("provider", help="LLM 供应商管理").add_subparsers(
        dest="action", required=True
    )
    add = provider.add_parser("add", help="新增或更新供应商")
    add.add_argument("--name", required=True)
    add.add_argument("--base-url", required=True, dest="base_url")
    add.add_argument("--key", default="", help="API Key；留空表示沿用已保存的")
    add.add_argument(
        "--protocol", default="openai_compatible",
        choices=["openai_compatible", "anthropic"],
        help="绝大多数供应商都是 openai_compatible",
    )
    add.add_argument("--model", default="", help="默认模型；留空则自动取列表第一个")
    add.add_argument("--proxy", default="", help="该供应商专用代理，如 http://172.17.0.1:7890")
    add.add_argument("--note", default="")
    add.add_argument("--no-validate", action="store_true", help="跳过 Key 有效性校验")
    add.add_argument("--no-discover", action="store_true", help="跳过自动拉取模型列表")
    add.set_defaults(func=cmd_provider_add)
    provider.add_parser("list", help="列出供应商").set_defaults(func=cmd_provider_list)
    models = provider.add_parser("models", help="刷新并列出可用模型")
    models.add_argument("name")
    models.set_defaults(func=cmd_provider_models)
    premove = provider.add_parser("remove", help="删除供应商")
    premove.add_argument("name")
    premove.set_defaults(func=cmd_provider_remove)

    mcp = sub.add_parser("mcp", help="外部 MCP 数据源").add_subparsers(dest="action", required=True)
    madd = mcp.add_parser("add", help="注册 MCP server（会当场握手并拉工具列表）")
    madd.add_argument("--name", required=True)
    madd.add_argument("--url", required=True)
    madd.add_argument("--token", default="", help="Bearer 令牌")
    madd.add_argument("--proxy", default="", help="该 server 专用代理")
    madd.add_argument("--note", default="")
    madd.add_argument("--no-verify", action="store_true", help="跳过连接校验")
    madd.set_defaults(func=cmd_mcp_add)
    mcp.add_parser("list", help="列出已注册 server").set_defaults(func=cmd_mcp_list)
    mtools = mcp.add_parser("tools", help="刷新并列出工具")
    mtools.add_argument("name")
    mtools.set_defaults(func=cmd_mcp_tools)
    mcall = mcp.add_parser("call", help="直接调一个工具（排障用）")
    mcall.add_argument("name")
    mcall.add_argument("tool")
    mcall.add_argument("--args", default="", help="参数 JSON")
    mcall.set_defaults(func=cmd_mcp_call)
    mremove = mcp.add_parser("remove", help="删除 server")
    mremove.add_argument("name")
    mremove.set_defaults(func=cmd_mcp_remove)

    job = sub.add_parser("job", help="定时任务管理").add_subparsers(dest="action", required=True)
    jadd = job.add_parser("add", help="创建任务")
    jadd.add_argument("name")
    jadd.add_argument("kind", choices=list(JOB_KINDS))
    jadd.add_argument("--cron", default="", help="5 字段 cron，如 '35 15 * * 1-5'")
    jadd.add_argument("--config", default="", help="该类型的配置 JSON")
    jadd.set_defaults(func=cmd_job_add)
    job.add_parser("list", help="列出任务").set_defaults(func=cmd_job_list)
    jrun = job.add_parser("run", help="立即执行一次")
    jrun.add_argument("name")
    jrun.set_defaults(func=cmd_job_run)
    jremove = job.add_parser("remove", help="删除任务")
    jremove.add_argument("name")
    jremove.set_defaults(func=cmd_job_remove)
    jtoggle = job.add_parser("toggle", help="启用/停用任务")
    jtoggle.add_argument("name")
    jtoggle.add_argument("enabled", choices=["on", "off"])
    jtoggle.set_defaults(func=cmd_job_toggle)

    runs = sub.add_parser("runs", help="查看执行历史")
    runs.add_argument("--limit", type=int, default=20)
    runs.add_argument("--status", default="", choices=["", "success", "failed", "running"])
    runs.set_defaults(func=cmd_runs)

    prune = sub.add_parser("prune", help="清理历史执行记录")
    prune.add_argument("--keep", type=int, default=200)
    prune.set_defaults(func=cmd_prune)

    sub.add_parser("serve", help="前台运行调度器").set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return int(args.func(args))
    except Exception as exc:
        # 业务错误（配额用尽、数据未就绪、配置不对）不该以裸 traceback 呈现——
        # 那看起来像程序崩了，其实是外部服务在如实告诉你一件事。
        # 需要堆栈时加 --verbose。
        if args.verbose:
            raise
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
