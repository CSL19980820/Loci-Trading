"""研究用例公开入口。"""
from src.research.application.catalog import build_research_catalog
from src.research.application.profile import (
    ResearchNotFoundError,
    build_research_profile,
    build_research_profile_from_snapshot,
)
from src.research.application.snapshot import capture_research_input
from src.research.application.readonly_engine import (
    polars_research_enabled,
    readonly_frame,
)
from src.research.application.run import (
    ResearchRunError,
    create_research_run,
    read_research_run,
    resume_research_run,
)
from src.research.application.run_card import (
    create_research_run_card,
    create_run_card,
    load_run_card,
    mark_run_card_stale,
    read_run_card,
    save_run_card,
    update_run_card_status,
)
from src.research.application.backtest_run import (
    ResearchBacktestError,
    ResearchBacktestOutcome,
    run_research_backtest,
)
from src.research.application.replay import ResearchReplayError, replay_research_backtest
from src.research.application.publication import (
    ResearchPublicationError,
    manifest_sha256,
    publish_research_backtest,
    reject_research_backtest,
)

__all__ = [
    "ResearchNotFoundError",
    "build_research_catalog",
    "build_research_profile",
    "build_research_profile_from_snapshot",
    "capture_research_input",
    "polars_research_enabled",
    "readonly_frame",
    "ResearchRunError",
    "create_research_run",
    "read_research_run",
    "resume_research_run",
    "create_research_run_card",
    "create_run_card",
    "load_run_card",
    "mark_run_card_stale",
    "read_run_card",
    "save_run_card",
    "update_run_card_status",
    "ResearchBacktestError",
    "ResearchBacktestOutcome",
    "run_research_backtest",
    "ResearchReplayError",
    "replay_research_backtest",
    "ResearchPublicationError",
    "manifest_sha256",
    "publish_research_backtest",
    "reject_research_backtest",
]
