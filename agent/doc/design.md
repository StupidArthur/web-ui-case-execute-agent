# 设计文档：Web UI 自动化测试执行 Agent

> 阶段②产物。承接需求理解，输出方案设计。文档与代码同步，禁止滞后。
> 本文档目标详细度：**可由另一个 AI 模型独立据此开发，架构师事后审核**。所有不可自由发挥的契约（数据 schema、控制流、接口签名、验收标准）均钉死到此。
>
> 关联：
> - `chat.py`（项目根，统一 LLM 调用层，复用）
> - `web-ui-case-executor/SKILL.md`（行为规格来源：五阶段/五要素/等待分级/熔断/6项能力/JSON 报告格式）
> - `ai_ui_recorder/`（上游录制+翻译工具，表示层与执行器架构参考）
>   - `doc/case_execution_unified_spec.md`（Hybrid Runner + LocatorAsset 架构参考）
>   - `recorder/src/case_translate/prompts/md/*.md`（翻译端 prompt，理解 agent.txt 生成口径）

---

## 0. 表示层契约（全链路货币）

本项目是上游 `ai_ui_recorder`（录制+翻译）的下游执行端。三者构成闭环：

```
录制端(CDP/AX) → 翻译端(AX→自然语言) → 执行端(自然语言→AX→操作) → [将来] cache 回写
```

**核心契约：全链路的页面表示货币是 AX（accessibility）树文本，不是 DOM/CSS/XPath。定位货币是 `role+name`。**

依据（来自 `ai_ui_recorder` 源码实证）：

- 录制端用 Playwright accessibility 抓 AX 树，裁剪为 YAML 风格文本（`- role "name" [attrs]`）。`_stripDOMContextFields` 主动删除 domContext/classes/ariaLabel/role 等 DOM 字段——AX 是正典，DOM 是被剥离的噪声。
- 翻译端 prompt 明确"不得仅凭 xpath/class 推测业务名称"——定位依据是 AX 语义（role + 可见文案 + placeholder）。
- `agent.txt` 中的定位描述是纯 AX 语义自然语言（"点击可见文本为『立即登录』的按钮""placeholder 为『请输入用户名』"）。action 里虽记 xpath，仅为证据副产物，从不作为定位依据。

> 这正是"CDP 走的不是 xpath 那套"的准确含义：本链路用 CDP 的 Accessibility domain（AX 树），而非 DOM domain 的 xpath。`CDP → language → CDP` 实为 `AX → 自然语言 → AX`。

**对本执行器的硬约束：**

1. 页面状态序列化统一使用 Playwright 内置 `page.aria_snapshot()`（返回 AX 树文本）。**不**自造序列化、**不**移植录制端 `snapshotToText`、**不**用 Python 版不存在的 `page.accessibility.snapshot()`。理由见 §3.5 决策。
2. **定位货币是 `role+name`**：grounding 输出 AX 语义定位器（role + name），用 Playwright `get_by_role(role, name=...)` 落地操作。禁止生成 CSS selector / XPath 作为定位依据。只要 role+name 在录制端与执行端语义一致（二者皆然），闭环即成立——AX 文本的格式细节（value 写法等）不影响定位货币。
3. xpath/CSS 仅可作诊断证据记录，不得参与定位决策。
4. `role+name` 是将来 locator cache 的存储单元（不存 AX 文本片段），故 AX 文本格式不一致**不影响**将来录制回放。

**与 `ai_ui_recorder` 的关系：** 当下是统一思路指引下的独立工具，表示层对齐但不引依赖、不对齐其目录结构。未来全链路效果验证后合并；AI 时代重构成本低，不为合并做提前抽象。

---

## 0.5 背景与动机

此前用 Claude Code 承载 `web-ui-case-executor` skill 运行测试用例，存在三个问题：

1. skill 只在开头强调一次，长对话执行中上下文衰减，逐渐遗忘 skill 内容。
2. Claude Code 本身 coding 导向，自带系统提示目标与本任务冲突。
3. 作为通用 agent 可修改面少，skill 约束是自然语言，软弱。

根因：**试图把一个状态机（五阶段、步进、重试上限、熔断条件）塞进 prompt，祈求 LLM 自觉遵守**。约束是自然语言而非代码。

本项目目标：自己实现一个 agent，把控制流从 prompt 挪到代码里，LLM 每步只负责一件窄事。

---

## 1. 技术栈

| 项 | 结论 |
|---|---|
| 语言/运行时 | Python 3.11+，async |
| 浏览器驱动 | Playwright (async API)，Chromium |
| LLM 调用 | 复用项目根 `chat.py`，模型 MiniMax-M3 |
| CLI 入口 | typer（遵循 dev-skill Python CLI 规范，核心逻辑放 `core/` 可独立 pytest） |
| 配置 | `config.local.json`（不进版本控制） |

### 1.1 依赖清单（requirements.txt）

```
playwright>=1.40
typer>=0.9
openai>=1.0        # chat.py 依赖
```

