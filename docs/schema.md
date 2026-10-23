# 对象与 Schema

当前协议为 1.1.0。机器契约位于包内 schemas，仓库 schema 是发布副本；具体语义字段与输入方式见 [semantic-contract.md](semantic-contract.md)。kind 等领域描述允许扩展；偏移、引用、来源访问级别、修订与语义结构必须通过校验。

## 1. 核心对象

| 对象 | 作用 | 关键字段 |
|---|---|---|
| State | 一次完整提交 | `state_id`, `parent_state_id`, `input`, `snapshot_id`, `file_hashes` |
| Document | 论文身份 | `id`, `created_state_id` |
| Block | 段落/标题/列表项等结构身份 | `id`, `kind`, `order`, `last_seen_state_id` |
| Container | 可跨版本追踪的文本单元 | `id`, `kind`, `parent_block_id`, `created_state_id` |
| Variant | 不可变的具体文字 | `id`, `container_id`, `first_seen_state_id`, `raw_text`, `normalized_text`, `content_sha256` |
| Placement | 某 Snapshot 中的一次出现 | `placement_id`, `container_id`, `variant_id`, `order`, `source_ranges` |
| Snapshot | 当前稿的完整选择 | `id`, `state_id`, `document_id`, `source_hash`, `selections`, `untracked_blocks` |
| Event | 审计记录 | `id`, `type`, `run_id`, `state_id`, `before`, `after`, `reason` |

## 2. Placement 是出现身份

同一 Variant 可能在文稿中出现多次。**每次出现必须有独立 `placement_id`。**

```json
{
  "placement_id": "PL000012",
  "container_id": "S000004",
  "variant_id": "V000011",
  "order": 30,
  "source_ranges": [{"start_byte": 120, "end_byte": 184}]
}
```

- `source_ranges` 是 UTF-8 字节偏移，左闭右开。
- 允许一个 placement 有多个非连续 range。
- Snapshot 内 `placement_id` 唯一；封面/正文重复句应使用不同 Container，而不是复用同一 Container 两次。

## 3. 覆盖不变量

对当前 Snapshot：

```text
所有 placement.source_ranges ∪ 所有 untracked_blocks = [0, paper_size)
且任意两者不重叠
```

- 无法抽取的公式/代码/表格/HTML 用 `untracked_blocks` 明确登记，保留原文。
- 不允许多个 placement 指向同一 Container（同一 Snapshot 内）。
- Variant 的 `source_range` 是 **first_seen** 定位；当前位置看 Snapshot placement。

## 4. Block

- 只记录可追踪的文本块（paragraph/heading/list_item/blockquote）。
- 代码块、数学块、表格、HTML 块进入 `untracked_blocks`，原因形如 `deferred:table`。
- 新块由 Agent 的 `block_ref` 分组；复用旧块用 `block_id`。

## 5. 事件类型

`BLOCK_CREATED`, `BLOCK_MOVED`, `CONTAINER_CREATED`, `VARIANT_CREATED`, `CONTAINER_MOVED`, `TEXT_SPLIT`, `TEXT_MERGED`, `REMOVED_FROM_TEXT`, `RESTORED_IN_TEXT`, `CLAIM_CREATED`, `CLAIM_REPLACED`, `CLAIM_REVISION`, `CHECK_INVALIDATED`, `SNAPSHOT_COMMITTED`。STATE_RECOVERED 为保留类型；恢复操作不修改已提交 State 的事件文件。

`REMOVED_FROM_TEXT` 是事件，不是 Claim 关系，也不生成空命题。

## 6. 枚举与版本

完整枚举、ID 前缀、阈值在 [`schema/registry.yaml`](../schema/registry.yaml)。Schema 版本是读写协议版本，不等于论文版本或模型版本。新增必填字段、改变枚举语义、改变 ID 语法或切分规则时必须显式迁移。

## 7. 非当前快照

一个 State 内保留历史 Snapshot 供审计。校验只对 `manifest.snapshot_id` 指向的当前快照要求：

- `state_id` 与 `source_hash` 匹配；
- 覆盖当前 `paper.md` 的全部字节。

历史快照保留其原始 `state_id`/`source_hash`，不得用当前正文尺寸重新解释。

## 8. 语义与运行记录

Claim C、Binding BD、Revision REV、Reference REF、Evidence E、Assessment A、Quantity Q、Argument ARG、Check CHK、Review RV、Invalidation INV、Run RUN 均由提交器分配六位 ID。关系与出现绑定分开保存，多位置命题依赖 Binding 与 Revision contexts。

多 range Variant 的 raw_text 使用各源区间 UTF-8 解码后以换行连接；单个 source_range 是 first_seen 首区间，完整区间在 source_ranges，当前实际位置以 Snapshot 为准。
