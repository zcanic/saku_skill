# 可视化检查层（0.3.0）

## 接入位置

`papercheck/template/.agents/skills/papercheck/SKILL.md` 是工厂 skill，根目录同路径为开发仓库入口。`scaffold` 自动把 skill 和 `workflow/06-visual-inspection.md` 带进论文工作区；完整分发模板也包含这些文件。没有写入用户全局技能目录。

流程：冻结 context → Agent 拆分全部目标陈述/核读精确来源 → validate → commit → verify → workflow/report → inspector export → 人工可视化核读。正文修改后重新走这条链。导出只读投影不会提交语义判断或清除待办。

## 数据与状态

- 命题出现位置直接采用当前快照 Binding ID；原文按 UTF-8 范围恢复，多范围以账本规则的换行拼接。
- 所有当前正文选择与非空 untracked 内容可见；无绑定正文和缺失来源不隐藏。工作流完成度单独显示。
- 当前状态仅依赖快照有效检查及其 Assessment；历史结果单列，历史证据也独立展示。`fail/error` 与 `conflict` 区分，未登记的判断不推导为通过。
- 正文、账本与来源副本固定在同一 release；清单记录 SHA-256。验证器核对文件、版本、原文字节与投影计数。它不代替科学事实核验。
- 人工备注保存在独立 reviews，按 release/论文哈希/Binding 隔离，不自动继承或写回账本。
- 来源从显式允许目录按证据定位选择；不执行研究代码或 SQL，不自动下载网络文件。口令模式脱敏仅作用于副本并保留原始哈希；分发前仍须审查隐私和材料权限。
- PDF 可选，由 Agent/作者确认内容一致后提供；哈希只验证文件完整性。

## 软件布局与维护

`papercheck/inspector.py`：导出与 CLI 生命周期。`papercheck/inspector_assets/frontend`：React/Radix/Motion 源码及锁文件。`runtime`：独立 Node 服务、预构建网页、Docker、版本 ZIP 管理和 SOP。`scripts/build_inspector_assets.py` 构建网页、收集许可、生成显式 ASSET-MANIFEST；不复制依赖目录、论文数据和个人备注。

UI 保留稳定纸面坐标的单一段落选择框、可中断平滑滚动、折叠证据和 reduced-motion。`serve` 默认仅监听本机；独立部署默认要求口令，HTTPS 反代需单独配置。

维护 UI：先重建资产，再跑测试，最后更新干净模板。`scripts/refresh_template.py` 只刷新通过初始清单校验的模板，含论文或任何用户修改时拒绝覆盖，并保存旧模板 ZIP。`scripts/export_template.py` 保留新目录/新归档不覆盖规则。

## 验证入口

运行 `python -m pytest`；新增 `tests/test_inspector.py` 使用合成论文，覆盖当前/历史核查、部分支持与反证、未登记改稿拒绝导出、空命题/表格保留、字节拼接、来源权限、口令副本脱敏、完整与数据包、CLI 脚手架、Node 来源预览/备注/失效/切换/回滚。构建与安装包、完整模板同步也需要检查；不把原动漫论文材料放入通用测试。

正式服务器及公网反代需要在目标环境另做验收；本地测试不宣称已完成服务器部署。

本轮结果：全量 92 项测试通过；两个项目级 skill 均通过结构验证；前端 TypeScript/Vite 构建通过。分别从开发源码、干净模板构建 wheel，安装到独立目录后，在开发仓库以外执行脚手架 → init → inspector init/export/package，均成功；确认导入实际来自安装目录而非源码。完整模板逐文件校验与确定性 ZIP 测试通过。没有安装全局 skill、推送 Git 或部署公网。
