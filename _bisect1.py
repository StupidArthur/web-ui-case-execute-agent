"""二分1：parse_case 后，用真实 Browser.wait_for_navigation_settle（含 aria_snapshot）等重定向。
区别于 _parsecase_test（裸 url 轮询）。若失败 → 嫌疑在 nav_settle/aria_snapshot。
"""
import asyncio, sys, time
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from agent.core.browser import Browser
from agent.core.case_parser import parse_case
from pathlib import Path

CASE = "agents_login_only.txt"


async def main():
    raw = Path(CASE).read_text(encoding="utf-8")
    case = await parse_case(raw)
    print(f"parse_case 完成，{len(case.steps)} 步")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await ctx.new_page()
        b = Browser(page)  # 真实 Browser，nav_settle 会调 aria_snapshot

        await page.goto(case.start_url, wait_until="domcontentloaded")
        await b.wait_for_navigation_settle()
        ok = "/login" in page.url
        print(f">>> 用真实 nav_settle 后 url={page.url[:60]}")
        print(f">>> 重定向到 /login: {'成功 ✓' if ok else '失败 ✗'}")
        try:
            await page.wait_for_timeout(8000)
        except Exception:
            pass
        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
