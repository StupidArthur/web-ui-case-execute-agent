"""判别：复刻 run_case，逐项剥离。看是 new_context 的 record_video_dir kwarg 还是 Agent 包装导致失败。
跑 3 个变体，都用朴素 500ms 循环 nav：
  V1: new_context(viewport) 不传 record_video_dir，无 Agent，直接 goto+nav
  V2: new_context(viewport, record_video_dir=None)（run_case 风格），无 Agent
  V3: 完整 Agent（= run_case）
"""
import asyncio, sys
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from agent.core.case_parser import parse_case
from agent.core.browser import Browser
from agent.core.models import Event
from agent.core.agent import Agent
from pathlib import Path

START_URL = "https://tpt.supcon.com/tpt-app/#/home/chat/main?TptSaasUserTenantryId=ATL43NW8"
CASE = "agents_login_only.txt"


async def plain_wait(page, label):
    for i in range(10):
        await page.wait_for_timeout(500)
        if "/login" in page.url:
            print(f"  [{label}] ✓ t={i*0.5+0.5:.1f}s")
            return True
    print(f"  [{label}] ✗")
    return False


async def v1():
    raw = Path(CASE).read_text(encoding="utf-8")
    await parse_case(raw)
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=False)
        ctx = await b.new_context(viewport={"width": 1280, "height": 720})  # 无 record_video_dir
        page = await ctx.new_page()
        await page.goto(START_URL, wait_until="domcontentloaded")
        ok = await plain_wait(page, "V1无video kwarg")
        try: await page.wait_for_timeout(1500)
        except: pass
        await ctx.close(); await b.close()
        return ok


async def v2():
    raw = Path(CASE).read_text(encoding="utf-8")
    await parse_case(raw)
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=False)
        ctx = await b.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=None)  # 传 None
        page = await ctx.new_page()
        await page.goto(START_URL, wait_until="domcontentloaded")
        ok = await plain_wait(page, "V2 video=None")
        try: await page.wait_for_timeout(1500)
        except: pass
        await ctx.close(); await b.close()
        return ok


async def v3():
    """完整 Agent，nav_settle 换朴素循环。"""
    import agent.core.browser as bm
    async def _plain(self, timeout_s=30.0):
        return await plain_wait(self.page, "V3 Agent")
    bm.Browser.wait_for_navigation_settle = _plain
    raw = Path(CASE).read_text(encoding="utf-8")
    case = await parse_case(raw)
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=False)
        ctx = await b.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=None)
        page = await ctx.new_page()
        br = Browser(page, trace_dir=None)
        agent = Agent(case=case, browser=br, on_event=lambda e: None)
        await agent.run()
        await ctx.close(); await b.close()
        return agent.passed > 0


async def main():
    print("=== V3 先跑: 完整 Agent ===")
    r3 = await v3(); await asyncio.sleep(1)
    print("\n=== V1: 无 record_video_dir kwarg ===")
    r1 = await v1(); await asyncio.sleep(1)
    print("\n=== V2: record_video_dir=None ===")
    r2 = await v2()
    print(f"\n=== 汇总 ===")
    print(f"V3 完整Agent(先跑): {'成功' if r3 else '失败'}")
    print(f"V1 无 kwarg: {'成功' if r1 else '失败'}")
    print(f"V2 video=None: {'成功' if r2 else '失败'}")


if __name__ == "__main__":
    asyncio.run(main())
