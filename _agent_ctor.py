"""终极判别：V2 代码 + 在 goto 前构造 Agent（不调 run），自己 goto+nav。
若失败 → Agent 构造本身是变量；若成功 → agent.run() 内某行是变量。
"""
import asyncio, sys
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from agent.core.case_parser import parse_case
from agent.core.browser import Browser
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


async def variant(label, build_agent: bool):
    raw = Path(CASE).read_text(encoding="utf-8")
    case = await parse_case(raw)
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=False)
        ctx = await b.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=None)
        page = await ctx.new_page()
        br = Browser(page, trace_dir=None)
        if build_agent:
            agent = Agent(case=case, browser=br, on_event=lambda e: None)
            # 不调 agent.run()，自己 goto+nav
        await page.goto(START_URL, wait_until="domcontentloaded")
        ok = await plain_wait(page, label)
        try: await page.wait_for_timeout(1500)
        except: pass
        await ctx.close(); await b.close()
        return ok


async def main():
    print("=== A: 不构造 Agent ===")
    a = await variant("A无Agent", build_agent=False); await asyncio.sleep(1)
    print("\n=== B: 构造 Agent 但不调 run ===")
    b = await variant("B有Agent不run", build_agent=True); await asyncio.sleep(1)
    print("\n=== C: 构造 Agent + 调 run()（=V3 复刻） ===")
    # C: 完整 run，nav_settle 已被朴素 patch
    import agent.core.browser as bm
    async def _plain(self, timeout_s=30.0):
        return await plain_wait(self.page, "C run()")
    bm.Browser.wait_for_navigation_settle = _plain
    raw = Path(CASE).read_text(encoding="utf-8")
    case = await parse_case(raw)
    async with async_playwright() as p:
        bb = await p.chromium.launch(headless=False)
        ctx = await bb.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=None)
        page = await ctx.new_page()
        br = Browser(page, trace_dir=None)
        agent = Agent(case=case, browser=br, on_event=lambda e: None)
        await agent.run()
        c = agent.passed > 0
        await ctx.close(); await bb.close()

    print("\n=== D: 构造 Agent + 手动复刻 run() 但【跳过 emit】 ===")
    raw = Path(CASE).read_text(encoding="utf-8")
    case = await parse_case(raw)
    async with async_playwright() as p:
        bb2 = await p.chromium.launch(headless=False)
        ctx2 = await bb2.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=None)
        page2 = await ctx2.new_page()
        br2 = Browser(page2, trace_dir=None)
        agent2 = Agent(case=case, browser=br2, on_event=lambda e: None)
        # 复刻 run()，但跳过 _emit("parse_done")
        await page2.goto(START_URL, wait_until="domcontentloaded")
        d = await plain_wait(page2, "D 跳过emit")
        await ctx2.close(); await bb2.close()
    print(f"\nA 无Agent: {'成功' if a else '失败'}")
    print(f"B 有Agent不run: {'成功' if b else '失败'}")
    print(f"C 调run(): {'成功' if c else '失败'}")
    print(f"D 跳过emit: {'成功' if d else '失败'}")


if __name__ == "__main__":
    asyncio.run(main())
