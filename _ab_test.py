"""同时刻 A/B 对照，锁死变量。
A: goto(start_url) + 循环 wait_for_timeout(500) 读 url，5s（复刻 _observe）
B: 先 parse_case，再 goto(start_url) + 同样循环，5s
两者唯一差别：B 多了 parse_case。
"""
import asyncio, sys, time
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from agent.core.case_parser import parse_case
from pathlib import Path

START_URL = "https://tpt.supcon.com/tpt-app/#/home/chat/main?TptSaasUserTenantryId=ATL43NW8"
CASE = "agents_login_only.txt"


async def goto_and_wait(label: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await ctx.new_page()
        await page.goto(START_URL, wait_until="domcontentloaded")
        ok = False
        for i in range(10):
            await page.wait_for_timeout(500)
            if "/login" in page.url:
                ok = True
                break
        print(f"  [{label}] {'重定向 ✓' if ok else '未重定向 ✗'} url={page.url[:55]}")
        try:
            await page.wait_for_timeout(3000)
        except Exception:
            pass
        await ctx.close()
        await browser.close()
        return ok


async def main():
    print("=== A: 无 parse_case，goto + 循环等 ===")
    a = await goto_and_wait("A无parse_case")
    await asyncio.sleep(1)
    print("\n=== B: 先 parse_case，再 goto + 循环等 ===")
    raw = Path(CASE).read_text(encoding="utf-8")
    case = await parse_case(raw)
    print(f"  parse_case 完成")
    b = await goto_and_wait("B有parse_case")
    print(f"\n=== 汇总 ===")
    print(f"A 无 parse_case: {'成功' if a else '失败'}")
    print(f"B 有 parse_case: {'成功' if b else '失败'}")


if __name__ == "__main__":
    asyncio.run(main())