安装后需执行 `playwright install chromium` 下载浏览器。

### 1.2 config.local.json

位于项目根 `G:\cc_demos\web-ui-case-execute-agent\config.local.json`，结构：

```json
{
  "api_key": "sk-cp-xxxxx",
  "model": "MiniMax-M3"
}
```

- 加入 `.gitignore`，不得提交。
- `config.py` 读取此文件；缺失时给出明确错误。
- model 必须是 `chat.py` 的 `list_models()` 返回值之一。

### 1.3 chat.py 复用方式

`chat.py` 位于项目根，`agent/` 是其子目录。`agent` 包内通过将项目根加入 `sys.path` 导入：

```python
# agent/core/llm.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
import chat  # 根目录 chat.py

async def call_llm(system_prompt: str, user_content: str) -> str:
    cfg = load_config()
    result = await chat.chat(
        model=cfg.model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        api_key=cfg.api_key,
    )
    return result.content
```

`chat.chat()` 签名（来自 `chat.py`）：`async def chat(model, messages, api_key, *, max_retries=3, temperature=0.2) -> ChatResult`，返回的 `ChatResult.content` 是已剥离 thinking 的最终回答。三个 LLM 调用点统一经 `call_llm`，不直接调 `chat.chat`。

定位：本质是 **agent runner 库**（核心是状态机+grounding），CLI 只是个壳。按 Python CLI 规范分层：`main.py` 只管参数，业务全在 `core/`。

---

## 2. 模块拆分

```
G:\cc_demos\web-ui-case-execute-agent\
├── chat.py                      # 已有，复用（统一 LLM 调用层）
├── config.local.json            # 新增，{api_key, model}，gitignore
├── requirements.txt             # 新增
├── agent/                       # 新增，agent 主体
│   ├── __init__.py              # 导出 run_case
│   ├── main.py                  # typer CLI 入口: run <case_file> [--headed] [--trace]
│   ├── config.py                # 读 config.local.json → Config dataclass
│   ├── core/
│   │   ├── __init__.py
│   │   ├── llm.py               # call_llm() 统一封装 chat.py
│   │   ├── models.py            # 全部 dataclass（见 §2.1）
│   │   ├── case_parser.py       # ① 解析: 原始用例文本 → Case(含[Step])  (LLM: parse_step)
│   │   ├── page_state.py        # [可删/仅测试用] aria_snapshot 路线下生产路径不使用，保留裁剪工具仅供测试
│   │   ├── grounding.py         # 指代+AX文本 → GroundingResult  (LLM: grounding)
│   │   ├── browser.py           # Playwright 工具面（见 §3.4）
│   │   ├── verifier.py          # 完成标准+AX状态 → pass/fail  (LLM: verify)
│   │   ├── agent.py             # ② 状态机: run_case() + execute_step()
│   │   ├── reporter.py          # ⑤ JSON 报告生成与落盘
│   │   └── events.py            # Event dataclass + emit 辅助
│   ├── prompts/                 # 各 LLM 调用点 system prompt（见 §6）
│   │   ├── parse_step.md
│   │   ├── grounding.md
│   │   └── verify.md
│   └── tests/                   # core/ 独立 pytest（无浏览器依赖的纯逻辑）
│       ├── test_case_parser.py
│       ├── test_page_state.py
│       └── test_models.py
```

职责单一性：`browser.py` 只管"对浏览器做动作"（含 `get_page_state` 直返 `aria_snapshot()` 文本），`grounding.py` 只管"指代→元素"，`verifier.py` 只管"判定完成"，`agent.py` 只管"编排状态机"。无跨模块调私有函数。

### 2.1 数据模型（models.py）

```python
from dataclass import dataclass

@dataclass
class Config:
    api_key: str
    model: str

@dataclass
class Step:
    """用例一步，parse_step 产出。"""
    index: int                # 1-based 步号
    raw_text: str             # 原始自然语言步骤文本
    action_type: str          # 枚举见 §3.2
    target_ref: str           # 自然语言指代，给 grounding（如『立即登录』按钮）
    value: str | None         # fill 的输入值 / keypress 的键；其余 None
    expected: str             # 预期结果（诊断用）
    done_criteria: str        # 完成标准，给 verify

@dataclass
class Case:
    name: str                 # 用例名称
    purpose: str              # 测试目的
    start_url: str            # 起始 URL
    steps: list[Step]

@dataclass
class AxLocator:
    role: str                 # AX 角色：button / textbox / checkbox / link / menuitem / ...
    name: str                 # AX 名称（可见文案 / placeholder / label）

@dataclass
class GroundingResult:
    found: bool               # 是否找到目标
    ref: int                  # 1-based，该 role+name 在 AX 树深度优先遍历中的第几个（消歧用，见 §3.5）
    locator: AxLocator | None # found=True 时非空
    rationale: str            # LLM 选择依据（人类可读）

@dataclass
class StepRecord:
    """单步执行记录，写报告用。"""
    step: str                 # 步骤序号及描述
    operation: str            # 解析后的微观操作
    actual_result: str        # DOM/AX 变化或页面状态
    status: str               # "成功" / "失败"
    error: str                # 无异常写"无"

@dataclass
class RunResult:
    case_name: str
    total: int
    passed: int
    failed: int
    finished: bool            # True=全部跑完；False=中途熔断/中断
    abort_step: int | None    # 熔断/中断步号，None=正常完成
    report_path: str
    exceptions: list[str]
```

