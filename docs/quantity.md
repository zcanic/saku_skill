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
  "derivation": null
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

## 5. 边界

- 训练集 N 与测试集 N 不同通常不构成矛盾。
- 摘要与方法中的同一指标，只有 scope 一致时才能报 conflict。
- LLM 提出推导关系；确定性执行器负责算术与统计重算。
