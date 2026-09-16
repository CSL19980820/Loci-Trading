"""Per-invocation accounting for completed responses, including exceptional exits."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict, dataclass
from functools import wraps
from typing import Callable, Concatenate, ParamSpec, TypeVar

from src.ai.infrastructure.client import ChatResponse, ProviderConfig

P = ParamSpec("P")
R = TypeVar("R")


@dataclass
class AgentUsage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    rounds: int = 0

    def record(self, response: ChatResponse) -> ChatResponse:
        # A returned response is known usage even when the next checkpoint stops the run.
        self.input_tokens += response.input_tokens
        self.output_tokens += response.output_tokens
        self.rounds += 1
        self.model = response.model or self.model
        return response


_CURRENT_USAGE: ContextVar[AgentUsage] = ContextVar("agent_usage")


def current_agent_usage() -> AgentUsage:
    return _CURRENT_USAGE.get()


def capture_agent_usage(
    run: Callable[Concatenate[ProviderConfig, P], R],
) -> Callable[Concatenate[ProviderConfig, P], R]:
    @wraps(run)
    def wrapped(config: ProviderConfig, *args: P.args, **kwargs: P.kwargs) -> R:
        usage = AgentUsage(model=config.model)
        token = _CURRENT_USAGE.set(usage)
        try:
            return run(config, *args, **kwargs)
        except BaseException as exc:
            # Preserve the original stop, including asyncio cancellation; never invent in-flight tokens.
            exc.usage = asdict(usage)
            raise
        finally:
            _CURRENT_USAGE.reset(token)

    return wrapped
