# Web UI 自动化测试执行 Agent — 进展与待办

> 最后更新：2026-06-26

## 一、当前进展

### 1.1 已完成的核心实现

按照 `agent/doc/design.md`，已完成整个 Agent 骨架：

| 模块 | 文件 | 说明 |
|---|---|---|
| 数据模型 | `agent/core/models.py` | `Config`, `Step`, `Case`, `AxLocator`, `GroundingResult`, `Verdict`, `StepRecord`, `OptimizationSignal`, `RunResult`, `Event` |
| 配置读取 | `agent/config.py` | 读取 `config.local.json`，含明确错误提示 |
| LLM 封装 | `agent/core/llm.py` | 复用项目根 `chat.py`，提供 `call_llm` / `call_llm_with_prompt` |
| 用例解析 | `agent/core/case_parser.py` | 解析 `agents.txt`，把每个 `- ` 子步骤作为独立 `Step`；`parse_step` LLM 调用 + JSON 失败兜底 |
| AX 序列化 | `agent/core/page_state.py` | `prune_snapshot` + `snapshot_to_text`，单元测试验证格式 |
| 浏览器工具 | `agent/core/browser.py` | Playwright 封装：定位、操作、等待、截图、循环检测 |
| grounding | `agent/core/grounding.py` | `target_ref + ax_text → GroundingResult`，支持空 name（如未命名 checkbox） |
| verifier | `agent/core/verifier.py` | `done_criteria + ax_state → Verdict` |
| 状态机 | `agent/core/agent.py` | 3 次重试、单步失败熔断、事件流、优化信号收集、grounding 缓存 |
| 报告 | `agent/core/reporter.py` | 生成 `SKILL.md` 格式 JSON 报告 |
| 事件流 | `agent/core/events.py` | `Event` 构造与 `make_emitter` |
| CLI | `agent/main.py`, `agent/__main__.py` | `python -m agent run <case_file> [--headed] [--trace]` |
| Prompts | `agent/prompts/*.md` | `parse_step.md`, `grounding.md`, `verify.md` |
| 单元测试 | `agent/tests/*.py` | `test_models.py`, `test_page_state.py`, `test_case_parser.py` |
| 项目配置 | `requirements.txt`, `.gitignore`, `config.local.json.example` | 依赖、忽略规则、配置模板 |

### 1.2 已验证结果

- **单元测试**：`python -m pytest agent/tests -v` —— **16 passed**。
- **API key 可用性**：调用 `chat.chat('MiniMax-M3', ...)` 返回正常。
- **端到端最小登录用例**（`test_login.txt`，3 步）：
  - 步骤 1（fill 用户名）：✅ 成功
  - 步骤 2（check 同意协议）：✅ 成功
  - 步骤 3（click 立即登录）：❌ 失败，按钮 disabled

### 1.3 已做的速度优化

1. **grounding 结果在同一轮重试内复用**：第一次成功后缓存，后续重试不再重复调用 LLM grounding。
2. **`wait_stable` 轮询间隔从 500ms 降到 200ms**，稳定判定更快返回。

---

## 二、遗留问题

### 2.1 登录用例第三步失败（当前阻塞）

**现象**：

```
TimeoutError: Locator.click: Timeout 30000ms exceeded.
waiting for get_by_role("button", name="立即登录")
  - locator resolved to <button disabled ...>立即登录</button>
  - element is not enabled
```

**原因分析**：

- 当前登录页为"密码登录"模式（ARIA snapshot 中可见 `radio "密码登录" [checked]`）。
- 表单包含：用户名输入框、密码输入框、同意协议 checkbox、立即登录按钮。
- 只有用户名和协议被操作时，登录按钮保持 disabled，必须同时填写密码才能启用。
- `agents.txt` / `test_login.txt` 第一步的子步骤中**没有输入密码的动作**，导致第三步按钮不可点击。

**解决方向**：

1. 在登录用例中补充"输入密码"子步骤。
2. 或者确认测试环境是否支持无密码登录 / 自动填充密码。
3. 如果密码是敏感信息，需要设计从安全渠道（环境变量、配置、密钥管理）注入，而不是写死在用例文件中。

### 2.2 单步执行速度仍然偏慢

**现象**：

端到端测试中，单步仍可能耗时数秒到十几秒。

**原因分析**：

- design.md 当前架构规定**每步 2 次 LLM 调用**：
  - `grounding`：自然语言指代 → AX 定位器
  - `verify`：完成标准 → pass/fail
- 此外每步还有：
  - 1 次 `parse_step`（一次性，平摊后影响小）
  - 多次 `get_page_state()` / `aria_snapshot()`
  - `wait_stable()` 轮询
- LLM API 调用本身（MiniMax-M3）通常需要 2–8 秒，两步叠加就是主要耗时来源。

**已做优化**：

- 重试内 grounding 缓存（减少重复 LLM 调用）。
- `wait_stable` 间隔缩短到 200ms。

**根本性解决方向**：

