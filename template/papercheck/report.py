from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from .state import StateView
from .util import atomic_write_text
from .workflow import current_workflow

UNTRACKED_LABELS = {
    "between_selections": "结构性间隔",
    "deferred:math_block": "数学块（已保留原文）",
    "deferred:code_block": "代码块（已保留原文）",
    "deferred:table": "表格（已保留原文，待 Agent 提取）",
    "deferred:html_block": "HTML 块（已保留原文）",
}


TASK_LIST_LIMIT = 20


def _markup_only(raw: bytes) -> bool:
    """Whitespace or a short run of Markdown markers (#, >, list bullets) carries no prose."""
    return len(raw) <= 16 and re.fullmatch(rb"[\s#>*+\-\d.]*", raw) is not None


def _preview(raw: bytes, width: int = 40) -> str:
    text = " ".join(raw.decode("utf-8", "replace").split()).replace("|", "\\|")
    return text if len(text) <= width else text[:width] + "…"


def _subject(check, claims, quantities) -> str:
    names = [f"{quantities[q]['metric_id']}「{quantities[q].get('source_expression', '')}」"
             for q in check.get("quantity_ids", []) if q in quantities]
    if names and check["kind"] == "quantity_consistency":
        return " [" + " ↔ ".join(names) + "]"
    if not names and check.get("claim_ids"):
        statement = claims.get(check["claim_ids"][0], {}).get("surface_statement", "")
        return f" [{_preview(statement.encode(), 60)}]" if statement else ""
    return ""


def _task_subject(task, claims) -> str:
    claim = claims.get(task["target"])
    return f"（{_preview(claim['surface_statement'].encode(), 60)}）" if claim else ""


