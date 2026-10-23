# 存储协议

## 1. 三种状态

1. **Working Copy**：根目录 `paper.md`。作者/Agent 可编辑，不是已提交状态。
2. **Committed State**：`states/Dxxxxxx/` 下的完整冻结源文件与 `manifest.json`。
3. **Materialized View**：Postgres/SQLite 索引、`reports/*.md`、导出物。均可从 State 重建。

根目录不放全局 `claims.jsonl` 作为权威源。**权威源只存在于已提交 State 内。**

## 2. 目录

```text
.papercheck/
├── CURRENT
├── states/D000001/{manifest.json,sources/*}
├── staging/                 # 候选 proposal、未发布状态
├── recovery/commit-log.jsonl
├── reports/
└── index.sqlite             # 未配置 Postgres 时使用
```

## 3. 提交协议（Windows 优先）

单写者；读进程只读取一次 `CURRENT`，之后固定 `state_id`。

1. 读取 `CURRENT = D_old`，冻结 `paper.md` 的字节、大小和 SHA-256。
2. 在锁内加载旧 State；旧 State 校验失败则拒绝继续。
3. Agent 提交 proposal；确定性校验器检查 Schema、引用、覆盖、base/paper 哈希。
4. 在 `staging/D_new/` 写入完整 sources + manifest；写完关闭句柄。
5. 校验 staging（哈希、引用、覆盖、ID 唯一性）。
6. 再次读取 `CURRENT` 与 `paper.md` 哈希；任意变化则放弃本次提交。
7. 将 staging 发布到此前不存在的 `states/D_new/`。
8. 追加 `recovery/commit-log.jsonl`（state_id、manifest 哈希、paper 哈希、run_id）。
9. 写 `CURRENT.tmp`，flush/close，`os.replace(CURRENT.tmp, CURRENT)`。
10. 重建索引、写报告；缓存失败不影响已提交 State。

**逻辑提交点是 `CURRENT` 的原子替换。** 已发布 State 内不再追加或修改任何文件。

## 4. 失败与恢复

- `after_stage` 失败：staging 可丢弃；CURRENT 不变。
- `after_publish` 失败：State 已发布但 CURRENT 未切；CURRENT 仍指向旧 State，旧 State 可验证。下次提交会分配新 ID，孤儿 State 可人工清理。
- `before_current` 失败：同 after_publish。
- `after_current` 失败：新 State 已生效；`verify` 通过。
- `CURRENT` 缺失/损坏：`recover` 从 commit-log 逆序找第一个可验证 State，原子写回 `CURRENT`；没有日志时，从最新 State 目录逆序回退。
- 仓库启动时先验证 CURRENT 指向的 manifest 与全部 `file_hashes`；不能仅凭最大目录号推断成功提交。

Windows 注意：`os.replace` 同卷文件替换是原子的，但不保证跨文件系统或断电强持久；发布目录必须是全新目录，不能覆盖已有 State。

## 5. Manifest

```json
{
  "schema_version": "1.1.0",
  "state_id": "D000002",
  "parent_state_id": "D000001",
  "created_at": "2026-10-21T15:00:00Z",
  "input": {"path": "paper.md", "sha256": "sha256:...", "size_bytes": 1234},
  "parser_version": "1.0.0",
  "segmenter_version": "1.0.0",
  "canonicalizer_version": "1.0.0",
  "snapshot_id": "SNAP000002",
  "source_files": {"paper": "sources/paper.md", "...": "..."},
  "file_hashes": {"sources/paper.md": "sha256:...", "...": "..."},
  "validation": {"structurally_valid": true, "semantic_status": "pending"}
}
```

`file_hashes` 必须覆盖该 State 的全部权威源文件；示例不是完整列表。

## 6. ID 分配

- State `D000001`、Snapshot `SNAP000001`、Block `B000001`、Container `S000001`、Variant `V000001`、Placement `PL000001`、Event `EV000001`。
- 6 位数字，提交器单写者分配；Agent 对新对象使用 proposal 内的临时 ref/block_ref，已有对象使用验证过的永久 ID。
- ID 不可重用；断号允许。

## 7. 索引

- 配置 `PAPERCHECK_DATABASE_URL` 时写 Postgres；否则写 `.papercheck/index.sqlite`。
- `meta.indexed_state_id` 必须与 CURRENT 一致；不一致时索引结果不得冒充当前结果。
- 索引重建可以 `DROP` 自己的表；它不是事实来源。

## 8. 1.1.0 补充

新状态包含 revisions、bindings、arguments、reviews、invalidations，及已实现的 claims/references/evidence/assessments/quantities/checks/runs。语义记录带 state_id、run_id 和协议版本；Run 保存原始提案、扩展字段和本轮摘要。

有效的 1.0.0 状态使用原文件集合校验；后续提交升级为 1.1.0，不重写旧状态。新版本执行包内记录 Schema、完整哈希集合、源字节、对象引用和语义指纹校验。

recover 与 commit 使用同一写锁，检查恢复日志的 manifest 摘要。截断尾行可忽略；后续 commit 修复尾行再追加。有日志时不选择摘要不匹配的未记录目录。

Git 应保存不可变 states 与恢复日志；仅忽略索引、staging、凭证和临时上下文。多 range placement 在索引中按 (placement_id, seq) 保存，语义索引位于 semantic_records。
