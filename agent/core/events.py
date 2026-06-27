"""事件流辅助。"""

from __future__ import annotations

from agent.core.models import Event, EventCallback


def make_emitter(on_event: EventCallback | None, total: int):
    """创建事件发射函数。"""
    if on_event is None:
        def noop(type_: str, step_index: int, payload: dict | None = None) -> None:
            pass
        return noop

    def emit(type_: str, step_index: int, payload: dict | None = None) -> None:
        on_event(Event(type=type_, step_index=step_index, total=total, payload=payload or {}))

    return emit
