"""后台线程 / 线程池必须带着**发起请求那个租户**的上下文。

为什么要有这一组用例：``ContextVar`` 不跨 ``threading.Thread`` 与
``ThreadPoolExecutor`` 边界（只有 asyncio Task 与 anyio 的 ``run_in_threadpool``
会复制 Context）。从请求里裸起一条线程，线程内 ``current_tenant()`` 直接落回
``PRIMARY_TENANT``——也就是管理员的老 ``data/`` 目录。这个 bug **不报错、不刷红**，
单机形态下 100% 观察不到，只会把 B 用户的结果静默写进管理员的账本。

所以这里既测「包装器确实把租户带过去了」，也测「裸 submit 确实会丢」——后者是
反向锚点；再加一条 AST 源码守卫，拦住把包装器改回裸调用的 revert。
"""
from __future__ import annotations

import ast
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.ai.application.assistant_manager import AssistantManager
from src.ai.infrastructure.assistant_store import AssistantStore
from src.ai.infrastructure.providers import save_provider
from src.ai.infrastructure.tenant_db import ops_db_for, open_ops_store
from src.shared.paths import ops_db
from src.shared.tenancy import current_tenant, submit_with_tenant, tenant_scope

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: 本批改造过的线程 / 线程池入口。守卫用例对着它们做 AST 扫描。
#: **拆文件时清单要跟着走**：被搬走的那段代码一旦不在清单里，守卫就出现盲区，
#: 而盲区是看不出来的——用例照样绿。
_GUARDED_FILES = (
    "src/ai/application/agent_execution.py",
    "src/ai/application/assistant_manager.py",
    # assistant_manager 的 `_run` 段（worker 线程里跑的那一整段，含证据子 Agent 扇出）
    # 拆到了这里；它也是「嵌套扇出也要包」这条纪律的落点。
    "src/ai/application/assistant_run_executor.py",
    "src/ai/application/assistant_evidence_agents.py",
    "src/ai/application/multi_agent.py",
    "src/ops/api/skill_runs_api.py",
    "src/strategy/api/router.py",
    "src/research/api/router.py",
    # research 的回测端点组（`_BACKTEST_EXECUTOR` + 那句 submit_with_tenant）拆到了这里。
    "src/research/api/backtest_router.py",
    "src/research/api/factor_router.py",
)


def _probe() -> tuple[str, str]:
    """线程体：报告自己看到的租户，以及**在线程内解析出来**的库路径。"""
    return current_tenant(), str(ops_db())


def _seed_tenant(tenant: str) -> str:
    """给某租户建一个可用的 provider + 会话，返回 session_id。"""
    with tenant_scope(tenant):
        with open_ops_store() as store:
            save_provider(
                store,
                name="alpha",
                protocol="openai_compatible",
                base_url="https://api.example.test/v1",
                api_key="sk-alpha",
                model="demo-model",
                validate=False,
                discover_models=False,
                is_default=True,
            )
        with AssistantStore(ops_db_for()) as store:
            return store.create_session(title=f"{tenant} 的对话")


def test_submit_with_tenant_carries_the_request_tenant_into_the_worker() -> None:
    with ThreadPoolExecutor(max_workers=1) as pool:
        # 先在主租户下跑一发：worker 线程就此建出来，它的 Context 从此定格。
        # 这正是生产里的形态——池子是进程内单例，请求来来去去，线程不换。
        pool.submit(_probe).result(timeout=10)
        with tenant_scope("u_a"):
            tenant, path = submit_with_tenant(pool, _probe).result(timeout=10)
    assert tenant == "u_a"
    assert "u_a" in path, f"线程内解析出的 ops.db 不属于发起租户：{path}"


def test_bare_submit_loses_the_tenant_which_is_exactly_the_bug() -> None:
    """反向锚点：裸 ``submit`` **必须**丢租户。

    如果哪天这条用例开始失败（裸 submit 也能带上租户了），说明 Python 或本仓的
    上下文传播语义变了，那时才可以重新讨论包装器还要不要——在那之前别删它。
    """
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(_probe).result(timeout=10)
        with tenant_scope("u_a"):
            tenant, path = pool.submit(_probe).result(timeout=10)
    assert tenant != "u_a"
    assert "u_a" not in path


