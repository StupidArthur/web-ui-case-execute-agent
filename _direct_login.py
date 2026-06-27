"""判别：直接 page.goto('/login')，不靠重定向，连跑3次看是否稳定到登录页。"""
import asyncio, sys
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright

LOGIN_URL = "https://tpt.supcon.com/tpt-app/#/login"


async def one(idx):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await ctx.new_page()
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        ax = await page.aria_snapshot()
        ok = "请输入用户名" in ax
        print(f"  第{idx}轮: 直接goto /login → {'登录页 ✓' if ok else '非登录页 ✗'} url={page.url[:50]}")
        try:
            await page.wait_for_timeout(4000)
        except Exception:
            pass
        await ctx.close()
        await browser.close()
        return ok


async def main():
    rs = [await one(i) for i in range(1, 4)]
    print(f"\n汇总: {sum(rs)}/3 成功到登录页")


if __name__ == "__main__":
    asyncio.run(main())
