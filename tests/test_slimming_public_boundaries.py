"""Public lifespan entrypoints delegate to their application components."""
import asyncio


def test_optional_gateway_public_entry_delegates_only_when_called(monkeypatch):
    import src.ai as api
    from src.ai.infrastructure import grpc_gateway
    calls=[]
    sentinel=object()
    async def start():
        calls.append('start')
        return sentinel
    monkeypatch.setattr(grpc_gateway,'start_from_env',start)
    assert calls == []
    assert asyncio.run(api.start_grpc_from_env()) is sentinel
    assert calls == ['start']


def test_research_recovery_public_entry_preserves_return_value(monkeypatch):
    import src.research as api
    from src.research.infrastructure import backtest_jobs
    calls=[]
    def recover():
        calls.append('recover')
        return 7
    monkeypatch.setattr(backtest_jobs,'recover_research_jobs',recover)
    assert calls == []
    assert api.recover_research_jobs() == 7
    assert calls == ['recover']
