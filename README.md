# Saku Skill

An evidence-linked workspace for reviewing research manuscripts.

Saku Skill connects manuscript passages to individual claims, supporting evidence, and review records. Authors work in Markdown, while an agent maintains claim mappings, checks sources, and records revisions through a versioned workflow. A browser-based inspection desk lets reviewers select a passage, examine its claims, and follow the evidence to specific quotations, document pages, code lines, or structured-data locations.

Each registered revision preserves the manuscript and its review history in an immutable snapshot. Personal review notes are stored separately, and standalone website packages support validated version updates and rollback.

The repository includes:

- A reusable manuscript workspace and project-level agent skill.
- A workflow for claim extraction, evidence assessment, and connected-claim checks.
- A visual inspection desk linking passages, claims, and sources.
- Versioned snapshots, integrity checks, and portable deployment packages.

The Python package and CLI are named `papercheck`. The core workflow runs locally with your choice of agent and editor, without a model-service dependency. Python 3.11+ is required; the inspection website uses Node.js 24. Most workflow documentation is currently in Chinese.

## Quick start

```bash
python -m pip install -e .
python -m papercheck scaffold ../my-paper --paper /path/to/manuscript.md
```

Open the new workspace with your agent and follow its `AGENTS.md` and project-level skill. After registering a manuscript revision, run these commands from that workspace:

```bash
python -m papercheck inspector init    # once per workspace
python -m papercheck inspector export
python -m papercheck inspector serve
```

Visit http://127.0.0.1:4178 to inspect the registered passages, claims, and sources. Exporting a page does not perform the underlying scholarly review; the workflow keeps outstanding tasks visible.

## 中文说明

面向 Markdown 论文的 **Agent 工作流脚手架与项目文件夹模板**。

作者日常只编辑 `paper.md`。外部 Agent 按模板完成切分、命题、证据和审核；提交器负责冻结输入、身份与引用校验、数值比较、依赖失效、原子提交和恢复。可以换模型、编辑器和 Harness，不需要内置模型服务。

```text
paper.md
   │  context（冻结输入、旧选择、diff）
   ▼
Agent  ── proposal.json ──> validate ──> commit ──> immutable state
                                              │
                                              └── Postgres / SQLite 索引
```

## 完整干净模板

直接复制 [`template/`](template/README.md)。需要 ZIP 时按下面的导出命令生成；仓库不提交本机 dist 归档。模板包含工具源码、安装声明、工作说明、完整契约和空白论文入口，可独立建立仓库；不包含开发历史、验收报告、缓存、凭证或已运行状态。

复制后在新目录执行 `python -m pip install -e .`，把论文放入 paper.md，再让 Agent 阅读 AGENTS.md。模板使用说明见 [template/README.md](template/README.md)，分发验证见 [docs/template-distribution.md](docs/template-distribution.md)。

维护模板时可执行：

```powershell
python scripts/export_template.py --output template --check
# 新目录导出；已存在的目录或 ZIP 会拒绝覆盖
python scripts/export_template.py --output .tmp/new-template --zip dist/new-template.zip
# 已有模板校验通过后，生成新的 ZIP
python scripts/export_template.py --output template --check --zip dist/verified-template.zip
```

## 建立工作区

```powershell
python -m pip install -e .
python -m papercheck scaffold ../my-paper --paper /path/to/manuscript.md
```

新文件夹包含 `AGENTS.md`、`PROJECT.md`、分阶段 `workflow/` 说明、完整语义指南、`contracts/` 机器契约、`templates/proposal.example.json` 和原始论文。已有文件会拒绝覆盖。让 Agent 进入该文件夹阅读说明，即可运行流程。外围 GitHub 发布和安装 skill 可单独接入。

## 日常使用

项目级 skill 入口：[.agents/skills/papercheck/SKILL.md](.agents/skills/papercheck/SKILL.md)。脚手架自动带入各论文工作区，无需全局安装。可视化检查流程见 [workflow/06-visual-inspection.md](papercheck/template/workflow/06-visual-inspection.md)。

