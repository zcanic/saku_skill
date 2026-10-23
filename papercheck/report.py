from __future__ import annotations

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
    if untracked:
        lines.extend(["## 未追踪区域", "", "| 字节范围 | 原因 |", "|---|---|"])
        for row in untracked:
            reason = row.get("reason", "")
            lines.append(
                f"| {row.get('start_byte')}–{row.get('end_byte')} | {UNTRACKED_LABELS.get(reason, reason)} |"
            )
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
        lines.extend(["## 本轮有效检查", ""])
        for check in current_checks:
            lines.append(f"- {check['kind']} / **{check['outcome']}**：{check['reason']}（方法：{check['method']}）")
        lines.append("")
    if workflow["tasks"]:
        lines.extend(["## 需要关注与尚待核实", ""])
        lines.extend(f"- [{task['status']}] {task['type']} / {task['target']}：{task['reason']}" for task in workflow["tasks"])
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
