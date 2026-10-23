# papercheck 论文检查模板

这是一份可以复制、建立 Git 仓库或作为 GitHub Template 使用的完整工作区。工具源码和流程说明都在此目录内。

Python 要求：3.11 或更高。Agent 阅读 AGENTS.md 和 workflow；作者日常只修改 paper.md。

## 开始使用

在此目录执行：

```powershell
python -m pip install -e .
python -m papercheck --version
```

将论文原文放入 paper.md，授权使用的文献、数据和计算输出放入 references/。空白 paper.md 仅为入口，放入正文后再开始检查。

让 Agent 执行：

```powershell
python -m papercheck context --output context.json
# Agent 阅读正文、历史记录和材料，生成 proposal.json
python -m papercheck validate --proposal proposal.json
python -m papercheck propose proposal.json
python -m papercheck commit
python -m papercheck verify
python -m papercheck workflow
```

无需模型 API 配置或数据库服务，默认使用 SQLite。实际阅读、语义判断和资料获取由你选择的 Agent 完成。

## 目录

```text
AGENTS.md                   Agent 工作规则
PROJECT.md                  项目职责与日常流程
paper.md                    论文入口，初始为空
references/                 授权材料，初始为空
workflow/                   分阶段说明和完整语义契约
contracts/                  可直接阅读的机器契约
templates/                  提案格式示例
papercheck/                 完整工具源码和包内资源
pyproject.toml              安装与依赖声明
TEMPLATE-MANIFEST.json      初始模板的文件校验清单
```

templates/proposal.example.json 只说明字段，不能直接当作自己论文的提案。所有哈希、范围、绑定和判断都应由 Agent 根据实际上下文重新生成。

## 日常操作

项目 skill 在 `.agents/skills/papercheck/SKILL.md`，随工作区携带。可视化流程见 `workflow/06-visual-inspection.md`。登记后首次运行：

```powershell
python -m papercheck inspector init
python -m papercheck inspector export
python -m papercheck inspector serve
```

Node.js 24 运行已有网页，无需 npm；原页 PDF 预览另需 Python/PyMuPDF。默认 http://127.0.0.1:4178。正文在左，选择段落后核读右侧命题和精确证据，默认折叠。未拆分内容和待办保留；个人备注不改变正式核查。每次改稿须先登记提交，再 export 和刷新。

源材料只从 `inspector/config.json` 中允许的目录按已登记证据复制。完整交付包：`inspector package --output site.zip`；更新包：`inspector package --release-only --output version.zip`。均接在 `python -m papercheck` 后，按包内 UPDATE_SOP.md 操作。交付需确认论文与材料分发权限；模板本身不含任何论文或证据数据。

- workflow：查看待办；正文再次变化时自动提示尚未检查。
- report：从已提交记录重建报告，位置为 .papercheck/reports/。
- show --json：查看正文、当前命题与全部记录。
- show --state D000001 --json：回溯历史正文和命题。
- rebuild-index：重建派生索引。
- verify / recover：校验状态或恢复 CURRENT。

命令默认操作当前目录。操作其他目录时将 --root 放在子命令之前，例如 python -m papercheck --root ../another-paper workflow。

## 使用规则

本项目自有代码与文档采用 MIT License，见 LICENSE；第三方组件保留各自许可证。检查层运行包携带自己的 LICENSE 和 THIRD_PARTY_NOTICES.txt。用户论文与证据材料的权利由原权利人保留，不因使用本模板而改变。

作者无需维护 JSON、ID 或数据库；这些工作由 Agent 经受控工具完成。Agent 默认不改论文正文。语义不确定、材料缺失和检查失效必须保留待办，不能写成已通过。

运行后才生成 .papercheck/。不可变 states 和恢复日志可以纳入 Git，索引、staging 和临时提案已配置忽略。用户材料是否提交由用户决定。

TEMPLATE-MANIFEST.json 描述分发时的初始文件；放入论文或修改说明后，模板哈希变化是正常的。实际论文历史的完整性由 verify 检查。

## 可选 Postgres

需要 Postgres 索引时安装 python -m pip install -e ".[postgres]"，再在环境或本目录 .env 中配置 PAPERCHECK_DATABASE_URL。数据库由使用者提供；默认 SQLite 流程无需此步骤。
