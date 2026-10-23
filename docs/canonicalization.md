# Claim 规范表示与等价判定

当前工具执行 Agent 提供的 canonical statement 的结构化指纹与保守复用。实体/谓词等词典由 Agent 或领域规则提供；工具没有内置自然语言语义模型。缺字段、unknown 或不完整 Quantity 范围不生成可复用指纹，见 [semantic-contract.md](semantic-contract.md)。

## 1. 两层文本

每个 Claim 至少保存：

- `surface_statement`：人可读的自然语言；
- `canonical_statement`：结构化真值条件；
- `canonicalizer_version`；
- `semantic_fingerprint`；
- `provenance`（从哪些 placement/变体抽取）。

```json
{
  "id": "C000041",
  "surface_statement": "X is associated with Y.",
  "canonical_statement": {
    "subject": {"entity_id": "X"},
    "predicate": "associated_with",
    "object": {"entity_id": "Y"},
    "polarity": "positive",
    "modality": "asserted",
    "causality": "associational",
    "quantifier": null,
    "population": null,
    "time_scope": null,
    "conditions": [],
    "quantity_ids": []
  },
  "canonicalizer_version": "1.0.0",
  "semantic_fingerprint": "sha256:..."
}
```

## 2. 规范化规则

1. 使用版本化的实体/谓词/否定/模态词典，而不是纯字符串比较。
2. Unicode NFC；只规整不改变语义的空白。
3. 数值进入 Quantity IR，使用十进制规范字符串。
4. 无序集合排序；有序论元、前提列表不排序。
5. 使用固定键序、数字表示、空值规则的 canonical JSON。
6. 哈希输入包含 `canonicalizer_version` 与序列化版本。

## 3. unknown 策略

- 任一真值条件字段为 `unknown` 时，**禁止用指纹复用旧 Claim**。
- 保守路径：新建 Claim + `proposed REPLACES`，等待核查。
- 不允许因为 embedding 相似或模型自信而强行合并。
- 规范化失败时记录 `unknown`，不编造确定结构。

## 4. 身份判定

| 变化 | 默认 |
|---|---|
| 排版/空白 | 复用 Claim + 新 Variant |
| 结构完全一致且解析可信 | 复用 Claim，记录等价判断 |
| `causes` → `associated with` | 新 Claim + 候选 REPLACES |
| 量词/否定/总体/条件改变 | 新 Claim |
| `N=3,038` → `N=3,012` | 新 Claim + Quantity Check |
| 无法判断 | 新 Claim + proposed REPLACES |

首次实现不要求 LLM 对所有 paraphrase 绝对稳定；要求**规则覆盖内稳定，覆盖外不静默错误复用**。
