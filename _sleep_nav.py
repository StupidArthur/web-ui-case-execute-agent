"""判别：完整 run_case 路径，但把 wait_for_navigation_settle 换成纯 wait_for_timeout(5000)。
若成功 → 轮询 page.url 也会阻塞重定向；若失败 → 阻塞点在别处（如 execute_step 的 gps）。
"""
import asyncio, sys, time
sys.stdout.reconfigure(encoding="utf-8")
from agent import run_case, Event
import agent.core.browser as browser_mod

async def _sleep_nav(self, timeout_s=30.0):
    print(f"  [sleep_nav] 纯等 5s，不读 url 不拍 snapshot")
    await self.page.wait_for_timeout(5000)
    print(f"  [sleep_nav done] url={self.page.url[:60]}")
browser_mod.Browser.wait_for_navigation_settle = _sleep_nav

def on_event(ev: Event):
    p = ev.payload or {}
    t = ev.type
    if t == "step_start":
        print(f"\n=== 步骤 {ev.step_index}/{ev.total}: {p.get('action')} {p.get('target')}")
    elif t == "grounding":
        print(f"  [grounding] found={p.get('found')} role={p.get('role')} name={p.get('name')}")
    elif t == "verify":
        print(f"  [verify] pass={p.get('pass')} | {p.get('reason','')[:60]}")
    elif t == "step_done":
        print(f"  [step_done] {p.get('status')}")
    elif t == "fail":
        print(f"  [FAIL] {p.get('error')}")
    elif t == "finish":
        print(f"\n=== FINISH passed={p.get('passed')} failed={p.get('failed')} abort={p.get('abort_step')}")

async def main():
    result = await asyncio.wait_for(
        run_case("agents_login_only.txt", headed=True, trace=False, on_event=on_event),
        timeout=200,
    )
    print(f"\n总耗时 finished={result.finished} passed={result.passed} abort={result.abort_step}")

if __name__ == "__main__":
    asyncio.run(main())
