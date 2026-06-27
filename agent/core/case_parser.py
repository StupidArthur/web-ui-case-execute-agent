"""测试用例解析器。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from agent.core.llm import call_llm_with_prompt
from agent.core.models import Case, Step


# 需要 grounding 的动作类型
NEEDS_GROUNDING = {"click", "fill", "check", "upload", "download", "keypress"}


@dataclass
class RawStepBlock:
    """原始步骤块，来自 agents.txt。"""

    group_index: int          # 步骤N 中的 N
    group_title: str          # 步骤N 后面的标题
    sub_steps: list[str]      # - 开头的子步骤文本列表


def _extract_field(text: str, field_name: str) -> str:
    """从文本中提取「字段名：值」。"""
    pattern = rf"{re.escape(field_name)}\s*[:：]\s*(.*)"
    match = re.search(pattern, text)
    if not match:
        return ""
    return match.group(1).strip()


def _split_raw_steps(text: str) -> list[RawStepBlock]:
    """将 agents.txt 文本切分为原始步骤块。

    支持两种形式：
    1. 步骤N: 标题
       - 子步骤1
       - 子步骤2
    2. 步骤N: 动作描述（无子步骤）
    """
    lines = text.splitlines()
    blocks: list[RawStepBlock] = []
    current: RawStepBlock | None = None

    step_header_pattern = re.compile(r"^步骤\s*(\d+)\s*[:：]\s*(.*)$")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        header_match = step_header_pattern.match(stripped)
        if header_match:
            if current is not None:
                blocks.append(current)
            group_index = int(header_match.group(1))
            group_title = header_match.group(2).strip()
            current = RawStepBlock(group_index=group_index, group_title=group_title, sub_steps=[])
            continue

        if current is not None and stripped.startswith("-"):
            sub = stripped.lstrip("-").strip()
            if sub:
                current.sub_steps.append(sub)
            continue

    if current is not None:
        blocks.append(current)

    return blocks


def _build_step_texts(blocks: list[RawStepBlock]) -> list[tuple[int, str, str]]:
    """把原始步骤块展开为 (global_index, display_step, raw_text) 列表。

    每个子步骤作为独立 Step；若步骤块无子步骤，则块标题本身作为一步。
    """
    result: list[tuple[int, str, str]] = []
    global_index = 0
    for block in blocks:
        if block.sub_steps:
            for sub in block.sub_steps:
                global_index += 1
                display = f"步骤{block.group_index}: {block.group_title}"
                result.append((global_index, display, sub))
        else:
            global_index += 1
            display = f"步骤{block.group_index}: {block.group_title}"
            result.append((global_index, display, block.group_title))
    return result


async def _parse_single_step(raw_text: str) -> dict:
    """调用 parse_step LLM，返回解析后的 JSON dict。

    JSON 解析失败时重试 2 次；仍失败返回兜底 dict。
    """
    user_content = f"输入：{raw_text}\n输出："
    for attempt in range(3):
        try:
            response = await call_llm_with_prompt("parse_step", user_content, temperature=0.1)
            cleaned = _clean_json_response(response)
            return json.loads(cleaned)
        except Exception:
            if attempt == 2:
                return {
                    "action_type": "wait",
                    "target_ref": raw_text,
                    "value": None,
                    "expected": raw_text,
                    "done_criteria": raw_text,
                }
    return {}  # unreachable


def _clean_json_response(response: str) -> str:
    """去除可能的 markdown 围栏与前后空白。"""
    response = response.strip()
    if response.startswith("```"):
        response = response[3:]
        if response.startswith("json"):
            response = response[3:]
        response = response.strip()
        if response.endswith("```"):
            response = response[:-3].strip()
    return response


async def parse_case(text: str) -> Case:
    """解析 agents.txt 文本为 Case 对象。"""
    name = _extract_field(text, "测试用例名称")
    purpose = _extract_field(text, "测试目的")
    start_url = _extract_field(text, "起始 URL")

    blocks = _split_raw_steps(text)
    step_texts = _build_step_texts(blocks)

    steps: list[Step] = []
    for global_index, display_step, raw_text in step_texts:
        parsed = await _parse_single_step(raw_text)
        action_type = parsed.get("action_type", "wait")
        if action_type not in {
            "click", "fill", "check", "scroll", "wait", "upload", "download", "keypress"
        }:
            action_type = "wait"
        steps.append(
            Step(
                index=global_index,
                raw_text=raw_text,
                action_type=action_type,
                target_ref=parsed.get("target_ref", ""),
                value=parsed.get("value"),
                expected=parsed.get("expected", ""),
                done_criteria=parsed.get("done_criteria", ""),
            )
        )

    return Case(name=name, purpose=purpose, start_url=start_url, steps=steps)
