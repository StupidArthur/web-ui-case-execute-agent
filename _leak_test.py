"""判别：累积泄漏假说。直接调 chat.chat N 次（不经 parse_case），再 goto 看重定向。
- 1 次成功、4 次失败 → 累积泄漏成立，async with 关闭是对的方向
- 1 次也失败 → 非累积，另查
"""
import asyncio, sys, time
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
import chat
from agent.config import load_config

START_URL = "https://tpt.supcon.com/tpt-app/#/home/chat/main?TptSaasUserTenantryId=ATL43NW8"


async def call_llm_n(n: int):
    cfg = load_config()
    for i in range(n):
        r = await chat.chat(
            model=cfg.model,
            messages=[{"role": "user", "content": f"回复一个字：{i}"}],
            api_key=cfg.api_key,
            temperature=0.1,
        )
        print(f"  LLM#{i+1} done: {r.content[:20]}")


async def goto_and_check(label: str):
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
                print(f"  [{label}] t={time.time()-t0:.1f}s 重定向 ✓")
                redirected = True
                break
        if not redirected:
            print(f"  [{label}] 20s 未重定向 ✗ url={page.url[:55]}")
        try:
            await page.wait_for_timeout(6000)
        except Exception:
            pass
        await ctx.close()
        await browser.close()
        return redirected


async def main():
    print("=== 对照 A: 调 1 次 LLM 后 goto ===")
    await call_llm_n(1)
    r1 = await goto_and_check("1次LLM")
    await asyncio.sleep(2)

    print("\n=== 对照 B: 调 4 次 LLM 后 goto ===")
    await call_llm_n(4)
    r4 = await goto_and_check("4次LLM")

    print("\n=== 汇总 ===")
    print(f"1 次 LLM: {'重定向成功' if r1 else '失败'}")
    print(f"4 次 LLM: {'重定向成功' if r4 else '失败'}")
    if r1 and not r4:
        print(">>> 累积泄漏假说成立（1次OK/4次失败）→ async with 关 client 是对的方向")
    elif not r1:
        print(">>> 1 次也失败 → 非累积泄漏，async with 关单个 client 未必能救")


if __name__ == "__main__":
    asyncio.run(main())
