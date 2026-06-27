"""用真实 Browser 类跑 nav_settle，但给 get_page_state 打桩每轮打印 URL+AX 摘要。"""
import asyncio, sys, time, hashlib
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from agent.core.browser import Browser

START_URL = "https://tpt.supcon.com/tpt-app/#/home/chat/main?TptSaasUserTenantryId=ATL43NW8"


async def main():
    # 模拟 agent: goto 前先做 parse_case 耗时 ~15s
    print("模拟 parse_case 延迟 15s...")
    await asyncio.sleep(15)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        # 与 agent.run_case 完全一致
        ctx = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await ctx.new_page()
        b = Browser(page)

        # 打桩 get_page_state：打印每轮 URL + AX 首行
        _orig = b.get_page_state
        counter = {"n": 0}
        async def traced():
            counter["n"] += 1
            url = page.url
            ax = await _orig()
            first = ax.splitlines()[0].strip() if ax else "(empty)"
            print(f"    poll#{counter['n']} t={time.time()-t0:.2f}s url={url[:55]} ax0={first[:40]}")
            return ax
        b.get_page_state = traced

        t0 = time.time()
        await page.goto(START_URL, wait_until="domcontentloaded")
        print(f"goto done t={time.time()-t0:.2f}s url={page.url[:60]}")
        await b.wait_for_navigation_settle()
        print(f"nav_settle done t={time.time()-t0:.2f}s url={page.url[:60]}")
        # 再等 5s 看 URL 是否还会变
        for _ in range(5):
            await page.wait_for_timeout(1000)
            print(f"  extra wait url={page.url[:60]}")
        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
