"""全链路数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Config:
    """本地配置。"""

    api_key: str
    model: str


@dataclass
class Step:
    """用例一步，parse_step 产出。"""

    index: int                # 1-based 步号
    raw_text: str             # 原始自然语言步骤文本
    action_type: str          # 枚举见 prompts/parse_step.md
    target_ref: str           # 自然语言指代，给 grounding
    value: str | None         # fill 的输入值 / keypress 的键；其余 None
    expected: str             # 预期结果（诊断用）
    done_criteria: str        # 完成标准，给 verify


@dataclass
class Case:
    """测试用例。"""

    name: str                 # 用例名称
    purpose: str              # 测试目的
    start_url: str            # 起始 URL
    steps: list[Step]


@dataclass
class AxLocator:
    """AX 语义定位器。"""

    role: str                 # AX 角色：button / textbox / checkbox / link / menuitem / ...
    name: str                 # AX 名称（可见文案 / placeholder / label）


@dataclass
class GroundingResult:
    """ grounding 结果。"""

    found: bool               # 是否找到目标
    ref: int                  # 1-based，该 role+name 在 AX 树深度优先遍历中的第几个
    locator: AxLocator | None # found=True 时非空
    rationale: str            # LLM 选择依据


@dataclass
class Verdict:
    """校验结果。"""

    passed: bool
    reason: str


@dataclass
class StepRecord:
    """单步执行记录，写报告用。"""

    step: str                 # 步骤序号及描述
    operation: str            # 解析后的微观操作
    actual_result: str        # DOM/AX 变化或页面状态
    status: str               # "成功" / "失败"
    error: str = "无"         # 无异常写"无"


@dataclass
class OptimizationSignal:
    """用例优化信号。"""

    step_index: int
    issue_type: str           # 定位不稳定/等待不明确/完成标准模糊/冗余步骤/结构不合理
    description: str
    suggestion: str
    rewritten_step: str = ""


@dataclass
class RunResult:
    """用例执行结果。"""

    case_name: str
    total: int
    passed: int
    failed: int
    finished: bool            # True=全部跑完；False=中途熔断/中断
    abort_step: int | None    # 熔断/中断步号，None=正常完成
    report_path: str
    exceptions: list[str] = field(default_factory=list)


@dataclass
class Event:
    """事件流契约。"""

    type: str                 # parse_done / step_start / grounding / verify / step_done / warn / fail / finish
    step_index: int           # 1-based；parse_done/finish 时为 0
    total: int                # 总步数
    payload: dict = field(default_factory=dict)


EventCallback = Callable[[Event], None]
