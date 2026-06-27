"""页面状态校验器。"""

from __future__ import annotations

import json

from agent.core.llm import call_llm_with_prompt
from agent.core.models import Verdict


class Verifier:
    """完成标准 + AX 状态 → pass/fail。"""

    async def verify(self, done_criteria: str, ax_state: str) -> Verdict:
        """判定完成标准在当前页面状态下是否满足。"""
        user_content = json.dumps(
            {"done_criteria": done_criteria, "ax_state": ax_state},
            ensure_ascii=False,
        )

        for attempt in range(3):
            try:
                response = await call_llm_with_prompt("verify", user_content, temperature=0.1)
                cleaned = self._clean_json_response(response)
                data = json.loads(cleaned)
                passed = bool(data.get("pass", False))
                reason = str(data.get("reason", "")).strip()
                return Verdict(passed=passed, reason=reason or ("通过" if passed else "未通过"))
            except Exception:
                if attempt == 2:
                    return Verdict(
                        passed=False,
                        reason="verify 调用异常，需人工复核",
                    )
                continue

        return Verdict(passed=False, reason="verify 调用异常，需人工复核")

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
