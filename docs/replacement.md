# Replacement 与 Revision Group

本契约已通过 1.1.0 semantic 提案实现，输入临时 ref 的具体格式见 [semantic-contract.md](semantic-contract.md)。Group 使用永久 ID 落盘，REPLACES 从 Group 派生；候选确认/驳回通过 revision_decisions 追加记录。

## 1. 语义

`REPLACES` 只表示：**在某次编辑中，新的命题表达/位置替代了旧命题的某些出现位置。**

它不表示等价、不表示旧命题为假、不传递旧 Evidence/Review。

## 2. Phase 1：文本层 lineage

当前实现用 Agent 声明的 `lineage` 记录文本拆分/合并：

```json
{"lineage": {"type": "split", "from": ["S000041"]}}
{"lineage": {"type": "merge", "from": ["S000052", "S000053"]}}
```

提交器发出 `TEXT_SPLIT` / `TEXT_MERGED`，并保留旧 Container。旧 Container 不再出现在当前 Snapshot 时发出 `REMOVED_FROM_TEXT`。

## 3. Phase 2：Revision Group

Claim 层引入权威的 Revision Group：

```json
{
  "id": "REV000012",
  "operation": "REPLACEMENT",
  "before_snapshot_id": "SNAP000011",
  "after_snapshot_id": "SNAP000012",
  "before": [
    {"claim_id": "C000041", "contexts": [{"placement_id": "PL000101"}]}
  ],
  "after": [
    {"claim_id": "C000052", "contexts": [{"placement_id": "PL000120"}]}
  ],
  "reason": "因果断言改为相关性断言",
  "status": "confirmed",
  "run_id": "RUN000032"
}
```

- `contexts` 是数组，使用 `placement_id` 精确到出现位置；不再使用单一 `context`。
- 1→N 用一条 Group 的多个 `after[].contexts`；N→1 用多个 `before[]`。
- 空 `after` 表示删除，不是生成空命题。
- 回退使用 `RESTORED_IN_TEXT`，不建立反向 `REPLACES`。

## 4. Relation 投影

`relations.jsonl` 中的 `REPLACES` 边从 Revision Group 派生：

```json
{"id":"L000003","src":"C000052","type":"REPLACES","dst":"C000041","revision_id":"REV000012","status":"confirmed"}
```

- 不得独立编辑派生边。
- `replacement` flag 从已确认的入边/Group 派生；`proposed` 只显示为候选，不进入确定性推理。

## 5. 合法性

- `before` contexts 必须存在于 `before_snapshot_id`；`after` 同理。
- `REPLACES` 的 src/dst 必须对应 Group 的 after/before Claim。
- 同一 Snapshot 同一位置不能互相矛盾地绑定两个唯一 Claim，除非显式建模共现。
- 旧 Claim、旧 Evidence、旧 Review 不删除；新 Claim 不自动继承 `confirmed`。
