# Agent 工作流契约

可视化人工核读是提交后的正式工作流阶段，见 [06-visual-inspection.md](../papercheck/template/workflow/06-visual-inspection.md)。项目 skill 位于 `.agents/skills/papercheck/SKILL.md`，脚手架与完整模板均携带；不需要全局安装。检查层只消费已验证的 CURRENT，单独存储人工备注，不写回源状态或自动结束待办。

本文件是 Agent 使用 `papercheck` 的规范。**Agent 负责语义与切分，提交器负责数据完整性。**

1.1.0 的语义接口与文件夹模板见 [semantic-contract.md](semantic-contract.md)。本文的 1.0.0 例子仍适用于纯文本提案；包含 semantic 的提案使用 1.1.0。当前定位是可复用工作流脚手架。

## 1. 分工

| 任务 | 执行者 |
|---|---|
| 阅读 `paper.md`，决定句子/容器边界 | Agent |
| 判断旧容器是否复用、文字是否只是新变体 | Agent |
| 判断移动、拆分、合并、恢复、删除 | Agent |
| 标记表格/公式/代码等未追踪区域 | Agent |
| 校验字节覆盖、引用、ID、哈希、base | 提交器 |
| 分配永久 ID、写 staging、原子切 CURRENT、重建索引 | 提交器 |

提交器**不猜测**语义，也不要求 Agent 使用正则或自动切句。

## 2. 标准步骤

```text
1. papercheck context --output context.json
2. Agent 读 context.json 与 paper.md
3. Agent 写 proposal.json
4. papercheck propose proposal.json       # 校验并暂存
5. papercheck commit --proposal proposal.json
6. papercheck verify
```

若 `commit` 返回 base/paper 哈希冲突（exit 3），说明 Agent 工作期间正文又变了：重新执行 `context`，基于新输入重写 proposal。**不要覆盖或回滚作者的新文字。**

## 3. context.json

关键字段：

```json
{
  "base_state_id": "D000002",
  "base_sha256": "sha256:...",
  "base_snapshot_id": "SNAP000002",
  "paper_sha256": "sha256:...",
  "paper_size": 1234,
  "lines": [
    {"line": 1, "start_byte": 0, "end_byte": 13, "text": "# Title\n"}
  ],
  "old_selections": [
    {
      "placement_id": "PL000001",
      "container_id": "S000001",
      "variant_id": "V000001",
      "block_id": "B000001",
      "kind": "paragraph",
      "source_ranges": [{"start_byte": 16, "end_byte": 58}],
      "raw_text": "...",
      "normalized_text": "..."
    }
  ],
  "old_untracked": [
    {"start_byte": 58, "end_byte": 59, "reason": "between_selections"}
  ],
  "diff": [
    {"tag": "replace", "old_lines": [3, 4], "new_lines": [3, 4], "old_text": "...", "new_text": "..."}
  ]
}
```

- 所有 `start_byte` / `end_byte` 都是 UTF-8 **字节偏移**，左闭右开。
- `old_selections` 是上一状态在当前稿中的选择，不代表当前稿仍然如此。
- `diff` 只是辅助；行级 diff 不能替代字节级 proposal。

## 4. proposal.json

一个 proposal 描述**当前 paper.md 的完整快照选择**，不是增量补丁。

```json
{
  "schema_version": "1.0.0",
  "base_state_id": "D000002",
  "base_sha256": "sha256:...",
  "paper_sha256": "sha256:...",
  "segments": [
    {
      "container_id": "S000004",
      "block_id": "B000003",
      "kind": "paragraph",
      "text": "Raw interaction counts are associated with traffic volume.",
      "source_ranges": [{"start_byte": 120, "end_byte": 184}]
    },
    {
      "block_ref": "new-p1",
      "kind": "paragraph",
      "text": "A newly added sentence.",
      "source_ranges": [{"start_byte": 185, "end_byte": 210}]
    }
  ],
  "untracked": [
    {"start_byte": 184, "end_byte": 185, "reason": "space"}
  ]
}
```

### 4.1 Segment 字段

