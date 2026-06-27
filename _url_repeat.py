"""连跑 3 次：parse_case + 裸 page.url 轮询（不调 aria_snapshot），看是否稳定成功。"""
import asyncio, sys
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from agent.core.case_parser import parse_case
from pathlib import Path

CASE = "agents_login_only.txt"


async def one(idx):
    raw = Path(CASE).read_text(encoding="utf-8")
    case = await parse_case(raw)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await ctx.new_page()
        await page.goto(case.start_url, wait_until="domcontentloaded")
        ok = False
        for _ in range(20):
            await page.wait_for_timeout(500)
            if "/login" in page.url:
                ok = True
                break
        print(f"  第{idx}轮: 裸url轮询 → {'成功 ✓' if ok else '失败 ✗'} url={page.url[:50]}")
        try:
            await page.wait_for_timeout(4000)
        except Exception:
            pass
        await ctx.close()
        await browser.close()
        return ok


async def main():
    rs = []
    for i in range(1, 4):
        rs.append(await one(i))
        await asyncio.sleep(1)
    print(f"\n汇总: {sum(rs)}/3 成功")


if __name__ == "__main__":
    asyncio.run(main())