完成登记后，首次运行 `python -m papercheck inspector init`，再运行 `inspector export`、`inspector serve`（均接在 `python -m papercheck` 后）。检查层提供原文 → 命题 → 精确来源、Motion 过渡与默认折叠、独立个人备注。无需 npm 即可启动；需要 Node.js 24。可选 PDF 由使用者提供。只读投影不会把待核查项目变成通过。

用户要求交付时，`inspector package --output site.zip` 生成独立部署包；`inspector package --release-only --output version.zip` 生成服务器更新包。均附 SHA-256，按包内 SOP 暂存、激活和回滚；不打包真实 `.env` 和个人备注。

```bash
# 1. 让 Agent 拿到当前上下文（包含字节偏移、旧容器、未追踪区域、diff）
python -m papercheck context --output context.json

# 2. Agent 根据 context 写 proposal.json（格式见 docs/agent-workflow.md）
#    然后校验并暂存
python -m papercheck propose proposal.json

# 3. 提交（再次校验 base/paper 哈希，原子切换 CURRENT）
python -m papercheck commit --proposal proposal.json

# 4. 验证
python -m papercheck verify
python -m papercheck workflow
```

首次没有历史状态时，也可以直接提交第一份 proposal（`base_state_id` / `base_sha256` 为 `null`）。若只想快速建立机械基线：

```bash
python -m papercheck init          # 可选：自动解析 baseline
python -m papercheck commit --auto # 可选：自动 diff baseline
```

`--auto` 只是辅助，不是工作流的必要条件。

## 命令

| 命令 | 作用 |
|---|---|
| `scaffold <dir> [--paper <file>]` | 建立项目文件夹，复制原文字节，拒绝覆盖已有文件 |
| `workflow [--json]` | 当前缺失来源、命题抽取、修订确认、检查失效和冲突待办 |
| `report` | 从不可变记录重建当前报告 |
| `context` | 输出冻结上下文 JSON：行/字节偏移、旧 selections、旧 untracked、diff、base 哈希 |
| `propose <file>` | 校验 proposal 并写入 `.papercheck/staging/proposal.json` |
| `validate [--proposal <file>]` | 只做确定性校验，不写状态 |
| `commit --proposal <file>` | 提交已校验 proposal；没有 `--proposal` 时使用 staged proposal |
| `commit --auto` | 使用确定性基线（Markdown 解析 + 对齐） |
| `init [--proposal <file>]` | 初始化工作区；默认建立机械基线 |
| `status` / `verify` | 查看当前状态 / 校验 CURRENT 与全部源文件哈希 |
| `recover` | CURRENT 损坏时从 commit log 恢复最近有效状态 |
| `rebuild-index` | 从当前 State 重建查询索引（Postgres 或 SQLite） |
| `show [--state D000001] [--json]` | 查看状态、快照、原始正文与完整语义记录 |

所有命令支持 `--root <dir>`；默认当前目录。

`--root` 放在子命令之前，例如 `python -m papercheck --root ../my-paper workflow`。

`workflow`、`context` 和 `report` 会提示正文尚未提交的变化；历史工作流已完成时，当前正文仍显示 pending。`recorded_status` 保留历史进度。`context --output` 拒绝写入 paper.md 或 .papercheck，提案支持 Windows 常见的 UTF-8 BOM 编码。

## 语义记录

1.1.0 提案的可选 `semantic` 区域支持 Claim、全量位置绑定、Revision Group、Reference、Evidence、Assessment、Quantity、Argument 和 Check。已知 canonical statement 完全一致时复用 Claim；未知条件保守新建并提议替代。REPLACES 只从带出现位置的修订组派生；恢复不会产生反向替代链。

