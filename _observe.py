"""纯观察：打开起始 URL，每 1s 打印 URL + AX 前 3 行，持续 15s。不带任何 agent 逻辑。"""
import asyncio, sys
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright

START_URL = "https://tpt.supcon.com/tpt-app/#/home/chat/main?TptSaasUserTenantryId=ATL43NW8"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await ctx.new_page()
        await page.goto(START_URL, wait_until="domcontentloaded")
        for s in range(1, 16):
            await page.wait_for_timeout(1000)
            try:
                url = page.url
                ax = (await page.aria_snapshot()).splitlines()
                top = " | ".join(x.strip() for x in ax[:3] if x.strip())
            except Exception as e:
                url, top = f"err:{e}", ""
            print(f"t={s:>2}s  url={url[:70]}")
            print(f"        ax: {top[:90]}")
        print("--- 观察结束，10s 后关闭 ---")
        await page.wait_for_timeout(10000)
        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
