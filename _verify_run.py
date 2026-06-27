"""验证等待优化：headed 跑 agents_login_only.txt，带时序 + nav 每轮 poll 日志。"""
import asyncio, sys, time
sys.stdout.reconfigure(encoding="utf-8")

from agent import run_case, Event
import agent.core.browser as browser_mod

# 给 Browser.get_page_state 打桩：每次调用打印 URL + AX 首行
_orig_gps = browser_mod.Browser.get_page_state
_t0 = {"v": 0.0}
def _start_t0():
    _t0["v"] = time.time()

async def _traced_gps(self):
    url = ""
    try:
        url = self.page.url
    except Exception:
        pass
    ax = await _orig_gps(self)
    first = ax.splitlines()[0].strip() if ax else "(empty)"
    print(f"    gps t={time.time()-_t0['v']:.2f}s url={url[:55]} ax0={first[:35]}")
    return ax

browser_mod.Browser.get_page_state = _traced_gps

# nav_settle 计时
_orig_nav = browser_mod.Browser.wait_for_navigation_settle
async def _nav(self, timeout_s=30.0):
    _start_t0()
    ub = self.page.url
    await _orig_nav(self, timeout_s)
    print(f"  [nav_settle done] url: {ub[:55]} -> {self.page.url[:55]}")
browser_mod.Browser.wait_for_navigation_settle = _nav

_orig_stable = browser_mod.Browser.wait_stable
async def _stable(self, timeout_s=4.0):
    t0 = time.time()
    await _orig_stable(self, timeout_s)
    print(f"  [wait_stable] {(time.time()-t0)*1000:.0f}ms")
browser_mod.Browser.wait_stable = _stable


def on_event(ev: Event):
    p = ev.payload or {}
    t = ev.type
    if t == "step_start":
        print(f"\n=== 步骤 {ev.step_index}/{ev.total}: {p.get('action')} {p.get('target')}")
    elif t == "grounding":
        print(f"  [grounding] found={p.get('found')} role={p.get('role')} name={p.get('name')} | {p.get('rationale','')[:60]}")
    elif t == "verify":
        print(f"  [verify] pass={p.get('pass')} | {p.get('reason','')[:70]}")
    elif t == "warn":
        print(f"  [warn] {p.get('原因','')[:80]}")
    elif t == "step_done":
        print(f"  [step_done] {p.get('status')} {p.get('耗时ms')}ms")
    elif t == "fail":
        print(f"  [FAIL] {p.get('error')}")
    elif t == "finish":
        print(f"\n=== FINISH passed={p.get('passed')} failed={p.get('failed')} abort={p.get('abort_step')}")


async def main():
    try:
        result = await asyncio.wait_for(
            run_case("agents_login_only.txt", headed=True, trace=False, on_event=on_event),
            timeout=300,
        )
    except asyncio.TimeoutError:
        print("\n!!! 超时"); return
    print(f"\n总耗时 finished={result.finished} passed={result.passed} abort={result.abort_step}")


if __name__ == "__main__":
    asyncio.run(main())
