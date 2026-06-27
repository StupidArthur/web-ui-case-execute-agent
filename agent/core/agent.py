"""状态机：用例执行编排。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from playwright.async_api import async_playwright

from agent.core.browser import Browser
from agent.core.case_parser import NEEDS_GROUNDING, parse_case
from agent.core.events import make_emitter
from agent.core.grounding import Grounding, GroundingError
from agent.core.models import Case, Event, GroundingResult, OptimizationSignal, RunResult, Step, StepRecord, Verdict
from agent.core.reporter import write_report
from agent.core.verifier import Verifier


class StepAbortError(Exception):
    """步骤最终失败，触发熔断。"""

    pass


@dataclass
class Agent:
    """执行单个测试用例的状态机。"""

    case: Case
    browser: Browser
    on_event: Callable[[Event], None] | None = None

    records: list[StepRecord] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    aborted: bool = False
    abort_step: int | None = None
    optimize_signals: list[OptimizationSignal] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)

    def __post_init__(self):
        self._emit = make_emitter(self.on_event, total=len(self.case.steps))
        self.grounding = Grounding()
        self.verifier = Verifier()

    async def run(self) -> RunResult:
        """执行用例主循环。"""
        self._emit(
            "parse_done",
            0,
            payload={
                "case_name": self.case.name,
                "total": len(self.case.steps),
                "steps": [(s.index, s.raw_text[:60]) for s in self.case.steps],
            },
        )

        report_path = ""
        try:
            await self.browser.page.goto(self.case.start_url, wait_until="domcontentloaded")
            await self.browser.wait_for_navigation_settle()

            for step in self.case.steps:
                await self.execute_step(step)

        except StepAbortError as e:
            self.exceptions.append(f"在第{self.abort_step}步异常中止: {e}")
        except Exception as e:
            self.exceptions.append(f"执行异常: {type(e).__name__}: {e}")
            self.aborted = True
        finally:
            report_path = write_report(
                case=self.case,
                records=self.records,
                optimize_signals=self.optimize_signals,
                exceptions=self.exceptions,
                abort_step=self.abort_step,
                finished=not self.aborted and len(self.records) == len(self.case.steps),
            )
            self._emit(
                "finish",
                self.abort_step or 0,
                payload={
                    "passed": self.passed,
                    "failed": self.failed,
                    "finished": not self.aborted and len(self.records) == len(self.case.steps),
                    "abort_step": self.abort_step,
                    "report_path": report_path,
                },
            )

        finished = not self.aborted and len(self.records) == len(self.case.steps)
        return RunResult(
            case_name=self.case.name,
            total=len(self.case.steps),
            passed=self.passed,
            failed=self.failed,
            finished=finished,
            abort_step=self.abort_step,
            report_path=report_path,
            exceptions=self.exceptions,
        )

    async def execute_step(self, step: Step):
        """单步执行：3 次重试，失败熔断。"""
        self._emit(
            "step_start",
            step.index,
            payload={"action": step.action_type, "target": step.target_ref},
        )
        record = StepRecord(
            step=f"步骤{step.index}: {step.raw_text[:40]}",
            operation="",
            actual_result="",
            status="失败",
            error="无",
        )

        # AI 对话界面特殊规则：每步开始前滚 chat-history 到底
        await self.browser.scroll_chat_to_bottom_if_exists()

        success = False
        last_error = ""
        start_time = time.time()
        cached_gr: GroundingResult | None = None

        for attempt in range(1, 4):
            try:
                # 2. grounding（仅交互类动作需要；同一轮重试内复用成功过的 grounding）
                gr: GroundingResult | None = None
                if step.action_type in NEEDS_GROUNDING:
                    if cached_gr is not None:
                        gr = cached_gr
                    else:
                        ax_text = await self.browser.get_page_state()
                        gr = await self.grounding.ground(step.target_ref, ax_text)
                        self._emit(
                            "grounding",
                            step.index,
                            payload={
                                "found": gr.found,
                                "ref": gr.ref,
                                "role": gr.locator.role if gr.locator else "",
                                "name": gr.locator.name if gr.locator else "",
                                "rationale": gr.rationale,
                            },
                        )
                        if gr.found and gr.locator is not None:
                            cached_gr = gr
                    if not gr.found:
                        raise GroundingError(f"未找到目标: {step.target_ref}")

                # 3. 执行动作（规则派发，不调 LLM）
                await self.browser.perform_action(step.action_type, gr, step.value)

                # 4. 等待页面稳定
                await self.browser.wait_stable()

                # 5. verify
                ax_after = await self.browser.get_page_state()
                verdict = await self.verifier.verify(step.done_criteria, ax_after)
                self._emit(
                    "verify",
                    step.index,
                    payload={"pass": verdict.passed, "reason": verdict.reason},
                )

                if verdict.passed:
                    success = True
                    record.actual_result = verdict.reason
                    break
                else:
                    last_error = f"校验未通过: {verdict.reason}"
                    self._emit(
                        "warn",
                        step.index,
                        payload={"原因": f"attempt {attempt} 校验失败"},
                    )
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                self._emit(
                    "warn",
                    step.index,
                    payload={"原因": f"attempt {attempt} 异常 {last_error}"},
                )

        elapsed_ms = int((time.time() - start_time) * 1000)

        if success:
            record.status = "成功"
            record.operation = f"{step.action_type} {step.target_ref}".strip()
            self.passed += 1
            self.records.append(record)
            self._emit(
                "step_done",
                step.index,
                payload={"status": "成功", "耗时ms": elapsed_ms},
            )
        else:
            record.status = "失败"
            record.error = last_error
            self.failed += 1
            self._collect_optimize_signal(step, last_error)
            screenshot_path = await self.browser.screenshot()
            self._emit(
                "fail",
                step.index,
                payload={"error": last_error, "screenshot": screenshot_path},
            )
            self.records.append(record)
            self.aborted = True
            self.abort_step = step.index
            raise StepAbortError(last_error)

    def _collect_optimize_signal(self, step: Step, error: str):
        """收集优化信号。"""
        issue_type = "定位不稳定"
        if "校验未通过" in error:
            issue_type = "完成标准模糊"
        elif "GroundingError" in error:
            issue_type = "定位不稳定"
        elif "超时" in error or "Timeout" in error:
            issue_type = "等待不明确"

        self.optimize_signals.append(
            OptimizationSignal(
                step_index=step.index,
                issue_type=issue_type,
                description=error,
                suggestion="检查步骤描述与页面 AX 结构是否一致",
                rewritten_step=step.raw_text,
            )
        )


async def run_case(
    case_file: str,
    *,
    headed: bool = False,
    trace: bool = False,
    on_event: Callable[[Event], None] | None = None,
) -> RunResult:
    """程序级入口：解析用例文件并执行。"""
    raw_text = Path(case_file).read_text(encoding="utf-8")
    case = await parse_case(raw_text)

    trace_dir = None
    if trace:
        trace_dir = Path.cwd() / f"trace_{time.strftime('%Y%m%d_%H%M%S')}"
        trace_dir.mkdir(exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headed)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=str(trace_dir) if trace_dir else None,
        )
        if trace:
            await context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = await context.new_page()

        agent_browser = Browser(page, trace_dir=str(trace_dir) if trace_dir else None)
        agent = Agent(case=case, browser=agent_browser, on_event=on_event)

        try:
            result = await agent.run()
        finally:
            if trace:
                trace_path = (trace_dir or Path.cwd()) / "trace.zip"
                await context.tracing.stop(path=str(trace_path))
            await context.close()
            await browser.close()

        return result
