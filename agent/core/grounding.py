"""自然语言指代 → AX 语义定位器。"""

from __future__ import annotations

import json

from agent.core.llm import call_llm_with_prompt
from agent.core.models import AxLocator, GroundingResult


class GroundingError(Exception):
    """元素定位失败异常。"""

    pass


class Grounding:
    """ grounding 模块。为 cache/hybrid 模式留接口。"""

    async def ground(self, target_ref: str, ax_text: str) -> GroundingResult:
        """指代 + AX 文本 → GroundingResult。内部调 LLM(grounding)。"""
        user_content = json.dumps({"target_ref": target_ref, "ax_text": ax_text}, ensure_ascii=False)

        last_error = ""
        for attempt in range(3):
            try:
                response = await call_llm_with_prompt("grounding", user_content, temperature=0.1)
                cleaned = self._clean_json_response(response)
                data = json.loads(cleaned)

                found = bool(data.get("found", False))
                ref = int(data.get("ref", 0))
                role = str(data.get("role", "")).strip()
                name = str(data.get("name", "")).strip()
                rationale = str(data.get("rationale", "")).strip()

                if not found:
                    return GroundingResult(found=False, ref=0, locator=None, rationale=rationale or "未找到匹配节点")

                if not role or ref <= 0:
                    raise GroundingError(f"无效 grounding 结果: role={role}, ref={ref}")
                # 某些元素（如未命名 checkbox）name 可能为空，允许

                return GroundingResult(
                    found=True,
                    ref=ref,
                    locator=AxLocator(role=role, name=name),
                    rationale=rationale,
                )
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                continue

        raise GroundingError(f"grounding 重试耗尽: {last_error}")

    def _clean_json_response(self, response: str) -> str:
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
