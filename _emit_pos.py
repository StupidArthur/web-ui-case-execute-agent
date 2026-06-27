"""确认 + 验证修复方向：emit 位置。
C2: 复刻 run，emit 在 goto 前（=原逻辑）→ 预期失败
E:  复刻 run，emit 在 goto+nav 之后 → 预期成功（修复方向）
"""
import asyncio, sys
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from agent.core.case_parser import parse_case
from agent.core.browser import Browser
from agent.core.agent import Agent
from agent.core.models import Event
from pathlib import Path

START_URL = "https://tpt.supcon.com/tpt-app/#/home/chat/main?TptSaasUserTenantryId=ATL43NW8"
CASE = "agents_login_only.txt"


async def plain_wait(page, label):
    for i in range(10):
        await page.wait_for_timeout(500)
        if "/login" in page.url:
            print(f"  [{label}] ✓ t={i*0.5+0.5:.1f}s")
            return True
    print(f"  [{label}] ✗")
    return False


def make_emit(on_event, total):
    def emit(type_, step_index, payload=None):
        if on_event:
            on_event(Event(type=type_, step_index=step_index, total=total, payload=payload or {}))
    return emit


async def variant(label, emit_before_goto: bool):
    raw = Path(CASE).read_text(encoding="utf-8")
    case = await parse_case(raw)
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=False)
        ctx = await b.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=None)
        page = await ctx.new_page()
        br = Browser(page, trace_dir=None)
        agent = Agent(case=case, browser=br, on_event=lambda e: None)
        emit = make_emit(lambda e: None, total=len(case.steps))
        if emit_before_goto:
            emit("parse_done", 0, payload={"case_name": case.name, "total": len(case.steps),
                  "steps": [(s.index, s.raw_text[:60]) for s in case.steps]})
        await page.goto(START_URL, wait_until="domcontentloaded")
        ok = await plain_wait(page, label)
        if not emit_before_goto:
            emit("parse_done", 0, payload={"case_name": case.name, "total": len(case.steps),
                  "steps": [(s.index, s.raw_text[:60]) for s in case.steps]})
        try: await page.wait_for_timeout(1000)
        except: pass
        await ctx.close(); await b.close()
        return ok


async def main():
    print("=== C2: emit 在 goto 前（原逻辑）===")
    c2 = await variant("C2 emit前", emit_before_goto=True); await asyncio.sleep(1)
    print("\n=== E: emit 在 goto+nav 后（修复方向）===")
    e = await variant("E emit后", emit_before_goto=False)
    print(f"\nC2 emit前: {'成功' if c2 else '失败'}")
    print(f"E  emit后: {'成功' if e else '失败'}")


if __name__ == "__main__":
    asyncio.run(main())
