# 语义提案与工作流契约（1.1.0）

本项目是可复用的 Agent 工作流脚手架。外部 Agent 阅读论文并提交判断；提交器不调用模型、不自动检索全文，也不从字符串相似度断言语义等价。

## 1. 完整路径

```text
scaffold → context → Agent 阅读与提案 → validate → commit → verify → workflow/report
```

模板包含 AGENTS.md、PROJECT.md、四份 workflow 说明及提案示例。使用者无需操作数据库或直接编辑权威 JSONL。模型、编辑器、Harness 和领域检查规则可以替换。外围 GitHub 安装 skill 独立于此仓库。

## 2. 提案与身份

文本部分保持原协议；每个 segment 可给本轮唯一 `ref`，供语义记录引用。偏移是 UTF-8 字节，非字符索引。格式变化也产生新 Variant；只在源字节完全相同时沿用 variant_id。

`semantic` 是可选的 1.1.0 区域。省略时只提交文本，自动保留精确 Variant 未改变的旧绑定；变化的部分留出 extract_claims 待办。提供时，`bindings` 必须列出**当前稿的全部命题绑定**，不是增量绑定补丁；其他记录数组是新增记录或明确身份复用。

| 字段 | 含义 |
|---|---|
| claims | `ref`, `surface_statement`, `canonical_statement`，可选 `claim_id`, `kind`, `review_requirements` |
| bindings | `claim`（本轮 ref 或既有永久 ID）、`segment`、`reason` |
| non_claim_segments | 不含可审查命题的 segment 与理由；不能同时绑定 Claim |
| references | 新来源的 ref、title、source_access，及可选 URL、哈希、数据集/研究标识 |
| reference_ids | 当前仍使用的既有 Reference ID；未取得全文的项目生成待办 |
| evidence | ref、reference、quote、locator；以及共享来源/数据集/研究标识 |
| quantities | 见 §5；抽取与比较分开记录 |
| revisions | 修订操作、before/after、status、reason |
| revision_decisions | 对既有修订的 revision_id、status 和 reason；追加新决定而不覆盖历史 |
| relations | src/dst Claim、type、status、reason；REPLACES 不允许直接写入 |
| assessments | claim、evidence、status、reason、可选 limitations |
| checks | claim_ids、kind、outcome、reason、method、可选 evidence_ids |
| invalidate_checks | 指定上次有效 check_id 和理由，处理引用/上下文变化等额外失效 |
| arguments | ref、conclusion、premises、status、reason；确认的必要前提投影为 DEPENDS_ON |

所有新对象用临时 ref；提交器统一分配永久 ID。扩展描述字段允许存在，完整原始提案保存在本次 Run 中。已知的结构、偏移、引用和语义区域受到确定性校验；错误不会因“描述性契约”被跳过。

权威机器契约在 `papercheck/schemas/`。仓库 `schema/` 是同步发布副本，修改生成器后执行 `python scripts/build_contracts.py`。安装包自带契约与模板，不依赖源码目录旁边存在 schema 文件夹。

## 3. canonical statement

用于稳定指纹的字段为 subject、predicate、object、polarity、modality、causality、quantifier、population、time_scope、conditions、quantity_ids。未知写 `unknown`，不适用可写 null。主体、谓词、客体等核心真值字段不能用 null 获取已知身份。

字符串做 NFC 和空白规整；conditions 和 quantity_ids 是无序集合，其他列表保留顺序。Quantity 指纹使用数值与范围内容，不使用新分配的 ID。哈希输入包含 canonicalizer 及序列化版本。

缺字段、unknown 或不完整的 Quantity 范围均禁止指纹复用；会创建新 Claim。显式 claim_id 复用也必须满足已知且一致的指纹。一个容器中出现新 Claim 而旧 Claim 消失时，可以生成 proposed Replacement 供复核，不能自动当成逻辑蕴含或事实已确定。

