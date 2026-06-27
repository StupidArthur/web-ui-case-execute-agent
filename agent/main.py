"""typer CLI 入口。"""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path
from typing import Optional

import typer

from agent import run_case
from agent.core.models import Event

app = typer.Typer(no_args_is_help=True)


@app.callback()
def callback() -> None:
    """Web UI 自动化测试执行器。"""
    pass


def _render_event(event: Event) -> None:
    """将事件渲染为终端输出。"""
    if event.type == "parse_done":
        typer.echo(f"用例: {event.payload.get('case_name')} 共 {event.payload.get('total')} 步")
    elif event.type == "step_start":
        typer.echo(
            f"\n【步骤 {event.step_index}/{event.total}】"
            f"操作: {event.payload.get('action')} {event.payload.get('target')}"
        )
    elif event.type == "grounding":
        if event.payload.get("found"):
            typer.echo(
                f"  定位: {event.payload.get('role')} \"{event.payload.get('name')}\" "
                f"ref={event.payload.get('ref')}"
            )
        else:
            typer.echo(f"  定位失败: {event.payload.get('rationale')}")
    elif event.type == "verify":
        status = "通过" if event.payload.get("pass") else "未通过"
        typer.echo(f"  校验{status}: {event.payload.get('reason')}")
    elif event.type == "warn":
        typer.echo(f"  警告: {event.payload.get('原因')}")
    elif event.type == "fail":
        typer.echo(f"  失败: {event.payload.get('error')}")
        typer.echo(f"  截图: {event.payload.get('screenshot')}")
    elif event.type == "step_done":
        typer.echo(f"  完成: {event.payload.get('status')}")
    elif event.type == "finish":
        finished = event.payload.get("finished")
        typer.echo(
            f"\n执行结束: passed={event.payload.get('passed')} "
            f"failed={event.payload.get('failed')} finished={finished}"
        )


@app.command()
def run(
    case_file: Path = typer.Argument(..., exists=True, readable=True, help="用例文件路径"),
    headed: bool = typer.Option(False, "--headed", help="headed 模式运行浏览器"),
    trace: bool = typer.Option(False, "--trace", help="启用 Playwright trace"),
) -> None:
    """执行 Web UI 测试用例。"""

    loop = asyncio.get_event_loop()

    def _signal_handler(sig, frame):
        typer.echo("\n收到中断信号，正在退出...")
        for task in asyncio.all_tasks(loop):
            task.cancel()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    async def _main() -> None:
        result = await run_case(str(case_file), headed=headed, trace=trace, on_event=_render_event)
        typer.echo(f"报告路径: {result.report_path}")

    try:
        asyncio.run(_main())
    except asyncio.CancelledError:
        typer.echo("已取消执行")


if __name__ == "__main__":
    app()