---

## 3. 核心设计

### 3.1 状态机：红线变代码（agent.py）

把 SKILL.md 的五阶段和红线翻译成 Python 控制流，不再靠 prompt 自觉：

```
phase1 解析: case = case_parser.parse(raw_text)     # 一次性
phase2 执行: for step in case.steps:               # for 循环 = 不跳步
              execute_step(step)
              step_idx += 1                         # 步号在代码里
phase3 等待验证: 在 execute_step 内部交错执行
phase4 优化分析: 累计优化信号 ≥3 → 生成优化用例
phase5 报告: 仅当 step_idx == total 或 熔断 时输出
```

红线 → 代码映射：

- **不跳步** → `for step in case.steps`，无跳转。
- **不提前终止** → 完成判定 `step_idx == total`，不看"成功"语义文本。
- **重试上限3** → `for attempt in range(3)`，硬编码。
- **不主动刷新** → `browser.py` 不暴露 `page.reload`。
- **熔断** → 重试耗尽 → `screenshot()` + 记录堆栈 → 跳出循环 → 进 phase5。

#### execute_step 伪代码（钉死，开发者不得自由发挥控制流）

```python
async def execute_step(self, step: Step):
    self._emit("step_start", step.index, payload={"action": step.action_type, "target": step.target_ref})
    record = StepRecord(step=f"步骤{step.index}: {step.raw_text[:40]}", operation="", actual_result="", status="", error="无")

    # AI 对话界面特殊规则：每步开始前滚 chat-history 到底
    await self.browser.scroll_chat_to_bottom_if_exists()

    success = False
    last_error = ""
    timing = {"grounding_ms": 0, "wait_ms": 0, "verify_ms": 0}   # 耗时埋点，见 §3.7
    for attempt in range(1, 4):                      # 重试上限 3
        try:
            # 1. 取页面 AX 状态
            ax_text = await self.browser.get_page_state()

            # 2. grounding（仅交互类动作需要；wait/scroll 等可跳过，见 §3.2）
            if step.action_type in NEEDS_GROUNDING:
                t0 = time.time()
                gr = await self.grounding.ground(step.target_ref, ax_text)
                timing["grounding_ms"] = int((time.time()-t0)*1000)
                self._emit("grounding", step.index, payload={"found": gr.found, "ref": gr.ref, "role": gr.locator.role if gr.locator else "", "name": gr.locator.name if gr.locator else "", "rationale": gr.rationale, "耗时ms": timing["grounding_ms"]})
                if not gr.found:
                    raise GroundingError(f"未找到目标: {step.target_ref}")
            else:
                gr = None

            # 3. 执行动作（规则派发，不调 LLM）。click/fill 自带 actionability 自动等待。
            await self.browser.perform_action(step.action_type, gr, step.value)

            # 4. 等待页面稳定（短超时、目标导向，见 §3.4）
            t0 = time.time()
            await self.browser.wait_stable()
            timing["wait_ms"] = int((time.time()-t0)*1000)

            # 5. verify
            t0 = time.time()
            ax_after = await self.browser.get_page_state()
            verdict = await self.verifier.verify(step.done_criteria, ax_after)
            timing["verify_ms"] = int((time.time()-t0)*1000)
            self._emit("verify", step.index, payload={"pass": verdict.passed, "reason": verdict.reason, "耗时ms": timing["verify_ms"]})

            if verdict.passed:
                success = True
                record.actual_result = verdict.reason
                break                                            # 成功，跳出重试
            else:
                last_error = f"校验未通过: {verdict.reason}"
                self._emit("warn", step.index, payload={"原因": f"attempt {attempt} 校验失败"})
                # 继续下一次重试
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            self._emit("warn", step.index, payload={"原因": f"attempt {attempt} 异常 {last_error}"})

    # 重试结束判定
    if success:
        record.status = "成功"
        record.operation = f"{step.action_type} {step.target_ref}"
        self.passed += 1
    else:
        record.status = "失败"
        record.error = last_error
        self.failed += 1
        self._collect_optimize_signal(step, last_error)         # 优化信号收集
        # 熔断：单步重试耗尽即熔断（与 SKILL.md "重试失败则熔断"一致）
        self._emit("fail", step.index, payload={"error": last_error, "screenshot": await self.browser.screenshot()})
        self.records.append(record)
        self.aborted = True
        self.abort_step = step.index
        raise StepAbortError(last_error)                         # 上抛，agent 主循环 catch 后进 phase5

    self.records.append(record)
    self._emit("step_done", step.index, payload={"status": "成功", "耗时ms": elapsed_ms, "耗时分解": timing})
```

