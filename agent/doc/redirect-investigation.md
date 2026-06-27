# 诊断报告：parse_case 的 LLM 网络调用干扰浏览器 goto 重定向

> 状态：实测确证现象与根因方向，但**底层机制未明**，待外部 review。
> 整理日期：2026-06-27
> 项目：`G:\cc_demos\web-ui-case-execute-agent`（Web UI 自动化测试执行 Agent，Python + Playwright）

---

## 0. 一句话结论

`run_case` 中「先 `parse_case`（内含 4 次 LLM 调用）→ 再 `page.goto()`」的顺序，会导致 goto 后页面**不重定向**到 `/login`，停在公共落地页；把两者顺序对调（先 goto 再 parse_case），重定向就正常。**现象确定性可复现，但「为什么 LLM 的 HTTP 调用会干扰随后一个全新浏览器 context 的导航」在逻辑上无法解释，需协助定位机制。**

---

## 1. 现象

被测站点起始 URL：
```
https://tpt.supcon.com/tpt-app/#/home/chat/main?TptSaasUserTenantryId=ATL43NW8
```
正常行为：浏览器打开该 URL 后，前端路由守卫在 **1.5~4.6s** 内重定向到 `https://tpt.supcon.com/tpt-app/#/login`（登录页，含 `textbox "请输入用户名"`、`textbox "请输入密码"`、`button "立即登录"`）。

异常行为：完整 agent 流程跑时，goto 后 URL 全程停在 `#/home/chat/main`，AX 快照首行为 `- text: 流程工业时序大模型TPT Time-series Pr...`（公共落地页，非登录页），**重定向从不发生**。于是第 1 步 grounding 找不到「请输入用户名」输入框，用例熔断。

---

## 2. 确定性差异（已实测复现）

下列脚本共用同一段 `goto` + 轮询逻辑，唯一变量是**是否在 goto 之前调用 `parse_case`**。

| 脚本 | goto 前是否跑 `parse_case` | 重定向到 /login | AX 首轮首行 |
|---|---|---|---|
| `_exp5.py`（5 轮连跑） | 否 | **5/5 成功** | `(empty)` 加载中 |
| `_nav_debug.py` | 否 | 成功 | `(empty)` |
| `_observe.py` | 否 | 成功（t=3s） | `(empty)` |
| `_see_agent.py` | 是 | **失败** | `流程工业时序大模型TPT` 已渲染 |
| `_no_snap.py` | 是 | **失败**（20s 不跳） | — |
| 完整 agent（`run_case`） | 是 | **每次失败** | `流程工业时序大模型TPT` |
| `_order_test.py`（先 goto 后 parse_case） | 否（goto 在前） | **成功** | `(empty)` |

关键对照：
- `_exp5`（无 parse_case）5 轮全成功；完整 agent（有 parse_case）每次全失败 —— **确定性，非随机**。
- `_order_test` 把 parse_case 挪到 goto+重定向之后 —— 成功。**证明变量就是 parse_case 的执行时机，与浏览器 context、与等待逻辑、与 snapshot 都无关。**

---

## 3. 已排除的假设

| 假设 | 排除依据 |
|---|---|
| `aria_snapshot()` 打断重定向（CDP 通道争用） | `_no_snap.py`：nav 期间只轮询 `page.url`、绝不调 `aria_snapshot`，仍失败 |
| 服务端租户态随机抖动 | 5 次连跑全成功 vs 全量每次全失败，是确定性的；服务端随机无法解释这种「按是否 parse_case 二分」的规律 |
| `parse_case` 耗时（~9s）导致的纯时间延迟 | `_nav_debug.py` 加 `asyncio.sleep(15)` 模拟延迟，仍重定向成功 |
| `wait_for_navigation_settle` 逻辑缺陷 | 该逻辑在「无 parse_case」场景下 5/5 正确抓到 1.5~4.6s 的重定向；且 `_no_snap` 不用该逻辑、纯轮询 URL 也失败 |
| cookie / context 残留 | 每次 `browser.new_context()` 都是全新 context，无 cookie 复用 |

---

## 4. 当前结论与未解的机制问题

**已确证**：`parse_case` 在 goto 之前执行，是导致重定向失败的**充分且必要**条件。

**`parse_case` 内部唯一的外部副作用**是 4 次 LLM 调用，经 `agent/core/llm.py` → `chat.py` → `openai.AsyncOpenAI`（httpx 异步客户端）。

**未解的机制问题**（核心，需协助分析）：

1. `openai.AsyncOpenAI` 的 LLM 调用与随后的 `page.goto()` 共用同一个 asyncio 事件循环。LLM 调用产生的 httpx 连接池 / 全局网络状态，**如何**影响一个全新 Playwright 浏览器 context 内部发起的 HTTP 请求（前端路由守卫的租户 token 校验请求）？
2. 是否是 httpx 与 Playwright（底层 CDP over WebSocket）争用事件循环，导致浏览器侧某个 XHR/fetch 超时，前端路由守卫走了「停留落地页」分支而非「重定向 /login」分支？
3. 还是 httpx 的全局 SSL 上下文 / DNS resolver / 代理设置污染了 Playwright 浏览器进程的网络栈？（注：Playwright 浏览器是独立子进程，理论上有独立网络栈，但 CDP 控制通道走宿主 loop。）
4. openai-python / httpx 版本相关的已知 issue？

