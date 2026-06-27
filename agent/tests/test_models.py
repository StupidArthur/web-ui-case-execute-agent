"""数据模型单元测试。"""

import pytest

from agent.core.models import (
    AxLocator,
    Config,
    Event,
    GroundingResult,
    OptimizationSignal,
    RunResult,
    Step,
    StepRecord,
    Verdict,
)


def test_config_fields():
    cfg = Config(api_key="sk-xxx", model="MiniMax-M3")
    assert cfg.api_key == "sk-xxx"
    assert cfg.model == "MiniMax-M3"


def test_step_fields():
    step = Step(
        index=1,
        raw_text="点击登录按钮",
        action_type="click",
        target_ref="登录按钮",
        value=None,
        expected="跳转",
        done_criteria="页面跳转",
    )
    assert step.index == 1
    assert step.action_type == "click"
    assert step.value is None


def test_grounding_result():
    loc = AxLocator(role="button", name="立即登录")
    gr = GroundingResult(found=True, ref=1, locator=loc, rationale="匹配")
    assert gr.locator.role == "button"
    assert gr.locator.name == "立即登录"


def test_verdict():
    v = Verdict(passed=True, reason="可见")
    assert v.passed is True


def test_step_record_defaults():
    r = StepRecord(step="步骤1", operation="click", actual_result="通过", status="成功")
    assert r.error == "无"


def test_run_result_defaults():
    result = RunResult(
        case_name="登录",
        total=3,
        passed=2,
        failed=1,
        finished=False,
        abort_step=2,
        report_path="report.json",
    )
    assert result.exceptions == []


def test_event_payload_default():
    e = Event(type="step_start", step_index=1, total=5)
    assert e.payload == {}


def test_optimization_signal():
    sig = OptimizationSignal(
        step_index=1,
        issue_type="定位不稳定",
        description="未找到",
        suggestion="增加 placeholder",
    )
    assert sig.rewritten_step == ""