**关键控制流约定（不可改）：**

- verify 失败 → 进入下一次重试（不是直接熔断）；3 次都失败 → 熔断。
- 异常（grounding 失败、动作异常）→ 进入下一次重试；3 次都异常 → 熔断。
- 熔断 = 整个用例停止，进 phase5 出报告。**不继续后续步骤。**（这是对 SKILL.md "重试失败则熔断并停止执行"的忠实实现。）
- 优化信号：仅在步骤失败或需要视觉/试错辅助时收集（见 §3.6）。

### 3.2 三个 LLM 调用点（单一职责 + 规则化包围）

遵循 LLM 集成横切规则。只有 3 个 LLM 调用点，各管一件窄事，动作执行本身（click/fill）是规则派发、不调 LLM。

#### 调用点 1：parse_step

- **单一职责**：把一步自然语言拆解为结构化要素。
- **输入**：`{"step_text": "在「请输入用户名」输入框中输入手机号，确认..."}`（单步原始文本）
- **输出 JSON schema**：

```json
{
  "action_type": "click | fill | check | scroll | wait | upload | download | keypress",
  "target_ref": "自然语言指代，给 grounding 用，如『请输入用户名』输入框",
  "value": "fill 时为输入值；keypress 时为键名(如 Enter)；其余为 null",
  "expected": "预期结果，一句话",
  "done_criteria": "完成标准，给 verify 用，一句话，必须是页面可验证状态"
}
```

- **action_type 枚举定义**：

| 值 | 含义 | 需要 grounding | value |
|---|---|---|---|
| `click` | 单击 | 是 | null |
| `fill` | 输入文本 | 是 | 输入值 |
| `check` | 勾选复选框 | 是 | null |
| `scroll` | 滚动 | 否 | null |
| `wait` | 等待 | 否 | null |
| `upload` | 上传文件 | 是 | 文件路径 |
| `download` | 下载 | 是 | null |
| `keypress` | 按键 | 是 | 键名 |

`NEEDS_GROUNDING = {"click","fill","check","upload","download","keypress"}`

- **行为边界**：只解析单步，不跨步；不揣测业务意图；done_criteria 必须是页面可观测状态。
- **兜底**：JSON 解析失败 → 重试 2 次 → 仍失败则该步标记异常、action_type 置 "wait"、done_criteria 置原文，不熔断整个用例（解析问题不该中断执行）。

#### 调用点 2：grounding

- **单一职责**：在 AX 树文本中找出目标节点，返回 AX 语义定位器。
- **输入**：`{"target_ref": "『立即登录』按钮", "ax_text": "<AX 树文本>"}`（ax_text 格式见 §3.5）
- **输出 JSON schema**：

```json
{
  "found": true,
  "ref": 2,
  "role": "button",
  "name": "立即登录",
  "rationale": "目标指代为『立即登录』按钮，AX 树中存在 button \"立即登录\""
}
```

未找到时：`{"found": false, "ref": 0, "role": "", "name": "", "rationale": "未找到匹配节点"}`

- **ref 语义**：1-based，表示"在 AX 树深度优先遍历中，该 role+name 组合是第几个匹配项"。用于同名多节点消歧（见 §3.5）。ref=0 表示未找到。
- **行为边界**：只能从给定 AX 文本中选；不得臆造不存在节点；role/name 必须取 AX 文本中的原值（不规范化）。
- **兜底**：JSON 解析失败 / found=false / ref 无效 → 重试 3 次 → 仍失败抛 `GroundingError`，由 execute_step 重试逻辑处理，最终熔断。

#### 调用点 3：verify

- **单一职责**：判定完成标准在当前页面状态下是否满足。
- **输入**：`{"done_criteria": "页面跳转至工作台，可见『我的对话』", "ax_state": "<操作后 AX 树文本>"}`
- **输出 JSON schema**：

```json
{
  "pass": true,
  "reason": "AX 树中出现『我的对话』『新建对话』等元素，登录表单已不可见"
}
```

- **行为边界**：只判定给定完成标准；依据只能是 ax_state 中的内容；不得引用未提供的上下文。
- **兜底**：JSON 解析失败 → 重试 2 次 → 仍失败则 `pass=false, reason="verify 调用异常，需人工复核"`，步骤按失败处理（不熔断，进重试）。

每个调用点对应 `prompts/` 下一份 system prompt（见 §6），输出固定 JSON。无宽泛委托。

### 3.3 grounding 模块 + 为 cache 留口（grounding.py）

将来 locator cache / hybrid 模式 / 失效重建的地基，当前只立接口、不实现缓存。

```python
class Grounding:
    async def ground(self, target_ref: str, ax_text: str) -> GroundingResult:
        """指代 + AX文本 → GroundingResult。内部调 LLM(grounding)。"""
```

