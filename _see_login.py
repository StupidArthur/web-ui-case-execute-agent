"""看现在 /login 页面 AX 内容到底是什么。"""
import asyncio, sys
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright

LOGIN_URL = "https://tpt.supcon.com/tpt-app/#/login"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await ctx.new_page()
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        ax = await page.aria_snapshot()
        print(f"url={page.url}")
        print("------ AX 全文 ------")
        print(ax)
        print("------ 窗口保留 15s ------")
        try:
            await page.wait_for_timeout(15000)
        except Exception:
            pass
        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
