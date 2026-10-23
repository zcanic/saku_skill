"""Project the committed workflow onto the current working copy without mutating it."""
from copy import deepcopy


def current_workflow(repo, state):
    recorded = state.snapshot.get("workflow", {"status": "pending", "tasks": [], "note": "legacy text-only snapshot"})
    workflow = deepcopy(recorded)
    working = repo.working_copy_status(state)
    workflow["recorded_status"] = recorded["status"]
    workflow["working_copy_changed"] = working["changed"]
    workflow["working_copy_exists"] = working["exists"]
    if working["changed"]:
        workflow["status"] = "pending"
        workflow["tasks"].insert(0, {"type": "update_snapshot", "target": "paper.md", "status": "pending",
            "reason": "正文已变化，尚未检查；重新获取 context 并提交提案。" if working["exists"] else "paper.md 缺失；先恢复工作副本再继续检查。"})
    return workflow