命题或依赖变化会失效旧检查，历史判断仍保留。数值按研究范围、单位和十进制进行比较。缺失全文、未知身份、候选修订和未完成检查会保留待办，不能变成“已通过”。机器只能校验 Agent 提交的记录，实际阅读与学术判断仍由 Agent 负责。

可直接运行离线示例，观察“因果改相关 + 文献缺失”的两次提交和报告：

```powershell
python -m examples.demo --root .tmp/demo-project
```

目标目录必须是新目录。示例数据用于展示工作流，不是实际研究结论。

## 工作区

```text
paper.md                         # Agent/作者编辑的唯一正文
.papercheck/
├── CURRENT                       # 当前已提交 State ID
├── states/D000001/
│   ├── manifest.json             # 哈希、版本、快照 ID
│   └── sources/                  # paper.md、blocks、containers、variants、snapshots、events…
├── staging/                      # 未提交 proposal / 候选状态
├── recovery/commit-log.jsonl     # 提交指针备份
├── reports/D000001.md            # 人可读报告
└── index.sqlite                  # SQLite 回退索引
```

权威数据只在已提交的 `states/Dxxxxxx/sources/` 内。索引可删除重建。

## 数据库

Postgres 通过 Docker 运行；`docker-compose.yml` 使用 `pgvector/pgvector:pg16`，端口 `127.0.0.1:55432`。

```bash
cp .env.example .env
# 填写 POSTGRES_PASSWORD 与 PAPERCHECK_DATABASE_URL
docker compose up -d
```

`PAPERCHECK_DATABASE_URL` 存在时，`commit` 和 `rebuild-index` 自动写 Postgres；否则回退到 `.papercheck/index.sqlite`。数据库只是索引，不是事实来源。

## 测试

```bash
python -m pytest -q
```

需要实践性复验时，运行以下命令。脚本只使用明确标注的合成材料，以真实 CLI 完成中文稿件的六轮提交，并保存全部命令、结果和不可变状态；输出目录必须是新目录。

```powershell
python scripts/practical_check.py --output .tmp/practical-recheck
# 可加 --package-path <独立安装目录>，在源码目录之外验证安装包
```

## 设计文档

- [`docs/agent-workflow.md`](docs/agent-workflow.md)：Agent 工具工作流与 proposal 契约
- [`docs/semantic-contract.md`](docs/semantic-contract.md)：1.1.0 语义提案、身份、修订、证据、数值与失效规则
- [`docs/storage.md`](docs/storage.md)：不可变 State、CURRENT、崩溃恢复
- [`docs/schema.md`](docs/schema.md)：对象、Placement、ID 与覆盖不变量
- [`docs/segmentation.md`](docs/segmentation.md)：Agent 切分与可选自动辅助
- [`docs/replacement.md`](docs/replacement.md)：Revision Group 与多位置替代
- [`docs/canonicalization.md`](docs/canonicalization.md)：Claim 规范表示与 unknown 策略
- [`docs/quantity.md`](docs/quantity.md)：Quantity IR
- [`schema/registry.yaml`](schema/registry.yaml)：枚举、版本与阈值
- [`schema/proposal.schema.json`](schema/proposal.schema.json)：proposal JSON Schema
- [`schema/records.schema.json`](schema/records.schema.json)：已提交记录的机器契约
- [`docs/visual-inspection.md`](docs/visual-inspection.md)：检查层接入、数据边界和验证入口

安装包内自带同一套契约与模板。修改契约后执行 `python scripts/build_contracts.py` 同步发布副本。

## License

This project's original code and documentation are licensed under the [MIT License](LICENSE), Copyright (c) 2026 zcan. Bundled third-party components retain their own licenses; see [THIRD_PARTY_NOTICES.txt](papercheck/inspector_assets/runtime/THIRD_PARTY_NOTICES.txt). The optional PDF renderer uses PyMuPDF, whose licensing terms apply separately. Manuscripts and evidence supplied by users retain their respective rights.
