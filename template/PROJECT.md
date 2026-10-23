# 论文检查工作区

这是 Agent 使用的文件夹模板。把论文放入 `paper.md`，将授权使用的材料放在 `references/`。

作者负责论文内容；Agent 阅读 `AGENTS.md`，按 workflow 完成追踪、命题登记、证据评估和报告。

```text
paper.md → context → Agent proposal → validate → commit → verify → workflow/report → inspector export → 人工核读
```

```powershell
python -m papercheck context --output context.json
# Agent 生成 proposal.json；不直接提交示例占位符
python -m papercheck validate --proposal proposal.json
python -m papercheck commit --proposal proposal.json
python -m papercheck verify
python -m papercheck workflow
```

首次可用 `init` 建立纯文本基线；这不代表命题或证据已经检查。无需服务端或模型 API 配置。未设置数据库连接时使用 SQLite。

项目内 `.agents/skills/papercheck/SKILL.md` 是 Agent 入口。可视化检查流程见 `workflow/06-visual-inspection.md`；默认创建 `inspector/`，保留原文选择、命题折叠、精确来源预览与独立个人备注。首次执行 `inspector init` 后，每轮提交再 `inspector export`，`inspector serve` 本地查看。导出和个人勾选均不会提升正式核验状态。

`show --json` 可读取当前所有记录；`show --state D000001 --json` 可回溯旧状态与原始正文。索引可用 `rebuild-index` 重建，当前报告可用 `report` 重建。

`workflow/` 是给 Agent 的步骤说明；`workflow/05-semantic-contract.md` 提供完整语义契约；`contracts/` 是本工作区的机器 Schema；`templates/` 是提案示例。无需回到工具源码查字段。领域规则可以补充到这些文档，业务判断不应变成作者维护 JSON 的负担。
