"""统一 LLM 调用封装。

通过 sys.path 将项目根目录加入导入路径，复用 chat.py。
"""

from __future__ import annotations

import os
import sys
from typing import Any

# 将项目根目录加入 sys.path，以便导入 chat.py
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import chat  # noqa: E402

from agent.config import load_config


async def call_llm(
    system_prompt: str,
    user_content: str,
    *,
    temperature: float = 0.2,
    max_retries: int = 3,
) -> str:
    """统一 LLM 调用入口。

    Args:
        system_prompt: system 消息内容。
        user_content: user 消息内容。
        temperature: 生成温度。
        max_retries: 最大重试次数。

    Returns:
        LLM 返回的 content 字符串。
    """
    cfg = load_config()
    result = await chat.chat(
        model=cfg.model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        api_key=cfg.api_key,
        temperature=temperature,
        max_retries=max_retries,
    )
    return result.content


def load_prompt(name: str) -> str:
    """加载 prompts/ 目录下的 system prompt 文件。"""
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "prompts",
        f"{name}.md",
    )
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


async def call_llm_with_prompt(prompt_name: str, user_content: str, **kwargs: Any) -> str:
    """加载指定 prompt 并调用 LLM。"""
    system_prompt = load_prompt(prompt_name)
    return await call_llm(system_prompt, user_content, **kwargs)