工具不替 Agent 生成实体/谓词词典或保证任意 paraphrase 被识别。Agent 应在规则覆盖的等价改写中复用同一 canonical statement，不能只靠 embedding 相似度合并。

## 4. Revision Group

```json
{
  "operation": "REPLACEMENT",
  "before": [{"claim": "C000001", "placements": ["PL000001", "PL000002"]}],
  "after": [{"claim": "new_claim", "segments": ["abstract", "discussion"]}],
  "status": "confirmed",
  "reason": "因果表述改为相关性表述"
}
```

before 必须绑定上一 Snapshot，after 必须绑定本轮位置。支持 REPLACEMENT/SPLIT/MERGE、DELETE 和 RESTORE；删除要求 after 为空。RESTORE 不创建反向 REPLACES。新旧 Claim、Evidence、Review 都保留。

REPLACES 从 Group 投影，方向为新 Claim → 旧 Claim。proposed 不进入已确认依赖推理；replacement flag 只对已确认替代的新命题生效，已有历史命题的身份不被覆写。

候选修订在后续运行中通过 revision_decisions 确认或驳回。新决定用 supersedes 关联旧记录；旧 Group、边与检查结果保留。当前 replacement flag 查看 `show --json` 的 current_claims 或 snapshot.replacement_claim_ids；历史 Claim 记录里的 flags 保留创建时的信息。确认的替代链禁止成环，恢复历史身份应使用 RESTORE。

## 5. Quantity IR 与证据

Quantity 必填 ref、metric_id、value、unit、segment、source_expression、extraction_status。可关联 claim。value.type 支持 point、range、interval；数值必须是有限十进制字符串；interval 额外要求 confidence。原始表达必须实际出现在对应 segment 中。

可比性字段为 metric_id、population、dataset_id、dataset_version、sample_filter、time_scope。缺少范围返回 insufficient_context；范围不同为 incomparable；未确认抽取为 pending。百分比需要 percent_base。工具以十进制执行范围、容差与登记的单位换算，产生独立 Check；它不证明原始实验材料正确。

Reference 访问级别封闭为 full_text、abstract_only、snippet_only、metadata_only、unavailable。元数据或不可获取来源禁止登记 quote Evidence；摘要/片段不能登记 fully supported。全文位置和引文由 Agent 实际阅读并负责，校验器检查引用结构而非伪装成 PDF 阅读器。

共享 source/dataset/study 会记录独立性状态；没有信息时保持 unknown，不以证据条数计算可信度。Assessment 会派生 evidence Check。其他检查由 Agent 填写方法与理由，历史审核不因更新被覆盖。

## 6. 增量工作流

Snapshot 保存当前绑定、Claim、Quantity、Reference、Check ID，以及 workflow.tasks。已确认 DEPENDS_ON、SUPPORTS、ENTAILS 用于受影响范围传播；proposed 关系不当成确定依赖。同一关系的后续状态通过新记录 supersedes 保留历史。

已知真值条件不变的明确改写可复用检查；变更/删除的命题及其下游旧检查记录 Invalidation，原历史 Check 仍保持原结果。对当前稿的全量语义绑定是 Agent 的责任；文本-only 路径采取保守失效策略。

默认经验性 Claim 需要 evidence 检查；定义需要 logic，方法声明需要 methodology。领域可用非空 review_requirements 扩展检查种类。未完成审核、未知身份、候选修订、缺失全文、数值冲突均形成待办。workflow completed 仅表示本次声明范围内的登记步骤已完成，不保证论文或 Agent 判断绝对正确。

## 7. 兼容与恢复

有效 1.0.0 文本状态仍可读取；下次提交产生包含新源集合的 1.1.0 状态，不重写旧目录。1.0.0 文本提案仍可使用，语义区域要求 1.1.0。

提交只切换 CURRENT，报告和索引是派生物。索引失败会明确返回；报告可重建。恢复容忍未完成日志尾行，后续提交修复尾行；存在恢复日志时不把摘要不匹配的孤儿目录当成可信提交。