| 字段 | 必填 | 含义 |
|---|---|---|
| `source_ranges` | 是 | 一个或多个字节范围；当前稿中的一次出现 |
| `text` | 建议 | Agent 认为该容器表达的文字；用于规范文本与变体比较 |
| `container_id` | 否 | 复用旧容器；省略则创建新容器 |
| `variant_id` | 否 | 仅在文字未变时复用旧变体；**文字变化时省略** |
| `block_id` | 否 | 复用旧文本块 |
| `block_ref` | 否 | 新文本块的分组键；同一新块的多句使用同一 `block_ref` |
| `kind` | 新容器/新块必填 | `paragraph` / `heading` / `list_item` / `blockquote` / … |
| `lineage` | 否 | `{"type":"split"|"merge","from":["S..."]}` |
| `reason` | 否 | 变更理由，写入事件 |

规则：

- `block_id` 与 `block_ref` 二选一。
- 复用 `container_id` 时，若文字有变化，省略 `variant_id`；提交器会创建新变体，旧变体保留。
- 提供 `variant_id` 时，`text` 的规范文本必须与旧变体一致，否则校验失败。
- 同一 `container_id` 在一个 proposal 中最多出现一次；重复文字使用不同容器。
- 拆分：新容器不填 `container_id`，推荐每个目标都填写相同的 `lineage.type=split`、`lineage.group` 和来源；同组至少两个目标。简写只允许单次拆分占用同一个 block 的全部未分组新增容器；同 block 多个不同拆分必须用显式 group。
- 合并：新容器不填 `container_id`，写 `lineage.type=merge`，`from` 列出旧容器。
- 删除：直接从 `segments` 省略；提交器发出 `REMOVED_FROM_TEXT`。
- 恢复：复用仍存在的旧 `container_id` / `variant_id`；提交器发出 `RESTORED_IN_TEXT`。
- 移动：复用旧 ID，填新 `source_ranges`；跨块时提交器发出 `CONTAINER_MOVED`。

### 4.2 覆盖不变量

`segments[].source_ranges` 与 `untracked[].source_ranges` 必须：

1. 覆盖 `paper.md` 的每一个字节；
2. 互不重叠；
3. 都不越界；
4. 按 proposal 的粒度可定位。

公式/代码/表格等暂不抽取的结构，用 `untracked` 明确保留原文：

```json
{"start_byte": 400, "end_byte": 512, "reason": "deferred:table"}
```

未追踪不是丢弃：字节仍在 `paper.md` 中，报告中会列出。

## 5. 校验与提交语义

`propose` / `validate` 检查：

- `schema_version`
- `paper_sha256` 与当前正文
- `base_state_id` / `base_sha256` 与 CURRENT
- segment 引用的容器/变体/块存在且归属正确
- `variant_id` 与文字一致
- lineage 来源存在
- 字节覆盖与重叠
- 同一容器不被重复放置

`commit` 在锁内重复全部检查，并再次确认 `CURRENT` 与 `paper.md` 哈希未变，然后：

```text
staging 写入完整 sources + manifest
  → 校验 staging
  → 再次检查 base/paper 哈希
  → 发布到 states/Dxxxxxx
  → 追加 commit-log
  → 原子替换 CURRENT
  → 重建索引/写报告（失败不回滚已提交状态）
```

退出码：`0` 成功，`1` 校验/状态问题，`2` proposal/命令错误，`3` 并发修改（重跑 context）。

## 6. 不要做的事

- 不要让 Agent 直接改 `.papercheck/states/` 或数据库。
- 不要把未校验的 `supports` / `REPLACES` 当成已确认事实。
- 不要在正文变化后沿用旧 proposal。
- 不要把“未检查”写成“通过”。
- 不要用 `--auto` 替代需要语义判断的修改；它只用于首次基线或明确同意的机械路径。

## 7. 提交后的核对

执行 workflow 查看未抽取命题、未知身份、候选修订、缺失全文、失效检查和冲突。通过 semantic.revision_decisions 确认或驳回候选；引用/上下文变化需要额外失效时提交 invalidate_checks。审核完成后提交 Check/Assessment，再读取报告；不直接修改任务 JSON 或历史源文件。

show --json 返回原始正文、全部语义记录和当前 Claim 视图；show --state D000001 --json 可回溯历史。安装包自带模板和 Schema，可在源码目录之外使用。