**待验证的下一步实验**（未做）：
- 用 `asyncio.run_in_executor` 或独立线程/子进程跑 LLM 调用，隔离事件循环，看是否恢复。
- 给 `openai.AsyncOpenAI` 传入独立的 `httpx.AsyncClient`（独立 transport/连接池），看是否恢复。
- 在 goto 期间抓浏览器网络日志（`page.on("request"/"response")`），对比有无 parse_case 时租户校验请求的差异。

---

## 5. 涉及的模块与组件

### 5.1 调用链

```
agent/main.py  run 命令
  → agent/core/agent.py  run_case()
      ①  raw_text = Path(case_file).read_text(...)
      ②  case = await parse_case(raw_text)          ← 【根因所在】此处先跑 4 次 LLM
      ③  async with async_playwright() as p:
            browser = await p.chromium.launch(...)
            context = await browser.new_context(...)
            page = await context.new_page()
      ④  await page.goto(case.start_url, ...)       ← 【受干扰】重定向不发生
      ⑤  await browser.wait_for_navigation_settle()
      ⑥  for step: await agent.execute_step(step)   ← 第 1 步 grounding 失败
```

### 5.2 关键文件

| 文件 | 角色 |
|---|---|
| `agent/core/agent.py` | `run_case()` 编排，**顺序①②→③④ 是问题所在**（见 L246-262） |
| `agent/core/case_parser.py` | `parse_case()` → `_parse_single_step()` 每步调 1 次 LLM，4 步 = 4 次调用 |
| `agent/core/llm.py` | `call_llm()` / `call_llm_with_prompt()`，加载 prompt 后调 `chat.chat()` |
| `chat.py`（项目根） | 统一 LLM 封装，`chat()` 内部 `client = openai.AsyncOpenAI(api_key, base_url)` 然后 `await client.chat.completions.create(...)` |
| `agent/core/browser.py` | `Browser.wait_for_navigation_settle()` 导航等待（已优化为阶梯式，但非根因） |
| `agents_login_only.txt` | 触发用例（4 步登录+偏好设置） |
| `config.local.json` | `model=MiniMax-M3`，`url=https://api.minimax.chat/v1` |

### 5.3 LLM 调用细节（`chat.py` L207-231）

```python
cfg = _MODELS[model]                       # MiniMax-M3
client = openai.AsyncOpenAI(               # 每次调用 new 一个 client
    api_key=api_key,
    base_url=cfg["url"],                   # https://api.minimax.chat/v1
)
# extra_body 含 reasoning_split=True, thinking={type:disabled}
completion = await client.chat.completions.create(
    model=cfg["api"], messages=messages,
    temperature=temperature, max_tokens=cfg["max_tokens"],
    extra_body=extra_body or None,
)
```
注意：`openai.AsyncOpenAI` 默认使用一个模块级/进程级 httpx 连接池与 SSL 上下文。`parse_case` 跑 4 次，每次 new 一个 client 但共享底层 httpx 全局状态。这是怀疑干扰源。

### 5.4 浏览器侧（`agent/core/agent.py` L254-262）

```python
async with async_playwright() as p:
    browser = await p.chromium.launch(headless=not headed)
    context = await browser.new_context(viewport={"width":1280,"height":720})
    page = await context.new_page()
    agent_browser = Browser(page, ...)
    agent = Agent(case=case, browser=agent_browser, on_event=on_event)
    result = await agent.run()   # 内部 page.goto(start_url) + wait_for_navigation_settle
```
Playwright 的 CDP 控制通道（WebSocket）跑在同一个 asyncio 事件循环上。

### 5.5 依赖版本（`requirements.txt`）

```
playwright
openai
typer
```
（未 pin 版本；实际环境 Python 3.11 / Windows 11）

---

## 6. 复现步骤

```bash
cd G:\cc_demos\web-ui-case-execute-agent

# 复现失败（先 parse_case 后 goto）：
python _see_agent.py      # 或完整 agent：python _verify_run.py

# 复现成功（先 goto 后 parse_case）：
python _order_test.py

# 复现成功（无 parse_case）：
python _exp5.py           # 5 轮连跑
```
所有 `_*.py` 脚本均在项目根目录，headed 模式，会弹出浏览器窗口。文本日志打印每轮 URL 变化与 AX 首行。

---

## 7. 待外部 AI 回答的问题

1. 在同一 asyncio 事件循环里，先跑 `openai.AsyncOpenAI` 的 httpx 请求、再跑 Playwright `page.goto()`，是否存在已知的相互干扰机制？
2. 若存在，是 httpx 全局状态（连接池/SSL/DNS）污染，还是事件循环争用导致 CDP 指令延迟，进而让浏览器侧某个有时间限制的路由守卫请求超时？
3. 最小且治本的隔离方案是什么？（独立事件循环 / 独立 httpx client / 子进程 / `asyncio.run_in_executor`？）
4. 是否需要抓 `page.on("request")` / `page.on("console")` 对比有无 parse_case 时浏览器侧网络请求差异，以锁定被干扰的具体请求？

---

## 附：本次已完成的无关修复（供参考，非本问题）

- `browser.py` 等待逻辑改为阶梯式自适应（`wait_stable` 200→500→1000ms；`wait_for_navigation_settle` 500→1000→2000ms，URL 变化判重定向 + 5s 防过早返回窗口）。在「无 parse_case 干扰」场景下 5/5 稳定抓到重定向。
- 新增显式等待：`Browser.wait_explicit(seconds)` + `perform_action` 的 wait 分支读 `Step.value` 作秒数强制等满；`agent/prompts/parse_step.md` 约定 wait 动作 value=秒数字符串。
- 单元测试 `python -m pytest agent/tests -v` → 16 passed。