- **cache 留口**：`GroundingResult.locator` 即回放时可复用的锚点。将来 hybrid 模式 = "有命中 cache 的 locator 就直接 `get_by_role`、跳过 LLM；locator 失效再回退 LLM grounding" = 失效重建。这条回退路径当前不写，但 `ground()` 签名 `(target_ref, ax_text)` 已为它留好——将来加一层 `ground_with_cache(target_ref, ax_text, cache)` 包裹即可，不改核心。
- **与上游 spec 对齐**：`AxLocator` 与 `case_execution_unified_spec.md` 的 `LocatorAsset.candidates[{type:"role", value:{role,name}}]` 同构，未来合并时 cache 层可直接衔接。
- **稳定性说明**：role+name 是 AX 语义层稳定锚点（前端改 class/结构但语义不变则仍命中），优于 CSS/XPath。`ref` 仅消歧/诊断用，不稳定，不入 cache。

### 3.4 工具面（browser.py）

每个能力是一个 Python 函数（硬约束），对应 SKILL.md 6 项能力。所有方法 async。

```python
class Browser:
    def __init__(self, page: Page): ...

    async def get_page_state(self) -> str:
        """返回 page.aria_snapshot() 文本（AX 树）。不做额外序列化。"""

    async def perform_action(self, action_type: str, gr: GroundingResult | None, value: str | None):
        """规则派发：click/fill/check/scroll/wait/upload/download/keypress。
        交互类用 gr.locator 经 get_by_role 落地（见 §3.5）。不调 LLM。"""

    async def wait_stable(self, timeout_s: float = 4.0):
        """轻量等待：给页面一点时间渲染，不追求"绝对稳定"。
        见下方 wait_stable 重写规格。"""

    async def wait_normal(self, timeout_s: float = 8.0): ...   # 普通等待（页面跳转）
    async def wait_active(self, timeout_s: float = 60.0): ...  # 主动等待（AI 处理/长任务）

    async def scroll_chat_to_bottom_if_exists(self):
        """若存在 class=chat-history 元素，滚动到底。每步开始前调。"""

    async def screenshot(self) -> str:
        """截图，返回路径。熔断时调。"""
```

- `perform_action` 内部按 action_type 分支，**不调 LLM**。click/fill/check 自带 Playwright actionability 自动等待，无需额外 wait。
- `detect_loop` 不单独实现；循环检测语义并入 `wait_active`（见下）。

#### wait_stable 重写规格（效率关键，必须照此实现）

**问题背景**：原实现用"整页 AX 哈希连续 2 次一致"判稳，默认 30s 超时。对含 loading 动画/AI 流式输出的动态页面，AX 树每次都变，条件永不满足，必然跑满 30s，且超时异常会触发重试级联熔断。这是当前执行慢的主因。

**重写原则：不追求"页面绝对稳定"，只追求"给渲染留够时间"。** 大部分步骤根本不需要显式等待（Playwright 动作自带自动等待）；只有动作后需要给页面一点时间反应时才短等。

```python
async def wait_stable(self, timeout_s: float = 4.0) -> None:
    """动作后的轻量等待：固定短停顿 + 早退。
    - 默认 4s 上限。
    - 轮询间隔 200ms，最多 ceil(timeout_s/0.2) 次。
    - 早退条件：AX 文本哈希连续 2 次一致（页面确实静下来了）。
    - 不把超时当异常：到上限直接返回（不抛），交给 verify 判定状态是否达标。
    """
```

**关键约定（不可改）：**

1. `wait_stable` **永不抛异常**——超时即视为"等够了"返回。避免动态页面级联熔断。
2. 默认超时 **4s**（非 30s）。`wait_normal` 8s，`wait_active` 60s。
3. `wait_active`（AI 对话/长任务）：轮询 AX，检测"流式停止"——连续 N 次（如 3 次，间隔 1s）AX 无变化视为回答结束；上限 60s。**不**用整页哈希严格一致。
4. execute_step 的 `except` 只捕 grounding/动作异常，**不再因 wait 超时熔断**（因 wait_stable 不抛）。

> 效率预期：动态步骤从 30s 降到 ≤4s，全用例等待时间大幅下降。真实瓶颈由 §3.7 耗时埋点实测定位。

### 3.5 AX 文本与节点定位（核心技术细节，必须照此实现）

#### AX 文本生成

**直接使用 Playwright 内置 `page.aria_snapshot()`，返回 AX 树文本。不自造序列化、不移植录制端 `snapshotToText`、不用 Python 版不存在的 `page.accessibility.snapshot()`。**

决策理由（路线2）：

- Python Playwright 无 `page.accessibility.snapshot()`（仅 JS 版有）。原设计文档此为事实错误。
- `aria_snapshot()` 自带 AX 状态属性（`[checked]`/`[disabled]` 等），信息完整，满足 verify 需求（实测确认）。
- 定位货币是 `role+name`，aria_snapshot 与录制端 snapshotToText 在 role/name 两字段上完全一致，格式细节差异（value 写法 `: "v"` vs `[value="v"]`、叶子 text 节点）不影响定位与 grounding。
- 将来合并 ai_ui_recorder 时，录制端也切 `aria_snapshot()`（JS/Python 皆有），全链路统一，比维护自造格式更可持续。
- `page_state.py` 的 `prune_snapshot`/`snapshot_to_text` 在此路线下**不用于生产路径**，可删除或仅保留为测试工具。

