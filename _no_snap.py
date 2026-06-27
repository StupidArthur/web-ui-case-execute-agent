"""判别实验：parse_case 后 goto，nav_settle 期间【只轮询 page.url，不打 AX 快照】。
看是否还能重定向到 /login。若能 → 证明 aria_snapshot 打断了重定向。
"""
import asyncio, sys, time
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from agent.core.case_parser import parse_case
from pathlib import Path

CASE = "agents_login_only.txt"


async def main():
    raw = Path(CASE).read_text(encoding="utf-8")
    case = await parse_case(raw)
    print("parse_case 完成")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await ctx.new_page()

        await page.goto(case.start_url, wait_until="domcontentloaded")
        print(f"goto done url={page.url[:60]}")

        # 只轮询 url，绝不调 aria_snapshot
        t0 = time.time()
        for i in range(1, 21):  # 最多 20s
            await page.wait_for_timeout(500)
            url = page.url
            print(f"  poll#{i} t={time.time()-t0:.1f}s url={url[:60]}")
            if "/login" in url:
                print(f">>> {time.time()-t0:.1f}s 检测到重定向到 /login ✓")
                break
        else:
            print(">>> 20s 内未重定向 ✗")

        print(f">>> 最终 url={page.url[:60]}")
        # 此时才打一次快照确认页面内容
        ax = await page.aria_snapshot()
        has_user = "请输入用户名" in ax
        print(f">>> 有用户名输入框={has_user}")
        print(">>> 窗口保留 12s 供人工确认")
        try:
            await page.wait_for_timeout(12000)
        except Exception:
            pass
        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
