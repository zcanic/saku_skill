# 文字、命题与修订

选择容器边界并覆盖全部 UTF-8 字节。仅在原始文字完全相同时沿用 variant_id；改字时保留 container_id 并省略 variant_id。移动保留身份；拆分使用每个目标都明确填写的 lineage.group，合并列出全部源容器。

## 什么算原子命题

判定标准：**所有判断，以及所有不属于常识的陈述，都是原子命题。**常识以“非本专业的本科生也应该知道”为界。

- 判断一律登记，无论有没有数字：评价、比较、因果、解释、推断、建议、适用范围，以及“显著”“稳定”“有效”“更好”这类定性词。
- 非常识的事实陈述一律登记：结果与数字、方法与操作步骤（“我们做了 X”）、数据来源与处理、定义与设定、文献归属（“某文献发现 Y”）、声明与来源说明。
- 每个命题只含一个可独立判断真假的内容。并列、转折、“因为……所以……”要拆开；“因此”引出的结论单独成为一条判断。
- 同一命题在多处出现时只建一个 Claim，绑定到所有位置。
- 只有以下内容可以写进 non_claim_segments，并且要写明理由：标题、作者占位符、纯导航句（“Figure 2 summarizes…”）、图注里的面板编号与图例说明、关键词、缩写定义、常识（如“MAE 越低越好”）。拿不准时按命题登记。
- 表格中的每一行都是一条报告结果；需要逐格核对时，再拆成数值（Quantity）。
- kind 取以下之一，以便检查层分组显示：empirical_result、method_or_definition、literature_claim、interpretation、practical_implication、scope_and_limitation、research_question_or_contribution、background_or_literature、declaration_or_provenance、table_cell。review_requirements 按类别设置：结果与文献类填 evidence，方法类填 methodology，判断类填 logic。

对可审查断言建立 canonical_statement。区分对象、谓词、条件、总体、时间、量词、否定、模态与数量。已知真值条件完全一致才复用指纹；未知条件走新命题和 proposed revision。

bindings 是当前稿命题位置的完整列表；before placements 必须来自上一快照，after segments 必须绑定本轮命题。同一命题多处出现时列出所有 contexts。恢复历史命题用 RESTORE，不创建反向 REPLACES。

## 长稿件（几十页、数百句）

- 先 `init` 建立机械切分基线，再重新 `context`。之后的提案从 `old_selections` 逐条复制 container_id、variant_id、block_id 与 source_ranges，只在需要处改动。不要手算几百个字节偏移。
- 用小脚本生成提案的机械部分（segments、untracked、标题与参考文献的 non_claim），语义部分（命题、数值、推导、理由）逐条手写。脚本放在工作区之外或 `.gitignore` 覆盖的位置。
- 明确本轮范围（例如“全文数值自洽 + 摘要/结论命题”）。范围外的句子保留 extract_claims 待办，不批量标成 non-claim。
- 要核对表格里的数字时，把表格行从 `deferred:table` 提升为 `kind: "table"` 的 segment（每行一个，表头和分隔行仍可 untracked），数值才能绑定到行。
- 句子切分以 context 中的 raw_text 为准。`source_expression` 必须逐字出现在该 segment 的原文里，包括 Markdown 标记（如 `_n_ = 273`）。

输出：文本覆盖、命题与位置绑定、Revision Group、无需命题的段落说明。
