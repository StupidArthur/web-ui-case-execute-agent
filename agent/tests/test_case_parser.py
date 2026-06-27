"""用例解析器单元测试。"""

import json
import pytest

from agent.core import case_parser as case_parser_module
from agent.core.case_parser import parse_case


@pytest.fixture
def sample_case_text():
    return """测试用例名称：完成用户登录
测试目的：验证用户能登录
起始 URL：https://example.com/login

测试步骤：

步骤1: 完成用户登录
- 在「请输入用户名」输入框中输入手机号，确认用户名输入框 value 变为"15700078644"
- 勾选「同意协议」复选框，确认复选框 checked 状态从 false 变为 true
- 点击可见文本为「立即登录」的按钮，确认页面跳转至工作台
"""


@pytest.mark.asyncio
async def test_parse_case_splits_sub_steps(monkeypatch, sample_case_text):
    async def fake_call(prompt_name, user_content, **kwargs):
        if prompt_name == "parse_step":
            return json.dumps(
                {
                    "action_type": "fill",
                    "target_ref": "请输入用户名",
                    "value": "15700078644",
                    "expected": "显示手机号",
                    "done_criteria": "value 为 15700078644",
                },
                ensure_ascii=False,
            )
        return "{}"

    monkeypatch.setattr(case_parser_module, "call_llm_with_prompt", fake_call)

    case = await parse_case(sample_case_text)
    assert case.name == "完成用户登录"
    assert case.purpose == "验证用户能登录"
    assert case.start_url == "https://example.com/login"
    assert len(case.steps) == 3
    assert case.steps[0].index == 1
    assert case.steps[0].action_type == "fill"
    assert case.steps[0].value == "15700078644"
    assert case.steps[2].index == 3


@pytest.mark.asyncio
async def test_parse_case_fallback_on_invalid_json(monkeypatch, sample_case_text):
    async def fake_call(prompt_name, user_content, **kwargs):
        return "这不是 JSON"

    monkeypatch.setattr(case_parser_module, "call_llm_with_prompt", fake_call)

    case = await parse_case(sample_case_text)
    assert len(case.steps) == 3
    assert case.steps[0].action_type == "wait"
    assert case.steps[0].done_criteria == case.steps[0].raw_text


@pytest.mark.asyncio
async def test_parse_case_single_block_no_sub_steps(monkeypatch):
    text = """测试用例名称：示例
测试目的：示例
起始 URL：https://example.com

测试步骤：

步骤1: 点击登录按钮
"""

    async def fake_call(prompt_name, user_content, **kwargs):
        return json.dumps(
            {
                "action_type": "click",
                "target_ref": "登录按钮",
                "value": None,
                "expected": "跳转",
                "done_criteria": "页面跳转",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(case_parser_module, "call_llm_with_prompt", fake_call)

    case = await parse_case(text)
    assert len(case.steps) == 1
    assert case.steps[0].action_type == "click"
