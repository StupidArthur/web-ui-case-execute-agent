# 诊断报告：完整 run_case 路径下 goto 后重定向不发生（根因未明，待外部 review）

> 状态：**根因未锁定**。已通过大量对照实验排除多个假设，变量收窄到"调 `Agent.run()` 方法"本身，但无法解释机制。需外部 AI 协助。
> 整理日期：2026-06-27（最新修订）
> 项目：`G:\cc_demos\web-ui-case-execute-agent`（Web UI 自动化测试执行 Agent，Python 3.11 + Playwright，Windows 11）

---

## 0. 一句话现象

被测起始 URL：
```
https://tpt.supcon.com/tpt-app/#/home/chat/main?TptSaasUserTenantryId=ATL43NW8
```
正常：`page.goto(start_url)` 后，前端路由守卫在 **1.5~5s** 内重定向到 `https://tpt.supcon.com/tpt-app/#/login`（登录页，AX 含 `textbox "请输入用户名"`）。

异常：**走完整 `run_case` → `Agent.run()` 路径时**，goto 后 URL 全程停在 `#/home/chat/main`，重定向**不发生**，AX 停在公共落地页（`- text: 流程工业时序大模型TPT...` + `textbox "请输入您的邀请码"`），grounding 找不到「请输入用户名」，用例熔断。

**关键：同一台机器、同一时刻、同样的 `page.goto(start_url)`，走 `Agent.run()` 就不重定向，走精简/复刻脚本就重定向。** 这是确定性的（多轮复现），但根因未明。

---

## 1. 已排除的假设（均有判别实验，勿再重复）

| 假设 | 证伪实验 | 结果 |
|---|---|---|
| 服务端会话/租户态失效导致 `/login` 渲染邀请码页 | `_observe.py`（goto start_url + 纯 wait_for_timeout 循环） | **重定向成功**，AX 是登录页。服务端正常。 |
| 直接 `goto('/login')` 能到登录页 | `_see_login.py` / `_direct_login.py` | 直接 goto('/login') 渲染邀请码页（因不带租户上下文）；但从 start_url 重定向过去是登录页。**这不是 bug，是站点设计**。 |
| `parse_case` 的 LLM 调用干扰 goto | `_ab_test.py`（同时刻 A 无 parse_case / B 有 parse_case） | A、B **都成功**。parse_case 不是变量。 |
| httpx 资源累积泄漏（外部 AI 假设） | `_leak_test.py`（纯 chat.chat 1次/4次后 goto） | 1次、4次**都成功**。非累积泄漏。 |
| `aria_snapshot()` 阻塞重定向 | `_url_repeat.py`（不调 snapshot 也失败）+ `_final_ab.py`（同时刻：精简脚本不调 snapshot 成功 / run_case 调 snapshot 失败） | snapshot 不是唯一变量；且 `wait_for_navigation_settle` 改为不调 snapshot 后 `run_case` 仍失败。 |
| `wait_for_navigation_settle` 的阶梯/dwell 逻辑 | `_plain_nav.py`（run_case + 朴素 500ms 循环 nav，无阶梯无 dwell） | 仍失败。nav 等待逻辑不是变量。 |
| `new_context(record_video_dir=None)` kwarg | `_ctx_test.py` V1(无kwarg)/V2(video=None) | V1、V2 **都成功**。kwarg 不是变量。 |
| `Agent` 构造本身 | `_agent_ctor.py` B（构造 Agent 不调 run） | **成功**。Agent 构造不是变量。 |
| `_emit("parse_done")` 在 goto 前调用 | `_emit_pos.py` C2（手动复刻 run 逻辑，含 emit 在 goto 前） | C2 **成功**。emit 本身不是变量。 |

---

## 2. 当前收窄到的变量（核心未解问题）

**变量 = "调用真正的 `Agent.run()` 方法" vs "手动复刻等价的 run() 逻辑"。**

`_agent_ctor.py` / `_emit_pos.py` 的对照（同一脚本内顺序跑，确定性）：

| 变体 | 描述 | 结果 |
|---|---|---|
| A | 不构造 Agent，直接 goto + 朴素 nav | ✓ |
| B | 构造 Agent，不调 run，直接 goto + 朴素 nav | ✓ |
| C | 构造 Agent + **调 `agent.run()`**（nav_settle 被 patch 成朴素循环） | **✗** |
| D | 构造 Agent + 手动复刻 run() 逻辑、**跳过 emit**、goto + 朴素 nav | ✓ |
| C2 | 构造 Agent + 手动复刻 run() 逻辑、**含 emit**、goto + 朴素 nav | ✓ |
| E | 构造 Agent + 手动复刻 run()、emit 放 goto 后 | ✓ |