`aria_snapshot()` 实际输出格式（实测）：

```
- checkbox "同意协议" [checked]
- text: 同意协议
- textbox "请输入用户名": "15700078644"
- button "禁用按钮" [disabled]
- radiogroup:
  - radio [checked]
  - text: 密码登录
```

语法要点（供 prompt 编写参考）：
- `- role "name"`：角色 + 名称。
- `[checked]`/`[disabled]`/`[expanded]`：状态属性，方括号。
- `: "value"`：textbox 等的当前值，冒号引号。
- `- text: xxx`：纯文本节点。
- 缩进 2 空格表层级，有子节点的角色末尾带 `:`。

grounding/verify 的 prompt 示例须按此真实格式编写（见 §6）。

#### 从 grounding 结果落地到 Playwright 操作

grounding 返回 `{found, ref, role, name}`。落地逻辑（`browser.perform_action` 内）：

```python
async def _resolve_locator(self, gr: GroundingResult) -> Locator:
    if gr.locator.name:
        loc = self.page.get_by_role(gr.locator.role, name=gr.locator.name)
    else:
        loc = self.page.get_by_role(gr.locator.role)   # 无 name（如未命名 checkbox）
    count = await loc.count()
    if count == 0:
        raise GroundingError(f"get_by_role 未匹配: {gr.locator}")
    if count == 1:
        return loc
    # 多匹配：用 ref 消歧（1-based nth）
    idx = gr.ref - 1
    if idx < 0 or idx >= count:
        raise GroundingError(f"ref {gr.ref} 超出范围 (count={count})")
    return loc.nth(idx)
```

然后按 action_type 操作：
- `click` → `await loc.click()`
- `fill` → `await loc.fill(value)`
- `check` → `await loc.check()`
- `keypress` → `await loc.press(value)`

#### 已知限制（第一版接受，记录在案）

1. **get_by_role 匹配顺序假设**：`count > 1` 时用 `loc.nth(ref-1)` 消歧，前提是 Playwright `get_by_role` 匹配顺序与 AX 树深度优先遍历顺序一致。Playwright 按 DOM 顺序返回，AX 遍历基本按 DOM 顺序——大概率一致，不保证 100%。第一版接受；消歧错误由优化信号记录。
2. **未命名元素**：aria_snapshot 对无 name 的元素（如某些 checkbox）可能不输出可定位文本，grounding 须返回 role + 空 name，落地用不带 name 的 `get_by_role`。若同 role 多个，靠 ref 消歧。

### 3.7 耗时埋点（效率观测，必做）

为定位真实瓶颈，execute_step 须分段计时并写入事件流：

- `grounding` 事件 payload 加 `耗时ms`。
- `verify` 事件 payload 加 `耗时ms`。
- `step_done` 事件 payload 加 `耗时分解: {grounding_ms, wait_ms, verify_ms}` + 总 `耗时ms`。

跑完用例后，从事件流/报告可看出每步时间花在 grounding / wait / verify 哪段，据此决定后续优化方向（LLM 调用慢则考虑降级/合并，wait 慢则调超时，verify 慢则简单判定走规则快路径）。

### 3.6 用例优化信号收集（phase4 输入）

执行中记录以下信号（在 execute_step 失败路径或辅助判断时收集）：

- 元素定位多次失败后成功 / 依赖视觉辅助
- 等待时间超阈值
- 步骤描述与实际 AX 结构不匹配
- 完成标准模糊或歧义
- 需要试错才找到正确操作
- 步骤顺序不合理或冗余
- 未明确可验证完成标准

累计 ≥3 条 → phase4 生成优化后用例（保持原始目标不变）；<3 条 → 报告中"优化后建议用例"填"无"。

---

## 4. 技术路线分歧

### 分歧①：页面状态序列化方式
- A. Playwright `page.accessibility.snapshot()`（Python 版不存在，不可用）
- B. 自定义 `evaluate` dump 可交互元素清单
- C. 移植录制端 `snapshotToText`（需先把 aria_snapshot 文本解析回 dict，成本高）
- D. **直接用 `page.aria_snapshot()`**（Playwright 内置 AX 文本）
- **采用 D**。理由：定位货币是 role+name，aria_snapshot 自带 `[checked]` 等状态属性信息完整，role/name 与录制端一致；不自造解析层，实现最简且 Playwright 官方维护。详见 §3.5 决策。

### 分歧②：解析阶段用 LLM 还是规则
- A. 纯规则解析
- B. LLM `parse_step`
- **采用 B**。理由：用例是 LLM 生成的自然语言，五要素抽取规则脆弱；解析只跑一次、不进每步循环，成本可控。