def test_assistant_manager_pool_runs_the_worker_under_the_caller_tenant() -> None:
    """``AssistantManager`` 的池：worker 必须能在**发起租户**的库里读到这条 run。

    ``start_run`` 是在请求线程里把 run 行写进发起用户 ops.db 的；worker 若掉回
    主租户，``store.get_run(run_id)`` 查不到就直接 return——run 永远停在
    ``running``，那个会话从此发不出下一轮，且日志里一行红都没有。
    """
    session_id = _seed_tenant("u_a")
    manager = AssistantManager(ops_db=None)
    seen: dict[str, object] = {}
    done = threading.Event()

    def fake_run(run_id: str, *_args: object, **_kwargs: object) -> None:
        # 只抓路径，不跑真业务：这里要验的是上下文，不是 LLM。
        seen["tenant"] = current_tenant()
        seen["ops_db"] = manager.ops_db
        with AssistantStore(manager.ops_db) as store:
            seen["run"] = store.get_run(run_id)
        done.set()

    manager._run = fake_run  # type: ignore[method-assign]
    try:
        with tenant_scope("u_a"):
            run_id = manager.start_run(session_id, message="你好")
        assert done.wait(20), "worker 没有跑起来"
    finally:
        manager.close()

    assert seen["tenant"] == "u_a"
    assert "u_a" in str(seen["ops_db"])
    run = seen["run"]
    assert isinstance(run, dict) and run["id"] == run_id, (
        "worker 在自己解析出的库里读不到这条 run —— 这就是「会话永久卡 running」的现场"
    )


def test_evidence_agent_fanout_keeps_the_tenant(monkeypatch) -> None:
    """助手 worker 里再扇出的证据子 Agent 同样不能掉回主租户。

    这一层容易被漏掉：外层线程已经修好了，内层 ``ThreadPoolExecutor`` 又把它丢一
    次，于是子 Agent 读到的是管理员的行情 / 账本，还会当成用户自己的证据讲出来。
    """
    from src.ai.application import assistant_evidence_agents as mod

    seen: list[tuple[str, str]] = []

    def fake_toolbus(*_args: object, **_kwargs: object) -> object:
        seen.append((current_tenant(), str(ops_db())))
        raise RuntimeError("只验上下文，不跑模型")

    monkeypatch.setattr(mod, "build_system_toolbus", fake_toolbus)
    specs = mod.plan_evidence_roles("帮我看看潜龙候选池，再搜一下最新新闻")
    assert specs, "取不到任何证据角色，用例前提不成立"

    with tenant_scope("u_b"):
        mod.run_evidence_agents(
            config=None,
            prompt="帮我看看潜龙候选池，再搜一下最新新闻",
            palace_db=None,
            market_db=None,
            ops_db=None,
            specs=specs,
        )

    assert seen, "子 Agent 一个都没跑起来"
    for tenant, path in seen:
        assert tenant == "u_b"
        assert "u_b" in path, f"子 Agent 线程解析出的库不属于发起租户：{path}"


def test_no_bare_thread_or_submit_left_in_the_changed_entrypoints() -> None:
    """源码守卫：这几个文件里不许再出现 ``threading.Thread(...)`` / ``x.submit(...)``。

    注释会被人读，但只有断言拦得住 revert。用 AST 而不是 grep：注释与文档串里的
    ``threading.Thread(`` 是**说明**，不该算残留。
    """
    offenders: list[str] = []
    for rel in _GUARDED_FILES:
        tree = ast.parse((_REPO_ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            bare_thread = (
                func.attr == "Thread"
                and isinstance(func.value, ast.Name)
                and func.value.id == "threading"
            )
            if bare_thread or func.attr == "submit":
                offenders.append(f"{rel}:{node.lineno} -> {ast.unparse(func)}(...)")
    assert not offenders, (
        "这些位置绕开了租户包装器；请改用 src.shared.tenancy 的 "
        "spawn_tenant_thread / submit_with_tenant：" + str(offenders)
    )


def test_skill_ammo_agent_fanout_keeps_the_tenant(monkeypatch) -> None:
    """Skill 的弹药子 agent 扇出同样要带租户。

    它跑在已带租户的 Skill worker 线程里，内层线程池会再丢一次上下文：子 agent 的
    CLI 与 MCP 调用会按主租户解析技能目录与 ``mcp.json``（后者是租户私有的，等于
    拿管理员的悟道 Key 去打人家的配额）。
    """
    from src.ai.application import multi_agent as mod

    seen: list[tuple[str, str]] = []

    def fake_cli(*_args: object, **_kwargs: object) -> dict[str, object]:
        seen.append((current_tenant(), str(ops_db())))
        return {"id": "x", "ok": True, "text": "done"}

    monkeypatch.setattr(mod, "_run_cli_agent", fake_cli)
    skill = {"agents": [{"id": "a1", "kind": "cli"}, {"id": "a2", "kind": "cli"}]}

    with tenant_scope("u_b"):
        mod.run_ammo_agents(skill)

    assert len(seen) == 2, "两个弹药子 agent 应当都跑到"
    for tenant, path in seen:
        assert tenant == "u_b"
        assert "u_b" in path, f"子 agent 线程解析出的库不属于发起租户：{path}"