**C（调 `agent.run()`）失败，C2（手动复刻 run 的等价逻辑，含 emit）成功。** 两者代码上几乎等价，差别只在"调真正的 `agent.run()` 方法"vs"手动写等价代码"。

### `Agent.run()` 源码（`agent/core/agent.py` L48-66）

```python
async def run(self) -> RunResult:
    self._emit(
        "parse_done", 0,
        payload={
            "case_name": self.case.name,
            "total": len(self.case.steps),
            "steps": [(s.index, s.raw_text[:60]) for s in self.case.steps],
        },
    )
    report_path = ""
    try:
        await self.browser.page.goto(self.case.start_url, wait_until="domcontentloaded")
        await self.browser.wait_for_navigation_settle()
        for step in self.case.steps:
            await self.execute_step(step)
    ...
```

C2 手动复刻的就是这段（emit + goto + nav），但 C2 成功、C 失败。

### 未解的机制问题（需外部 AI 回答）

1. **调用 `Agent.run()` 方法本身，相比手动复刻其等价逻辑，会对随后 `page.goto()` 的浏览器重定向产生确定性影响吗？** 这种"调方法 vs 复刻代码"的差异通常不该存在——除非：
   - `Agent` 是 `@dataclass`，`run` 是绑定方法，调用路径有差异？（不该影响浏览器）
   - `self._emit` 是 `__post_init__` 里 `make_emitter` 创建的闭包，与 C2 的 `make_emit` 闭包有细微差别？（两者都调 `on_event(Event(...))`，on_event 都是 `lambda e: None`）
   - 是否存在某种 `__post_init__` / dataclass 字段默认值在 `run()` 调用时才求值的副作用？

2. C 失败时，nav_settle（被 patch 的朴素 500ms×10 循环）5s 内 URL 全程不变；C2 成功时 URL 在 3~4s 变到 /login。**同一个 `page.goto(start_url)`，重定向是否发生取决于调用方是 `agent.run()` 还是手写代码。** 浏览器进程是同一个，CDP 通道是同一个。

3. 是否是 `agent.run()` 内部 `try/except/finally` 结构、或 `for step in self.case.steps` 在 goto 后立即进入 `execute_step`（调 `scroll_chat_to_bottom_if_exists` + `get_page_state`）导致？—— 但 C 失败发生在 nav_settle 阶段（goto 后、execute_step 前），URL 已确定没变。除非 nav_settle 的 patch 未生效。

4. **patch 是否真的生效？** C 通过 `bm.Browser.wait_for_navigation_settle = _plain` patch 类方法，`agent.run()` 调 `self.browser.wait_for_navigation_settle()`。需确认 patch 后 `agent.run()` 走的是 `_plain` 还是原方法。若 patch 未生效，C 走的是原 `wait_for_navigation_settle`（含 aria_snapshot），那 C 失败就回到 snapshot 假设——但 `_final_ab.py` 已证明同时刻精简脚本调 snapshot 也成功……需厘清。

---

## 3. 关键文件与代码

### 3.1 调用链
```
agent/main.py  run 命令
  → agent/core/agent.py  run_case()
      raw = Path(case_file).read_text(...)
      case = await parse_case(raw)              # 4 次 LLM，已证非变量
      async with async_playwright() as p:
          browser = await p.chromium.launch(headless=False)
          context = await browser.new_context(viewport={...}, record_video_dir=None)
          page = await context.new_page()
          agent_browser = Browser(page, trace_dir=None)
          agent = Agent(case=case, browser=agent_browser, on_event=on_event)
          result = await agent.run()            # 【调此方法 = 失败】
              → self._emit("parse_done", ...)   # goto 前
              → await page.goto(start_url)      # 重定向不发生
              → await self.browser.wait_for_navigation_settle()
              → for step: execute_step(step)
```

### 3.2 `Agent` 类（`agent/core/agent.py` L27-46）
```python
@dataclass
class Agent:
    case: Case
    browser: Browser
    on_event: Callable[[Event], None] | None = None
    records: list[StepRecord] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    aborted: bool = False
    abort_step: int | None = None
    optimize_signals: list[OptimizationSignal] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)

    def __post_init__(self):
        self._emit = make_emitter(self.on_event, total=len(self.case.steps))
        self.grounding = Grounding()
        self.verifier = Verifier()
```

### 3.3 `make_emitter`（`agent/core/events.py`）
```python
def make_emitter(on_event, total):
    if on_event is None:
        def noop(type_, step_index, payload=None): pass
        return noop
    def emit(type_, step_index, payload=None):
        on_event(Event(type=type_, step_index=step_index, total=total, payload=payload or {}))
    return emit
```