def write_report(repo, state: StateView, summary: dict[str, Any]) -> Path:
    snapshot = state.snapshot
    lines = [
        f"# 本次论文修改检查：{state.state_id}",
        "",
        f"- 文稿：`paper.md`",
        f"- 输入哈希：`{state.manifest.get('input', {}).get('sha256')}`",
        f"- 父状态：`{state.manifest.get('parent_state_id')}`",
        f"- 快照：`{snapshot.get('id')}`",
        "",
        "## 已自动处理",
        "",
        f"- 文本块：{summary.get('blocks_total', 0)}；容器：{summary.get('containers_total', 0)}；变体：{summary.get('variants_total', 0)}",
        f"- 新增块：{summary.get('blocks_added', 0)}；新增容器：{summary.get('containers_added', 0)}；新增变体：{summary.get('variants_added', 0)}",
        f"- 移动：块 {summary.get('block_moves', 0)}、容器 {summary.get('moved', 0)}；恢复：{summary.get('restored', 0)}；删除：{summary.get('removed', 0)}；拆分：{summary.get('splits', 0)}；合并：{summary.get('merges', 0)}",
        "",
    ]
    untracked = snapshot.get("untracked_blocks", [])
    paper = state.paper_bytes
    # Whitespace between selections is bookkeeping; listing hundreds of them hides real gaps.
    blank = [r for r in untracked if _markup_only(paper[r["start_byte"]:r["end_byte"]])]
    substantive = [r for r in untracked if not _markup_only(paper[r["start_byte"]:r["end_byte"]])]
    if untracked:
        lines.extend(["## 未追踪区域", ""])
        if blank:
            lines.extend([f"- 空白与 Markdown 标记：{len(blank)} 处，共 {sum(r['end_byte'] - r['start_byte'] for r in blank)} 字节（不含文字）。", ""])
        if substantive:
            lines.extend(["| 字节范围 | 原因 | 原文开头 |", "|---|---|---|"])
            for row in substantive:
                reason = row.get("reason", "")
                lines.append(f"| {row.get('start_byte')}–{row.get('end_byte')} | {UNTRACKED_LABELS.get(reason, reason)} | "
                             f"{_preview(paper[row['start_byte']:row['end_byte']])} |")
            lines.append("")
    workflow = current_workflow(repo, state)
    if workflow["working_copy_changed"]:
        lines.extend(["## 工作副本尚待处理", "", "当前 paper.md 与本报告快照不同或已缺失；以下检查对应已提交历史，不能视为当前正文已通过。", ""])
    lines.extend(["## 检查进度", "", f"- 工作流状态：**{workflow['status']}**",
        f"- 当前命题：{len(snapshot.get('claim_ids', []))}；复用检查：{summary.get('checks_reused', 0)}；待办：{len(workflow['tasks'])}",
        "- 正文和结构校验成功不等于学术结论已验证。", ""])
    claims = state.by_id("claims")
    revisions = [r for r in state.revisions if r.get("state_id") == state.state_id]
    if revisions:
        lines.extend(["## 命题修订", ""])
        for revision in revisions:
            before = "；".join(claims[r["claim_id"]]["surface_statement"] for r in revision["before"]) or "无"
            after = "；".join(claims[r["claim_id"]]["surface_statement"] for r in revision["after"]) or "删除"
            lines.extend([f"- {revision['operation']} ({revision['status']})：{before} → {after}",
                          f"  理由：{revision['reason']}"])
        lines.append("")
    current_checks = [c for c in state.checks if c["id"] in snapshot.get("check_ids", [])]
    if current_checks:
        quantities = state.by_id("quantities")
        lines.extend(["## 本轮有效检查", ""])
        tally = Counter((c["kind"], c["outcome"]) for c in current_checks)
        lines.append("- 汇总：" + "；".join(f"{kind} / {outcome} × {count}" for (kind, outcome), count in sorted(tally.items())))
        lines.append("")
        # Problems first, then passes, so a long ledger does not bury a conflict.
        for check in sorted(current_checks, key=lambda c: (c["outcome"] == "pass", c["id"])):
            lines.append(f"- {check['id']} {check['kind']} / **{check['outcome']}**{_subject(check, claims, quantities)}："
                         f"{check['reason']}（方法：{check['method']}）")
        lines.append("")
    if workflow["tasks"]:
        lines.extend(["## 需要关注与尚待核实", ""])
        groups = {}
        for task in workflow["tasks"]:
            groups.setdefault((task["type"], task["status"]), []).append(task)
        lines.append("- 汇总：" + "；".join(f"{kind} / {status} × {len(items)}" for (kind, status), items in groups.items()))
        lines.append("")
        for (kind, status), items in sorted(groups.items(), key=lambda item: item[0][1] != "action_required"):
            shown = items if len(items) <= TASK_LIST_LIMIT else items[:TASK_LIST_LIMIT]
            lines.extend(f"- [{task['status']}] {task['type']} / {task['target']}{_task_subject(task, claims)}：{task['reason']}"
                         for task in shown)
            if len(items) > len(shown):
                lines.append(f"- …… 另有 {len(items) - len(shown)} 项 {kind}；完整列表见 `workflow --json`。")
        lines.append("")
    if state.evidence:
        lines.extend(["## 证据出处", ""])
        active_eids = {eid for c in current_checks for eid in c.get("evidence_ids", [])}
        refs = state.by_id("references")
        for evidence in state.evidence:
            if evidence["id"] in active_eids:
                reference = refs[evidence["reference_id"]]
                lines.append(f"- {reference['title']} / {evidence['source_access']} / {evidence['locator']}：{evidence['quote']}")
        lines.append("")
    invalidated = [r for r in state.invalidations if r["snapshot_id"] == snapshot["id"]]
    if invalidated:
        lines.extend(["## 已失效的旧检查", ""])
        lines.extend(f"- {r['check_id']}：{r['reason']}；历史结果仍保留。" for r in invalidated)
        lines.append("")
    lines.extend(["## 审计", "", f"- 快照：{snapshot['id']}；输入：{snapshot['source_hash']}",
                  "- 语义和证据判断由 Agent 提交；工具执行结构校验、数值比较和状态管理。", ""])
    path = repo.reports / f"{state.state_id}.md"
    atomic_write_text(path, "\n".join(lines))
    return path
