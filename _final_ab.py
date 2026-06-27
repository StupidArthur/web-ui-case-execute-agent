"""真正同时刻对照：同一脚本内顺序跑
1. 精简脚本（_ab_test B 风格）：parse_case + goto + 朴素500ms循环
2. 完整 run_case（_plain_nav 风格）：run_case + 同样的朴素500ms循环 nav
若 1成功2失败 → 变量在 run_case 路径（new_context参数/Agent构造/...）。
"""
import asyncio, sys
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from agent.core.case_parser import parse_case
from agent import run_case, Event
import agent.core.browser as browser_mod
from pathlib import Path

START_URL = "https://tpt.supcon.com/tpt-app/#/home/chat/main?TptSaasUserTenantryId=ATL43NW8"
CASE = "agents_login_only.txt"


async def plain_wait(page, label):
    for i in range(10):
        await page.wait_for_timeout(500)
        if "/login" in page.url:
            print(f"  [{label}] t={i*0.5+0.5:.1f}s 到 /login ✓")
            return True
    print(f"  [{label}] 5s 未到 /login ✗")
    return False


async def test_simple():
    """精简：parse_case + 自管浏览器 + goto + 朴素循环。"""
    raw = Path(CASE).read_text(encoding="utf-8")
    await parse_case(raw)
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=False)
        ctx = await b.new_context(viewport={"width": 1280, "height": 720})
        page = await ctx.new_page()
        await page.goto(START_URL, wait_until="domcontentloaded")
        ok = await plain_wait(page, "精简")
        try: await page.wait_for_timeout(2000)
        except: pass
        await ctx.close(); await b.close()
        return ok


async def test_runcase():
    """完整 run_case，nav_settle 换成朴素循环。"""
    async def _plain(self, timeout_s=30.0):
        return await plain_wait(self.page, "run_case")
    browser_mod.Browser.wait_for_navigation_settle = _plain

    def on_event(ev: Event):
        if ev.type == "finish":
            print(f"  [run_case finish] passed={ev.payload.get('passed')} abort={ev.payload.get('abort_step')}")

    result = await run_case(CASE, headed=True, trace=False, on_event=on_event)
    return result.passed > 0


async def main():
    print("=== 1. 精简脚本 ===")
    r1 = await test_simple()
    await asyncio.sleep(1)
    print("\n=== 2. 完整 run_case ===")
    r2 = await test_runcase()
    print(f"\n=== 汇总 ===")
    print(f"精简脚本: {'成功' if r1 else '失败'}")
    print(f"完整 run_case: {'成功' if r2 else '失败'}")


if __name__ == "__main__":
    asyncio.run(main())
