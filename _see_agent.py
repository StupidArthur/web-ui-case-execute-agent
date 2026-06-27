"""让 agent 完整跑，但 nav_settle 完成后暂停 20s 给人工看窗口（停在邀请码页还是 /login）。
不跑 LLM 步骤，只走到 nav_settle，真实复现 agent 的 goto 路径 + parse_case 前置。
"""
import asyncio, sys, time
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from agent.core.browser import Browser
from agent.core.case_parser import parse_case
from pathlib import Path

CASE = "agents_login_only.txt"


async def main():
    # 真实复现：先 parse_case（含 4 次 LLM），再 goto + nav_settle
    print("先跑 parse_case（4 次 LLM），复现 agent 前置耗时...")
    t0 = time.time()
    raw = Path(CASE).read_text(encoding="utf-8")
    case = await parse_case(raw)
    print(f"parse_case 用时 {time.time()-t0:.1f}s，解析出 {len(case.steps)} 步")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await ctx.new_page()
        b = Browser(page)

        _orig = b.get_page_state
        async def traced():
            url = page.url
            ax = await _orig()
            first = ax.splitlines()[0].strip() if ax else "(empty)"
            print(f"    gps url={url[:55]} ax0={first[:30]}")
            return ax
        b.get_page_state = traced

        await page.goto(case.start_url, wait_until="domcontentloaded")
        await b.wait_for_navigation_settle()
        print(f"\n>>> nav_settle 完成，最终 URL: {page.url[:70]}")
        print(f">>> 重定向到 /login: {'是' if '/login' in page.url else '否（停在邀请码/落地页）'}")
        print(">>> 窗口保留 20s，请人工确认页面状态...")
        try:
            await page.wait_for_timeout(20000)
        except Exception as e:
            print(f"  (窗口关闭: {type(e).__name__})")
        try: await ctx.close()
        except Exception: pass
        try: await browser.close()
        except Exception: pass


if __name__ == "__main__":
    asyncio.run(main())
