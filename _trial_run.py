"""试运行：跑到登录成功后下一步即停。打印事件流。"""
import asyncio, sys, time
sys.stdout.reconfigure(encoding="utf-8")

from agent import run_case, Event


def on_event(ev: Event):
    p = ev.payload or {}
    t = ev.type
    if t == "parse_done":
        print(f"[parse] case={p.get('case_name')} total={p.get('total')}")
    elif t == "step_start":
        print(f"\n=== 步骤 {ev.step_index}/{ev.total} 开始: action={p.get('action')} target={p.get('target')}")
    elif t == "grounding":
        print(f"  [grounding] found={p.get('found')} ref={p.get('ref')} role={p.get('role')} name={p.get('name')} | {p.get('耗时ms')}ms | {p.get('rationale','')[:60]}")
    elif t == "verify":
        print(f"  [verify] pass={p.get('pass')} | {p.get('耗时ms')}ms | {p.get('reason','')[:80]}")
    elif t == "warn":
        print(f"  [warn] {p.get('原因','')}")
    elif t == "step_done":
        print(f"  [step_done] status={p.get('status')} 耗时={p.get('耗时ms')}ms 分解={p.get('耗时分解')}")
    elif t == "fail":
        print(f"  [FAIL] {p.get('error')} | screenshot={p.get('screenshot')}")
    elif t == "finish":
        print(f"\n=== FINISH: passed={p.get('passed')} failed={p.get('failed')} finished={p.get('finished')} abort_step={p.get('abort_step')}")
        print(f"  report={p.get('report_path')}")


async def main():
    t0 = time.time()
    try:
        result = await asyncio.wait_for(
            run_case("agents_login_only.txt", headed=True, trace=False, on_event=on_event),
            timeout=480,
        )
    except asyncio.TimeoutError:
        print("\n!!! 总超时 480s，强制停止")
        return
    print(f"\n总耗时 {int(time.time()-t0)}s")
    print(f"RunResult: finished={result.finished} passed={result.passed} failed={result.failed} abort_step={result.abort_step}")
    if result.exceptions:
        print("exceptions:", result.exceptions)


if __name__ == "__main__":
    asyncio.run(main())
