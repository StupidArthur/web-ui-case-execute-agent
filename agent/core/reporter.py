"""测试报告生成。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from agent.core.models import Case, OptimizationSignal, RunResult, StepRecord


def _sanitize_filename(name: str) -> str:
    """将字符串转为可用作文件名的形式。"""
    name = re.sub(r'[\\/:*?"<>>|]', "_", name)
    return name.strip()


def write_report(
    case: Case,
    records: list[StepRecord],
    optimize_signals: list[OptimizationSignal],
    exceptions: list[str],
    abort_step: int | None,
    finished: bool,
) -> str:
    """生成 JSON 测试报告并落盘，返回报告文件路径。"""
    test_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    step_records_json = []
    for r in records:
        step_records_json.append({
            "步骤": r.step,
            "操作": r.operation,
            "实际结果": r.actual_result,
            "状态": r.status,
            "异常说明": r.error,
        })

    optimize_json = []
    for sig in optimize_signals:
        optimize_json.append({
            "步骤编号": str(sig.step_index),
            "问题类型": sig.issue_type,
            "问题描述": sig.description,
            "优化建议": sig.suggestion,
            "推荐改写步骤": sig.rewritten_step,
        })

    optimized_case = "无"
    if len(optimize_signals) >= 3:
        optimized_case = _generate_optimized_case(case, optimize_signals)

    report = {
        "测试时间": test_time,
        "测试环境": case.start_url,
        "用例名称": case.name,
        "步骤记录": step_records_json,
        "关键结果": {"备注": ""},
        "异常汇总": exceptions,
        "用例优化分析": optimize_json,
        "优化后建议用例": optimized_case,
    }

    safe_name = _sanitize_filename(case.name) or "unnamed"
    filename = f"test_record_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path = Path.cwd() / filename

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return str(report_path)


def _generate_optimized_case(case: Case, signals: list[OptimizationSignal]) -> str:
    """根据优化信号生成优化后用例文本（简化版）。"""
    lines = [
        f"测试用例名称：{case.name}",
        f"测试目的：{case.purpose}",
        f"起始 URL：{case.start_url}",
        "",
        "测试步骤：",
    ]
    for record in signals:
        lines.append(f"步骤{record.step_index}: ({record.issue_type}) {record.rewritten_step or '建议细化描述'}")
    return "\n".join(lines)
