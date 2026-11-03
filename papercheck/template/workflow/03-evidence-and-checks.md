# 证据与复核

Reference 区分全文、摘要、片段、元数据和不可获取。只有实际读取的材料才可登记可定位 quote；full support 需要全文 Evidence。记录共享来源、数据集和研究标识，避免把相同数据重复当成独立证据。

数值先抽取 Quantity IR，填写指标、总体、数据集版本、筛选条件、时间和单位。未知范围写 unknown 或省略以保留不足状态；不相同范围的 N 不能直接判冲突。用十进制字符串表达数值，百分比注明 percent_base。

## 数值自洽：重复与推导

- 同一数字在摘要、正文、表格、结论重复出现时，用同一 metric_id 和相同范围字段各登记一次；提交器两两比较（quantity_consistency）。
- 由别的数字算出的数字写 `derivation`：样本拆分之和（sum）、消融差值（difference）、按样本量加权的合并指标（weighted_mean）、占比（share + scale "100"）、两模型平均（mean）。提交器按书写位数考虑舍入后重算（quantity_derivation）。conflict 就是要给作者看的具体错误。
- 算式必须来自论文自己的定义（例如“∆MAE 是消融 MAE 减去完整模型 MAE”）。看不出算式时不要猜，留作待办或在报告中提问。
- 所有推导都通过只说明“稿件内部算术一致”，不说明原始实验输出正确；没有原始产物时 evidence 审核仍为待办。

检查依赖变更后的受影响命题与论证。Agent 可以提供 checks 和 assessments；工具负责数值比较、推导重算、来源/引用校验、历史保留和失效传播，不替 Agent 执行学术判断。

输出：有方法与理由的 checks、可定位 Evidence/Assessment、尚缺来源与未完成审核。
