<!-- 此完整模板自带工具源码。首次运行前读 README.md 并执行 python -m pip install -e . -->

# 论文检查项目：Agent 工作说明

用户日常只编辑 `paper.md`；你负责维护检查流程。先读 `PROJECT.md` 和 `workflow/`。

- 在项目根目录执行 `python -m papercheck context --output context.json`。正文、上下文哈希和字节偏移必须来自这次冻结输入。
- 阅读正文、历史命题、证据与待办，再准备 proposal；`templates/proposal.example.json` 说明字段。不要用自动字符串相似度决定学术语义。
- 用 segment `ref` 绑定本轮位置，用临时对象 `ref` 表示新对象；永久 ID 只由提交器分配。
- 等价改写保留已知 canonical statement。含未知条件时新建 Claim，替代关系标 proposed。因果、数值、量词或限定改变需要新命题。
- `semantic.bindings` 描述本轮全部命题出现位置。无命题的段落用 `non_claim_segments` 说明。表格/代码/公式可暂列 untracked，并保留原始字节。
- 缺少原文不能编造 quote、页码或已通过的审核。元数据来源只登记 Reference；取得可定位正文后再登记 Evidence。
- 先 validate，再 commit，再 verify 和 workflow。正文或 CURRENT 改变后重新获取上下文；不得强行覆盖作者新文字。
- `.papercheck/states/` 和数据库禁止直接编辑。源状态不可变，索引与报告可以重建。
- 默认不修改 `paper.md`。建议修改用普通语言给作者，只有获得正文修改授权后才能应用。
- 阶段性输出应说明已完成、发现问题和剩余待核查；workflow pending 不能写成整篇通过。
- 完成本轮登记后，按 `workflow/06-visual-inspection.md` 导出只读检查层；页面备注与正式核查分开。未登记的新稿不得直接覆盖旧版可视化数据。

命令来自安装好的 papercheck 包；不绑定模型厂商、Agent Harness 或编辑器。项目内 skill 位于 `.agents/skills/papercheck/SKILL.md`；无需全局安装。部署 GitHub 可独立处理。
