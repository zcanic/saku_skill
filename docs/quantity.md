# Quantity IR

1.1.0 已支持 Agent 抽取与确定性比较。输入使用 ref/segment/claim；提交器分配 ID、生成 locator 和 claim_ids 数组。以下示例描述数据含义，准确机器契约以 schemas/records.schema.json 与 [semantic-contract.md](semantic-contract.md) 为准。

## 1. 为什么需要中间表示

`N = 3,038` 可能出现在摘要、方法、表格和讨论中，也可能指训练集、清洗后样本或另一批次。只比较句子会导致大量误报/漏报。

## 2. 最小 Schema

```json
{
  "id": "Q000041",
  "claim_ids": ["C000052"],
  "metric_id": "reference_sample_size",
  "name": "sample_size",
  "value": {"type": "point", "value_decimal": "3038"},
  "operator": "=",
  "unit": "work",
  "population": "reference_population",
  "dataset_id": "DATASET000001",
  "dataset_version": "v1",
  "sample_filter": "valid_rating_and_primary_page",
  "time_scope": null,
  "precision": "exact_integer",
  "approximation": "exact",
  "source_expression": "N = 3,038",
  "locator": {
    "snapshot_id": "SNAP000012",
    "placement_id": "PL000120",
    "container_id": "S000024",
    "variant_id": "V000041"
  },
  "extraction_status": "confirmed",
  "derivation": {"op": "sum", "inputs": ["n_pre2020", "n_oof", "n_undated"]}
}
```

## 3. value 判别式联合

| type | 字段 |
|---|---|
| `point` | `value_decimal` |
| `range` | `value_lower`, `value_upper`, 可选 `inclusive` |
| `interval` | `value_lower`, `value_upper`, `confidence` |

百分比额外记录 `percent_base`；单位换算必须显式、可复现。

## 4. 可比性与核查

1. 抽取 Quantity 候选，保留原始表达与位置。
2. 标准化数值、单位、比较符。
3. 按 `metric_id + dataset_version + population + sample_filter + time_scope` 判断是否可比。
4. 可比较时执行精确值、单位换算、舍入容差、区间包含或公式重算。
5. 输出 `consistent | conflict | incomparable | insufficient_context | pending`。
6. 数值变化只失效相关 Claim/Assessment/Argument/Check，不全文重跑。

`claim_ids` 是数组，允许为空：表格中的数值不一定绑定单一 Claim。当前输入可用 claim 指定一个关联命题。

## 5. 推导重算（derivation）

同一指标多处出现由 `quantity_consistency` 比较；由其他数字算出的数字用 `derivation` 声明，提交器以十进制区间重算并生成 `quantity_derivation` 检查。Agent 负责写出算式，工具只做算术，不猜测关系。

| op | 含义 | 额外字段 |
|---|---|---|
| `sum` | inputs 相加 | |
| `difference` | 第一个减去其余 | |
| `product` | 连乘 | |
| `ratio` | 恰好两个：前者 / 后者 | |
| `mean` | 简单平均 | |
| `weighted_mean` | 加权平均 | `weights`，与 inputs 一一对应 |
| `share` | sum(inputs) / sum(of) | `of`；可配 `scale: "100"` 得百分数 |

所有算子都可配 `scale`。inputs/weights/of 写本轮 quantity ref 或既有 Q ID，必须是当前快照的 point 数值。

舍入规则：小数按书写位数取半个末位（`11.158` → ±0.0005），整数视为精确计数；`tolerance_decimal` 追加容差，`precision: "exact"` 去掉舍入。工具在全部输入的舍入区间顶点上求值，得到可达区间，再与目标值的舍入区间比较：相交为 pass，不相交为 conflict（action_required）。因此 `12.729 − 11.158 = 1.571` 与所写 `1.572` 判为一致，而 `657` 写成 `675` 会被拦截。输入未确认为 pending，输入不在当前快照为 insufficient_context，分母可能为零为 error。

推导检查与一致性检查一样在每次提交时按当前数值重算，旧结果写入 Invalidation 保留历史。

## 6. 边界

- 训练集 N 与测试集 N 不同通常不构成矛盾。
- 摘要与方法中的同一指标，只有 scope 一致时才能报 conflict。
- LLM 提出推导关系；确定性执行器负责算术与统计重算。
