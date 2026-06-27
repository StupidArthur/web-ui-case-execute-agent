"""Web UI 自动化测试执行 Agent。

提供程序级入口 `run_case`，以及 typer CLI 入口。
"""

from agent.core.agent import run_case
from agent.core.models import RunResult, Event

__all__ = ["run_case", "RunResult", "Event"]
