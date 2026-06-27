"""验证修复方向：parse_case 后 goto，若没重定向到 /login，尝试主动 goto(/login) 拉回登录页。
看主动导航能否恢复到登录页（有用户名/密码输入框）。
"""
import asyncio, sys, time
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from agent.core.case_parser import parse_case
from pathlib import Path

CASE = "agents_login_only.txt"
LOGIN_URL = "https://tpt.supcon.com/tpt-app/#/login"


async def snap(page, tag):
    ax = await page.aria_snapshot()
    lines = [l.strip() for l in ax.splitlines() if l.strip()]
    has_user = any("请输入用户名" in l for l in lines)
    print(f"  [{tag}] url={page.url[:55]} 有用户名输入框={has_user}")
    return has_user


async def main():
    raw = Path(CASE).read_text(encoding="utf-8")
    case = await parse_case(raw)
    print(f"parse_case 完成")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await ctx.new_page()

        await page.goto(case.start_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        ok = await snap(page, "goto后5s")

        if not ok:
            print("  未到登录页，尝试主动 goto /login ...")
            await page.goto(LOGIN_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            ok = await snap(page, "主动goto /login后3s")

        if not ok:
            print("  仍失败，尝试重新 goto start_url ...")
            await page.goto(case.start_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)
            ok = await snap(page, "重新goto start_url后5s")

        print(f"\n>>> 最终能否到登录页: {'是 ✓' if ok else '否 ✗'}")
        print(">>> 窗口保留 15s 供人工确认")
        try:
            await page.wait_for_timeout(15000)
        except Exception:
            pass
        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