### 分歧③：verify 用 LLM 还是规则
- A. 规则
- B. LLM `verify`
- **采用 B**。理由：完成标准是自然语言，规则覆盖不全；单一窄调用，输出 pass/fail。

> 成本提示：三处均用 LLM，每步约 2 次调用（grounding + verify），外加开头一次解析。

---

## 5. 用户交互与程序入口

形态：**CLI + 实时流式输出 + 程序级函数入口**。核心原则沿用 `case_execution_unified_spec.md`：**函数参数作为主入口，CLI 仅做薄适配**。

### 5.1 双层入口

**函数入口（主入口，给 agent 调用 / 联调用）：**

```python
# agent/__init__.py 导出
async def run_case(
    case_file: str,
    *,
    headed: bool = False,
    trace: bool = False,
    on_event: Callable[[Event], None] | None = None,
) -> RunResult
```

- 所有核心逻辑挂此函数，不依赖 typer / 浏览器全局状态，可被另一个 agent 直接 `await` 调用。
- `on_event`：可选事件回调，订阅结构化事件。不传则无副作用。
- 返回 `RunResult`，调用方拿结构化结果，无需解析文本输出。
- 联调场景：翻译模块调 `run_case(case_file, on_event=its_collector)`，既收实时事件流对账，又拿 `RunResult` 做最终判定。不起子进程、不解析 CLI 文本。

**CLI 入口（薄适配，给人用）：**

```
python -m agent run <case_file> [--headed] [--trace]
```

- 仅参数解析，转调 `run_case()`。
- 流式输出：CLI 传一个 `on_event`，将事件渲染成 SKILL.md ②阶段"每步输出模板"打到终端。
- Ctrl+C 优雅停：捕获信号，保存当前进度报告后退出。

### 5.2 事件流契约

```python
@dataclass
class Event:
    type: str           # 见下枚举
    step_index: int     # 当前步号（1-based，parse_done/finish 时为 0）
    total: int          # 总步数
    payload: dict       # 类型相关载荷
```

| type | 触发时机 | payload 要点 |
|---|---|---|
| `parse_done` | 用例解析完成 | case_name、total、steps 概要 |
| `step_start` | 每步开始 | action、target |
| `grounding` | grounding 完成 | found、ref、role、name、rationale |
| `verify` | 校验完成 | pass、reason |
| `step_done` | 每步结束 | status、耗时ms |
| `warn` | 重试/循环检测/优化信号 | 原因 |
| `fail` | 步骤最终失败（熔断前） | error、screenshot |
| `finish` | 全部完成或熔断 | passed、failed、finished、abort_step、report_path |

- 当下 sink：终端渲染。
- 联调 sink：调用方 `on_event` 收集器。
- 将来 sink：SSE 推送（未实现）。事件源不变，只换 sink。

### 5.3 输入与输出

- **输入**：单个 `agent.txt` 文件路径。当下不支持 `step_2_structured_steps.json`，留待后续。
- **报告输出**：按 SKILL.md Output Format 落 `test_record_{用例名}_{YYYYMMDD_HHMMSS}.json` 到当前工作目录，路径打印终端 / 写入 `RunResult.report_path`。
- **trace**：`--trace` 开启 Playwright trace，落盘到报告同目录，供 trace viewer 回放。

---

## 6. Prompt 骨架（规则化包围实体）

三份 prompt 文件位于 `agent/prompts/`。开发者按以下骨架填充，**约束部分（Constraints/Output Format）不得改动**，仅 Role 描述可润色。每个 prompt 强制要求输出纯 JSON（无 markdown 围栏、无标签外文字）。

### 6.1 parse_step.md 骨架

```
# Role: Web UI 测试步骤解析器

## 职责
将单步中文测试步骤拆解为结构化要素，供下游 grounding 与 verify 使用。

## 输入
单步自然语言步骤文本。

## 输出契约（纯 JSON，禁止围栏与标签外文字）
{
  "action_type": "click|fill|check|scroll|wait|upload|download|keypress",
  "target_ref": "给 grounding 的自然语言指代",
  "value": "fill 输入值 / keypress 键名 / 其余 null",
  "expected": "预期结果",
  "done_criteria": "页面可验证的完成标准"
}

## 约束
- action_type 必须是枚举值之一。
- target_ref 必须包含足够让 grounding 在 AX 树中找到元素的语义（可见文案/placeholder/角色）。
- done_criteria 必须是页面可观测状态，不得是抽象业务目标。
- 只解析当前这一步，不跨步合并。

## 示例
输入：在「请输入用户名」输入框中输入手机号，确认用户名输入框 value 变为"15700078644"
输出：{"action_type":"fill","target_ref":"『请输入用户名』输入框","value":"15700078644","expected":"用户名输入框显示已输入值","done_criteria":"用户名输入框 value 为 15700078644"}
```

### 6.2 grounding.md 骨架

