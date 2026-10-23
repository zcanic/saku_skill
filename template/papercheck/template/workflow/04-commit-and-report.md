# 校验、提交与报告

执行 validate --proposal。结构性错误由 Agent 修正；语义不确定性保留 pending/proposed，不靠编造确定值通过校验。

commit 在锁内再次检查正文和 base 哈希。退出码 3 表示提交期间正文又变；校验时发现旧哈希返回 2，同样应重读 context。成功后 verify，再看 workflow 和生成的报告。

给作者报告本轮文本变化、替代命题与原因、证据定位、数值冲突、失效检查和待办。即使缺文献，也继续可完成的其他工作；不能把未检查项目写为通过。

随后按 `06-visual-inspection.md` 导出当前登记版本的可视化核读层。它是阅读入口，不改变 workflow 的完成状态；下一轮修改仍从新 context 开始。