- 实现 **locator cache / hybrid 模式**：第一次用 LLM grounding，后续步骤直接复用 `get_by_role`；locator 失效再回退 LLM。
- 这对应 design.md §9 中明确标记为"本次不做"的项，但可以显著提升速度。

### 2.3 CLI 中文输出在 Windows 终端显示乱码

**现象**：

```
Usage: python -m agent [OPTIONS] COMMAND [ARGS]...
Web UI �Զ�������ִ������
```

**原因分析**：

- 源文件本身为 UTF-8 编码（已验证）。
- Windows 终端/控制台默认使用 GBK 编码解码 stdout，导致 UTF-8 中文字节显示为乱码。
- 这是环境编码问题，不影响程序逻辑和文件写入（报告 JSON 中中文正常）。

**解决方向**：

- 在 `main.py` 中检测并设置 stdout 编码为 UTF-8（如 `sys.stdout.reconfigure(encoding='utf-8')`）。
- 或者用户在 UTF-8 终端（如 Windows Terminal + PowerShell 7 / Git Bash）中运行。

### 2.4 页面状态表示与录制端格式可能存在差异

**现象**：

- design.md 要求移植 `ai_ui_recorder/recorder/src/recorder/snapshot-utils.js` 的 `pruneSnapshot` + `snapshotToText`，使用 `page.accessibility.snapshot()`。
- 但 **Playwright Python 的 `Page` 对象没有 `accessibility` 属性**，实际使用的是 `page.aria_snapshot()`。

**原因分析**：

- Playwright Python API 与 Node.js API 不完全一致，`page.accessibility` 不存在。
- `page.aria_snapshot()` 返回的也是 ARIA/AX 树 YAML 风格文本，语义对齐，但格式细节可能与录制端有差异。

**影响**：

- 当前端到端测试能正常定位 `textbox "请输入用户名"` 和 `button "立即登录"`，说明基本可用。
- 如果后续与录制端/翻译端联调时出现格式不一致，需要统一表示层。

**解决方向**：

- 使用 CDP session 调用 `Accessibility.getFullAXTree`，自己实现 prune + 序列化，完全对齐录制端。
- 或者验证 `aria_snapshot()` 格式与录制端足够接近，保持当前实现。

### 2.5 信号处理代码可能不正确

**现象**：

`agent/main.py` 中：

```python
loop = asyncio.get_event_loop()
def _signal_handler(sig, frame):
    for task in asyncio.all_tasks(loop):
        task.cancel()
asyncio.run(_main())
```

**问题**：

- `asyncio.get_event_loop()` 在 `asyncio.run()` 之前获取的 loop，与 `asyncio.run()` 内部创建的新 loop 可能不是同一个。
- Ctrl+C 时取消的可能是旧 loop 的任务，实际效果未验证。

**解决方向**：

- 在 `_main()` 内部获取当前 running loop 并注册信号处理程序。
- 或者使用 `asyncio.run()` 时不提前获取 loop。

---

## 三、下一步建议（按优先级）

### 高优先级

1. **修复登录用例**
   - 确认测试环境登录是否需要密码。
   - 如果需要，补充"输入密码"步骤，并设计密码安全注入方式。
   - 重新运行端到端测试，验证是否能完成登录。

2. **优化执行速度**
   - 实现 locator cache / hybrid 模式：
     - 维护 `target_ref → AxLocator` 映射。
     - 命中 cache 时跳过 LLM grounding，直接 `get_by_role`。
     - locator 失效（count==0）时回退 LLM grounding 并更新 cache。
   - 预计可将每步 LLM 调用从 2 次降到 0–1 次。

### 中优先级

3. **修复 CLI 中文乱码**
   - 在 `main.py` 入口强制设置 `sys.stdout` / `sys.stderr` 编码为 UTF-8。

4. **验证信号处理**
   - 测试 Ctrl+C 是否能正确取消执行并保存报告。
   - 修复 signal handler 中获取 loop 的问题。

### 低优先级

5. **统一页面状态表示**
   - 对比 `aria_snapshot()` 与上游 `snapshot-utils.js` 输出格式。
   - 如有必要，改用 CDP `Accessibility.getFullAXTree` 实现完全一致的格式。

6. **完善测试覆盖**
   - 补充 `test_grounding.py`、`test_verifier.py`、`test_browser.py` 的 mock 测试。
   - 补充端到端测试的降级验收（前两步通过即可）。

---

## 四、关键文件清单

- `agent/doc/design.md` — 设计规格来源
- `agents.txt` — 原始完整用例
- `test_login.txt` — 最小登录验收用例（当前用于调试）
- `config.local.json` — 本地 API 配置（已加入 `.gitignore`）
- `agent/core/agent.py` — 状态机主循环
- `agent/core/browser.py` — 浏览器封装
- `agent/core/grounding.py` — grounding 逻辑
- `agent/core/verifier.py` — verify 逻辑
- `agent/core/case_parser.py` — 用例解析
- `agent/core/reporter.py` — 报告生成