### 3.4 `Browser.wait_for_navigation_settle`（`agent/core/browser.py`，当前版本已改为纯 URL 轮询不调 aria_snapshot）
见仓库 `agent/core/browser.py` L147-201。

### 3.5 `run_case`（`agent/core/agent.py` L238-276）
见仓库。

---

## 4. 调试脚本（项目根目录，全部 headed）

| 脚本 | 用途 | 关键结果 |
|---|---|---|
| `_observe.py` | goto start_url + 纯 wait_for_timeout 循环 15s，打印 url+ax | 重定向成功（t=3~4s）|
| `_see_login.py` | 直接 goto('/login') 拍 AX | 渲染邀请码页（非 bug）|
| `_leak_test.py` | 纯 chat.chat 1次/4次后 goto | 都成功（证伪泄漏说）|
| `_ab_test.py` | 同时刻 A 无 parse_case / B 有 parse_case | 都成功（证伪 parse_case）|
| `_final_ab.py` | 同时刻 精简脚本 / 完整 run_case | 精简✓ run_case✗ |
| `_ctx_test.py` | V1无kwarg/V2 video=None/V3 完整Agent | V1✓ V2✓ V3✗ |
| `_agent_ctor.py` | A无Agent/B不run/C调run/D跳过emit | A✓ B✓ C✗ D✓ |
| `_emit_pos.py` | C2 emit前 / E emit后 | 都✓（证伪 emit 是变量）|
| `_plain_nav.py` | run_case + 朴素500ms nav | ✗ |
| `_verify_run.py` | 完整 run_case 带日志 | ✗ |
| `_bisect_repeat.py` / `_url_repeat.py` | 连跑3次 | 曾出现3/3失败（疑似当时刻污染）|

---

## 5. 待外部 AI 回答的核心问题

1. 在 Python + Playwright + asyncio 环境下，**调用一个 `@dataclass` 的 async 方法（`Agent.run()`），与手动复刻该方法的等价代码**，是否可能对随后 `page.goto()` 触发的浏览器重定向产生确定性影响？若可能，机制是什么？
2. 第 2 节的 C vs C2 对照（调方法失败 / 复刻代码成功）是否暗示 `agent.run()` 内部有未被观察到的副作用？建议如何进一步插桩（例如打印 goto 前后精确时间戳、CDP 通信日志）定位？
3. 是否需要确认 `_plain` patch 在 `agent.run()` 内真的生效？若未生效，C 走原 `wait_for_navigation_settle`，但当前版本该函数已不调 aria_snapshot，为何仍失败？
4. 是否可能是 `Agent.run()` 的 `try/except/finally` + `for step in ...` 结构导致 goto 后事件循环调度顺序不同，使浏览器侧重定向请求被延迟到 nav_settle 之后才发起？如何验证？
5. 给定治标优先：在 `run_case` 中 goto 后检测未到 `/login` 时 `page.reload()` 或重新 `goto(start_url)`，是否可靠？

---

## 6. 排查过程教训（供参考）

1. **单次实验不足以定论。** 本例中"parse_case 是根因""snapshot 是根因""emit 是根因"都曾被"确定性"宣布，又被下一轮同时刻对照推翻。现象可能受跑的时刻/顺序影响，**必须用同一脚本内 A/B 同时刻对照**才能锁定变量。
2. **"非确定性"假象常源于未控制的时序变量。** 早期 `_no_snap` 等实验跨时段跑，结果被误当确定性。
3. **外部 AI 的精致因果链需可证伪实验检验。** 本例外部 AI 的"httpx 泄漏→IOCP→CDP 背压→V8 挂起"被一次 `_leak_test` 证伪。
4. **grounding 失败时先 dump 页面 AX 全文**，确认页面真实内容，而非假设页面正确去怀疑定位逻辑。
5. **不要用截图排查**（文本模型读不了 PNG），靠 AX 快照文本 + 事件日志。

---

## 附：本次已完成的无关代码改动（保留，非根因修复）

- `browser.py` `wait_for_navigation_settle` 已改为纯 `page.url` 轮询、不调 `aria_snapshot`（阶梯间隔 500ms→1s→2s + 5s 防过早返回窗口）。
- `browser.py` `wait_stable` 改阶梯式（200→500→1000ms）。
- 新增 `Browser.wait_explicit(seconds)` + `perform_action` wait 分支读 `Step.value` 秒数 + `parse_step.md` 约定。
- 单元测试 `python -m pytest agent/tests -v` → 16 passed。
