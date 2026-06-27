"""headed 单独打开起始 URL，不执行任何用例步骤。
dump 当前 AX 快照到 snapshot_now.txt，然后窗口停着不关，等人来看。
"""
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright

START_URL = "https://tpt.supcon.com/tpt-app/#/home/chat/main?TptSaasUserTenantryId=ATL43NW8"
OUT = Path("snapshot_now.txt")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()

        await page.goto(START_URL, wait_until="domcontentloaded")
        # 给重定向/渲染留时间
        await page.wait_for_timeout(4000)

        ax = await page.aria_snapshot()
        OUT.write_text(ax, encoding="utf-8")
        print(f"URL: {page.url}")
        print(f"AX 快照已写入: {OUT.resolve()}")
        print("------ AX 前 60 行 ------")
        for line in ax.splitlines()[:60]:
            print(line)
        print("------ 窗口保持打开 300s，请人工查看 ------")
        await page.wait_for_timeout(300000)
        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
