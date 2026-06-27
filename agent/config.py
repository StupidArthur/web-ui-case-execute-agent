"""读取本地配置。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from agent.core.models import Config


DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config.local.json",
)


def load_config(path: str | None = None) -> Config:
    """读取 config.local.json，返回 Config 对象。

    Args:
        path: 配置文件路径，默认项目根目录 config.local.json。

    Raises:
        FileNotFoundError: 配置文件不存在时给出明确错误。
        ValueError: 配置缺少必要字段。
    """
    path = path or DEFAULT_CONFIG_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"配置文件不存在: {path}\n"
            '请创建 config.local.json，内容示例: {"api_key": "sk-xxx", "model": "MiniMax-M3"}'
        )

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    api_key = data.get("api_key")
    model = data.get("model")
    if not api_key or not model:
        raise ValueError("config.local.json 必须包含 api_key 和 model 字段")

    return Config(api_key=api_key, model=model)
