"""5 次重定向对照实验：每轮真实 run_case 路径，nav_settle 后暂停给你看窗口。
每轮打印 nav 期间每 poll 的 URL，以及最终 URL。窗口保留 8s 供人工确认。
"""
import asyncio, sys, time
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from agent.core.browser import Browser
from agent.core.case_parser import parse_case
from pathlib import Path

START_URL = "https://tpt.supcon.com/tpt-app/#/home/chat/main?TptSaasUserTenantryId=ATL43NW8"


async def one_round(idx: int):
    """单轮：真实 Browser + goto + nav_settle，打印每 poll URL，暂停 8s。"""
    print(f"\n========== 第 {idx} 轮 ==========")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await ctx.new_page()
        b = Browser(page)

        # 打桩 gps 打印 URL
        _orig = b.get_page_state
        poll_log = []
        async def traced():
            url = page.url
            ax = await _orig()
            first = ax.splitlines()[0].strip() if ax else "(empty)"
            poll_log.append((url, first))
            return ax
        b.get_page_state = traced

        t0 = time.time()
        await page.goto(START_URL, wait_until="domcontentloaded")
        await b.wait_for_navigation_settle()
        final_url = page.url
        elapsed = time.time() - t0

        print(f"nav_settle 用时 {elapsed:.1f}s")
        print("每 poll URL 变化:")
        for i, (u, a) in enumerate(poll_log, 1):
            print(f"  poll#{i} url={u[:60]} ax0={a[:30]}")
        redirected = "/login" in final_url
        print(f">>> 最终 URL: {final_url[:70]}")
        print(f">>> 重定向到 /login: {'是 ✓' if redirected else '否 ✗ (停在邀请码/落地页)'}")
        print(f">>> 第 {idx} 轮窗口保留 20s 供人工确认，请看浏览器窗口...")
        try:
            await page.wait_for_timeout(20000)
        except Exception as e:
            print(f"  (窗口提前关闭: {type(e).__name__})")
        try:
            await ctx.close()
        except Exception:
            pass
        try:
            await browser.close()
        except Exception:
            pass
        return redirected


async def main():
    results = []
    for i in range(1, 6):
        try:
            r = await asyncio.wait_for(one_round(i), timeout=90)
        except asyncio.TimeoutError:
            print(f"第 {i} 轮超时")
            r = None
        results.append(r)
        await asyncio.sleep(2)  # 轮间间隔
    print("\n========== 汇总 ==========")
    for i, r in enumerate(results, 1):
        print(f"第 {i} 轮: {r}")


if __name__ == "__main__":
    asyncio.run(main())