```
# Role: AX 树元素定位器

## 职责
给定自然语言指代与页面 AX 树文本，找出目标节点，返回 AX 语义定位器。

## 输入
{"target_ref": "...", "ax_text": "<AX 树文本，Playwright aria_snapshot 格式：- role \"name\"，状态属性 [checked]，值 : \"v\">"}

## 输出契约（纯 JSON）
{
  "found": true|false,
  "ref": <int, 1-based, 该 role+name 在 AX 深度优先遍历中的第几个匹配>,
  "role": "AX 角色",
  "name": "AX 名称",
  "rationale": "选择依据"
}

## 约束
- role/name 必须取 AX 文本中的原值，不得规范化或臆造。
- 只能从给定 ax_text 中选；不存在则 found=false。
- ref 用于同名多节点消歧：若该 role+name 唯一，ref=1；若多个，ref=目标在遍历中的第几个。
- 不得依赖 xpath/css。

## 示例
输入 ax_text 含 `- button "立即登录"`，target_ref="『立即登录』按钮"
输出：{"found":true,"ref":1,"role":"button","name":"立即登录","rationale":"AX 树中存在 button 立即登录"}
```

### 6.3 verify.md 骨架

```
# Role: 页面状态校验器

## 职责
判定完成标准在当前页面 AX 状态下是否满足。

## 输入
{"done_criteria": "...", "ax_state": "<操作后 AX 树文本>"}

## 输出契约（纯 JSON）
{"pass": true|false, "reason": "判定依据，引用 ax_state 中的具体内容"}

## 约束
- 判定依据只能是 ax_state 中存在的内容，不得引用未提供的上下文。
- 不得揣测，信息不足时 pass=false 并在 reason 说明。
```

---

## 7. 验收标准（开发者自检依据）

### 7.1 模块级单元测试（tests/，无浏览器依赖）

- `test_page_state.py`：[可选，page_state 已不用于生产路径] 若保留裁剪工具，测其正确性；否则可删。生产路径用 `aria_snapshot()`，无需单测（Playwright 内置）。
- `test_models.py`：dataclass 序列化/字段完整性。
- `test_case_parser.py`：mock `call_llm` 返回固定 JSON，`parse` 正确产出 `Case`；JSON 解析失败时走兜底（不抛异常）。

### 7.2 端到端最小验收（需浏览器 + 网络 + API key）

用 `agents.txt` 步骤 1（完成用户登录）作为最小验收用例：

```
验收脚本：python -m agent run agents.txt --headed --trace   （或单独跑步骤1的裁剪用例）
```

**通过标准：**

1. `run_case` 正常返回 `RunResult`，`finished=True`。
2. 浏览器导航到 `agents.txt` 起始 URL。
3. 步骤1 的 grounding 能在登录页 AX 树中选中「请输入用户名」textbox 与「立即登录」button（`grounding` 事件 found=true）。
4. fill 手机号后 verify 通过（用户名 value 变更）。
5. 点击立即登录后 verify 通过（页面跳转、登录表单消失）。
6. 报告 JSON 落盘，路径写入 `RunResult.report_path`，结构符合 SKILL.md Output Format。

**若登录页需验证码等无法自动完成的因素**，验收可降级为"前两步（输入用户名 + 勾选协议）grounding 与 verify 通过"，并记录为已知环境限制。

### 7.3 联调验收

另一个 agent（翻译模块）调用 `run_case(case_file, on_event=collector)`：
- 能收到完整事件流（parse_done → step_start → grounding → verify → step_done → ... → finish）。
- 返回的 `RunResult` 字段完整可用。
- 不抛未捕获异常。

---

## 8. 横切规则检查

- **LLM 集成**：3 个调用点均按"单一职责+规则化包围"设计，各五项（职责/输入/输出/边界/兜底）已定义，JSON 输出，无宽泛委托。✓
- **运行安全**：测试执行器，无持久化数据写入风险；熔断保证不无限循环（重试上限 3 + 循环检测 5 次强制继续）；报告落盘是唯一写操作。✓

---

## 9. 本次不做（明确边界）

- ❌ locator cache / hybrid 模式 / 失效重建（只留 `AxLocator` 接口口子）
- ❌ 多 tab / 多浏览器上下文
- ❌ 上游"人录制→生成 agents.txt"那套（背景，不做）
- ❌ `step_2_structured_steps.json` 输入支持
- ❌ PyInstaller 打包（先 `pip install` 跑通）
- ❌ Web Dashboard / SSE（事件流已留 sink 口子）

---

## 10. 关联与后续

- 行为规格来源：`web-ui-case-executor/SKILL.md`（五阶段、五要素、等待分级、熔断、6项能力、JSON 报告格式）。
- 表示层与执行器架构参考：`ai_ui_recorder/`（录制端 `snapshot-utils.js` AX 序列化、`doc/case_execution_unified_spec.md` Hybrid Runner + LocatorAsset）。
- 下一阶段（背景，不做）：locator cache / hybrid 模式 / 失效重建——即 unified spec 的 `hybrid` 模式，`AxLocator` 与其 `LocatorAsset` 已同构衔接。
