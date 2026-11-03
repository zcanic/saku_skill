# 文字、命题与修订

选择容器边界并覆盖全部 UTF-8 字节。仅在原始文字完全相同时沿用 variant_id；改字时保留 container_id 并省略 variant_id。移动保留身份；拆分使用每个目标都明确填写的 lineage.group，合并列出全部源容器。

对可审查断言建立 canonical_statement。区分对象、谓词、条件、总体、时间、量词、否定、模态与数量。已知真值条件完全一致才复用指纹；未知条件走新命题和 proposed revision。

bindings 是当前稿命题位置的完整列表；before placements 必须来自上一快照，after segments 必须绑定本轮命题。同一命题多处出现时列出所有 contexts。恢复历史命题用 RESTORE，不创建反向 REPLACES。

## 长稿件（几十页、数百句）

- 先 `init` 建立机械切分基线，再重新 `context`。之后的提案从 `old_selections` 逐条复制 container_id、variant_id、block_id 与 source_ranges，只在需要处改动。不要手算几百个字节偏移。
- 用小脚本生成提案的机械部分（segments、untracked、标题与参考文献的 non_claim），语义部分（命题、数值、推导、理由）逐条手写。脚本放在工作区之外或 `.gitignore` 覆盖的位置。
- 明确本轮范围（例如“全文数值自洽 + 摘要/结论命题”）。范围外的句子保留 extract_claims 待办，不批量标成 non-claim。
- 要核对表格里的数字时，把表格行从 `deferred:table` 提升为 `kind: "table"` 的 segment（每行一个，表头和分隔行仍可 untracked），数值才能绑定到行。
- 句子切分以 context 中的 raw_text 为准。`source_expression` 必须逐字出现在该 segment 的原文里，包括 Markdown 标记（如 `_n_ = 273`）。

输出：文本覆盖、命题与位置绑定、Revision Group、无需命题的段落说明。
