"""二次判别：直接调 parse_case（而非裸 chat.chat）后 goto，看是否失败。
若失败 → 问题在 parse_case 特有路径（load_prompt / 长 system message / 解析）。
若成功 → 之前 _see_agent 失败另有原因（如脚本间状态）。
"""
import asyncio, sys, time
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from agent.core.case_parser import parse_case
from pathlib import Path

START_URL = "https://tpt.supcon.com/tpt-app/#/home/chat/main?TptSaasUserTenantryId=ATL43NW8"
CASE = "agents_login_only.txt"


async def main():
    print("=== 调 parse_case 后 goto ===")
    raw = Path(CASE).read_text(encoding="utf-8")
    case = await parse_case(raw)
    print(f"parse_case 完成，{len(case.steps)} 步")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await ctx.new_page()
        await page.goto(START_URL, wait_until="domcontentloaded")
        t0 = time.time()
        redirected = False
        for i in range(1, 21):
            await page.wait_for_timeout(500)
            if "/login" in page.url:
                print(f"  t={time.time()-t0:.1f}s 重定向 ✓")
                redirected = True
                break
        if not redirected:
            print(f"  20s 未重定向 ✗ url={page.url[:55]}")
        print(f">>> parse_case 后重定向: {'成功' if redirected else '失败'}")
        try:
            await page.wait_for_timeout(6000)
        except Exception:
            pass
        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
