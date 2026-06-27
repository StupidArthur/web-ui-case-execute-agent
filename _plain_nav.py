"""判别：完整 run_case，但 wait_for_navigation_settle 换成 _ab_test B 的朴素循环。
固定 500ms × 10 轮，读 url，不阶梯不 dwell 不拍 snapshot。
若成功 → nav_settle 的阶梯/dwell 逻辑是问题；若失败 → run_case 路径另有阻塞点。
"""
import asyncio, sys
sys.stdout.reconfigure(encoding="utf-8")
from agent import run_case, Event
import agent.core.browser as browser_mod

async def _plain_nav(self, timeout_s=30.0):
    print(f"  [plain_nav] 朴素 500ms×10 循环读 url")
    for i in range(10):
        await self.page.wait_for_timeout(500)
        url = self.page.url
        if "/login" in url:
            print(f"  [plain_nav] t={i*0.5+0.5:.1f}s 检测到 /login ✓")
            return
    print(f"  [plain_nav] 5s 未到 /login ✗ url={self.page.url[:55]}")
browser_mod.Browser.wait_for_navigation_settle = _plain_nav

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
