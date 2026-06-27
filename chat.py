"""
统一 LLM 调用模块（Python 实现）。

本模块封装多家 LLM 供应商的调用差异，对外提供统一的输入/输出接口。
调用方只需关注：模型名、消息内容、API Key，其余细节（端点、thinking 参数、
reasoning_split、max_tokens 等）均由模块内部根据模型注册表自动处理。

支持的供应商及模型：
  - MiniMax: M2.7-highspeed[thinking], M3, M3[thinking]
  - Xiaomi MiMo: mimo-v2.5-pro, mimo-v2.5-pro[thinking]
  - DeepSeek: deepseek-v4-pro, deepseek-v4-pro[thinking]

对外接口：
  - list_models() → list[str]
      返回所有可选模型名称，供前端 select 下拉框使用。

  - chat(model, messages, api_key, ...) → ChatResult
      统一调用入口，自动处理各供应商的参数差异。

设计原则：
  1. API Key 不存储在模块内，由调用方传入（从配置文件/环境变量/数据库获取）。
  2. 模型注册表只记录技术参数（端点、thinking 控制、max_tokens），不含密钥。
  3. 输出结构 ChatResult 对所有模型一致，调用方无需关心底层差异。
  4. 新增供应商只需扩展 _MODELS 注册表，无需修改调用逻辑。
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

import openai

log = logging.getLogger(__name__)

# =====================================================================
# 模型注册表
# =====================================================================
# 每个模型条目包含以下字段：
#   - api:            实际调用的 API 模型名（可能与对外展示名不同）
#   - url:            API 端点 base_url
#   - thinking:       thinking 模式控制
#                     - None: 不发送 thinking 字段（M2.x 关不掉，保持默认）
#                     - "disabled": 关闭思考（跳过推理，直接回答）
#                     - "adaptive": 开启自适应思考
#   - reasoning_split: 是否需要在请求中显式发送 reasoning_split=true
#                     - True:  MiniMax 需要，否则 thinking 内容混在 content 中
#                     - False: MiMo/DeepSeek 自动返回 reasoning_content，无需发送
#   - max_tokens:     模型支持的最大输出 token 数（经实测确认的实际上限）
#
# 注意：注册表不含 API Key，调用时由调用方通过 api_key 参数传入。
# =====================================================================

_MODELS: dict[str, dict] = {
    # ---- MiniMax 系列 ----
    # MiniMax M2.x 的 thinking 无法关闭，因此只有 [thinking] 一种形态。
    # MiniMax 需要显式发送 reasoning_split=true 才能将 thinking 分离到独立字段。
    "MiniMax-M2.7-highspeed[thinking]": {
        "api": "MiniMax-M2.7-highspeed",
        "url": "https://api.minimax.chat/v1",
        "thinking": None,        # M2.x thinking 关不掉，不发送 thinking 字段
        "reasoning_split": True, # MiniMax 需要显式开启 reasoning_split
        "max_tokens": 196608,    # 实测上限：196608（API 报错确认）
    },
    "MiniMax-M3": {
        "api": "MiniMax-M3",
        "url": "https://api.minimax.chat/v1",
        "thinking": "disabled",  # 关闭思考，跳过推理直接回答
        "reasoning_split": True,
        "max_tokens": 524288,    # M3 实测上限
    },
    "MiniMax-M3[thinking]": {
        "api": "MiniMax-M3",
        "url": "https://api.minimax.chat/v1",
        "thinking": "adaptive",  # 开启自适应思考
        "reasoning_split": True,
        "max_tokens": 524288,
    },

    # ---- Xiaomi MiMo 系列 ----
    # MiMo 的 reasoning_content 自动返回，无需发送 reasoning_split。
    # thinking=disabled 时 reasoning_tokens=0，不产生推理开销。
    "mimo-v2.5-pro": {
        "api": "mimo-v2.5-pro",
        "url": "https://token-plan-cn.xiaomimimo.com/v1",
        "thinking": "disabled",
        "reasoning_split": False,  # MiMo 自动返回 reasoning_content
        "max_tokens": 131072,      # 实测上限：131072（131073 报错）
    },
    "mimo-v2.5-pro[thinking]": {
        "api": "mimo-v2.5-pro",
        "url": "https://token-plan-cn.xiaomimimo.com/v1",
        "thinking": "adaptive",
        "reasoning_split": False,
        "max_tokens": 131072,
    },

    # ---- DeepSeek 系列 ----
    # DeepSeek 的 reasoning_content 自动返回，无需发送 reasoning_split。
    # thinking 默认开启，可通过 thinking=disabled 关闭。
    "deepseek-v4-pro": {
        "api": "deepseek-v4-pro",
        "url": "https://api.deepseek.com",
        "thinking": "disabled",
        "reasoning_split": False,  # DeepSeek 自动返回 reasoning_content
        "max_tokens": 393216,      # 实测上限：393216（API 报错 valid range [1, 393216]）
    },
    "deepseek-v4-pro[thinking]": {
        "api": "deepseek-v4-pro",
        "url": "https://api.deepseek.com",
        "thinking": "adaptive",
        "reasoning_split": False,
        "max_tokens": 393216,
    },
}


# =====================================================================
# 结果结构
# =====================================================================

@dataclass
class ChatResult:
    """统一 LLM 调用结果，所有模型返回相同结构。

    Attributes:
        content:            模型生成的最终回答（已去除 thinking 标签等杂质）。
        reasoning_content:  模型的思考/推理过程。
                            - thinking 开启时：包含推理链文本
                            - thinking 关闭时：为空字符串
        finish_reason:      生成终止原因，通常为 "stop"（正常结束）或 "length"（达到 max_tokens 截断）。
        prompt_tokens:      输入 token 数（含 system/user 消息）。
        completion_tokens:  输出 token 数（含 reasoning + content）。
    """
    content: str
    reasoning_content: str = ""
    finish_reason: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


# =====================================================================
# 对外接口
# =====================================================================

def list_models() -> list[str]:
    """返回所有可选模型名称列表。

    返回值可直接用于前端 select 下拉框的选项列表。
    模型命名规则：
      - 不带 [thinking] 后缀：关闭思考模式（M2.x 除外，其 thinking 无法关闭）
      - 带 [thinking] 后缀：开启思考模式

    Returns:
        模型名称列表，例如 ["MiniMax-M3", "mimo-v2.5-pro[thinking]", ...]
    """
    return list(_MODELS.keys())


async def chat(
    model: str,
    messages: list[dict[str, str]],
    api_key: str,
    *,
    max_retries: int = 3,
    temperature: float = 0.2,
) -> ChatResult:
    """统一 LLM 调用入口。

    内部自动处理以下差异：
      - 各供应商的 API 端点和模型名
      - thinking 参数的发送与否及具体值
      - reasoning_split 的发送与否
      - max_tokens 的模型实际上限
      - 指数退避重试

    Args:
        model:      模型名称，必须是 list_models() 返回的值之一。
                    例如 "MiniMax-M3", "mimo-v2.5-pro[thinking]", "deepseek-v4-pro"。
        messages:   消息数组，遵循 OpenAI 格式。
                    [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
        api_key:    API Key，由调用方从配置/环境变量/数据库等途径获取。
                    不同供应商的 key 不同，调用方需自行管理映射关系。
        max_retries: 最大重试次数（默认 3），失败时按指数退避重试。
        temperature: 生成温度（默认 0.2），控制输出随机性，范围 [0, 2]。

    Returns:
        ChatResult 对象，包含 content、reasoning_content、token 用量等。

    Raises:
        ValueError:  模型名不在注册表中。
        RuntimeError: 所有重试均失败。

    示例：
        >>> result = await chat("MiniMax-M3", [
        ...     {"role": "system", "content": "你是助手"},
        ...     {"role": "user", "content": "你好"},
        ... ], api_key="sk-xxx")
        >>> print(result.content)
    """
    # 校验模型名
    if model not in _MODELS:
        raise ValueError(f"未知模型: {model}，可选: {list_models()}")

    cfg = _MODELS[model]

    # 创建 OpenAI 客户端（兼容所有供应商的 OpenAI 格式接口）
    client = openai.AsyncOpenAI(api_key=api_key, base_url=cfg["url"])

    # 构建供应商特定的 extra_body 参数
    extra_body: dict = {}
    # reasoning_split: 仅 MiniMax 需要显式发送，MiMo/DeepSeek 自动返回
    if cfg["reasoning_split"]:
        extra_body["reasoning_split"] = True
    # thinking: 仅在需要显式控制时发送（None 表示不发送，保持模型默认行为）
    if cfg["thinking"] is not None:
        extra_body["thinking"] = {"type": cfg["thinking"]}

    # 带指数退避的重试循环
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            completion = await client.chat.completions.create(
                model=cfg["api"],
                messages=messages,
                temperature=temperature,
                max_tokens=cfg["max_tokens"],
                extra_body=extra_body or None,
            )

            # 提取响应内容
            raw = completion.model_dump()
            msg = raw["choices"][0]["message"]
            content = (msg.get("content") or "").strip()
            reasoning = (msg.get("reasoning_content") or "").strip()

            # 两者均为空则报错
            if not content and not reasoning:
                raise ValueError("AI 返回空结果")

            # 容错：content 为空时尝试从 reasoning 的</think>标签后提取
            # 这是防御性逻辑，正常情况下 reasoning_split 已分离两者
            if not content:
                content = _extract_from_reasoning(reasoning)
                if not content:
                    raise ValueError("AI 返回空 content，reasoning 无法提取")

            # 构建统一返回结果
            usage = raw.get("usage") or {}
            return ChatResult(
                content=content,
                reasoning_content=reasoning,
                finish_reason=raw["choices"][0].get("finish_reason", ""),
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
            )
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                delay = 2 ** (attempt - 1)  # 指数退避：1s, 2s, 4s, ...
                log.warning("调用失败，第 %s 次重试，%ss 后重试...", attempt, delay)
                await asyncio.sleep(delay)

    raise RuntimeError(f"调用失败，已重试 {max_retries} 次: {last_error}")


# =====================================================================
# 内部工具函数
# =====================================================================

def _extract_from_reasoning(reasoning: str) -> str:
    """从 reasoning_content 中提取实际回答。

    当 content 为空但 reasoning 非空时（异常情况），尝试从 reasoning 中恢复。
    查找</think>结束标签，返回其后的内容作为回答。

    这是对标 Go 版 extractContentFromReasoning 的防御性逻辑，
    正常流程中 reasoning_split 已将 thinking 和 content 分离，不会走到这里。

    Args:
        reasoning: 原始 reasoning_content 文本。

    Returns:
        提取到的回答文本。如果未找到</think>标签，则返回整个 reasoning 文本。
    """
    m = re.search(r"</think>", reasoning)
    if m:
        after = reasoning[m.end():].strip()
        if after:
            return after
    # 未找到结束标签，返回整个 reasoning（最后的手段）
    return reasoning


# =====================================================================
# 命令行测试入口
# =====================================================================

if __name__ == "__main__":
    async def main():
        """快速验证模块可用性。"""
        print("可用模型:", list_models())
        # 测试用 key，实际由应用层传入
        key = "sk-cp-aXV4X8TlWZeR3E1hpIaPtjEFnafrpbEi_IMlm6NhSY_0-CQHOV5WupxDkg4LV2JXfB3sO_AoGodPCkQ6irIC7PuIoxC29MVKqG70AYz_hQ1VIjNDgSpCvOo"
        r = await chat("MiniMax-M3", [{"role": "user", "content": "1+1"}], key)
        print(f"  content: {r.content}")
    asyncio.run(main())
