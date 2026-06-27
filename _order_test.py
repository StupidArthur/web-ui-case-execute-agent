"""判别实验：先 goto + 等重定向，再 parse_case。
若重定向恢复成功 → 证明 parse_case 的 LLM 网络调用干扰了 goto 期间的网络。
"""
import asyncio, sys, time
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from agent.core.case_parser import parse_case
from pathlib import Path

CASE = "agents_login_only.txt"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await ctx.new_page()

        # 1. 先 goto（此时还没跑 parse_case，没有 LLM 网络干扰）
        await page.goto("https://tpt.supcon.com/tpt-app/#/home/chat/main?TptSaasUserTenantryId=ATL43NW8",
                        wait_until="domcontentloaded")
        print(f"goto done url={page.url[:60]}")

        # 2. 只轮询 url 看是否重定向（不打快照）
        t0 = time.time()
        redirected = False
        for i in range(1, 21):
            await page.wait_for_timeout(500)
            url = page.url
            if "/login" in url:
                print(f"  poll#{i} t={time.time()-t0:.1f}s 检测到 /login ✓")
                redirected = True
                break
        if not redirected:
            print(f"  20s 未重定向 ✗ 最终 url={page.url[:60]}")

        # 3. 重定向判定后，再跑 parse_case
        print("现在跑 parse_case ...")
        raw = Path(CASE).read_text(encoding="utf-8")
        case = await parse_case(raw)
        print(f"parse_case 完成，{len(case.steps)} 步")

        ax = await page.aria_snapshot()
        has_user = "请输入用户名" in ax
        print(f">>> 重定向到 /login: {redirected}")
        print(f">>> 有用户名输入框: {has_user}")
        print(">>> 窗口保留 12s 供人工确认")
        try:
            await page.wait_for_timeout(12000)
        except Exception:
            pass
        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
