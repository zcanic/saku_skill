# 切分与容器边界

## 1. 默认由 Agent 决定

`papercheck` **不要求**用正则自动切句。Agent 阅读 `paper.md` 与 `context.json`，决定：

- 哪些字节组成一个 Container；
- 一个句子是否拆成多个 Container；
- 多句是否合并为一个 Container；
- 哪些区域暂不抽取（`untracked`）。

提交器只检查字节覆盖、引用和哈希，不评价切分是否“像句子”。

## 2. 推荐的 Agent 切分原则

- 以语义可独立检查为粒度；不强制“一句一 Container”。
- 中英文混排时，`.` / `。` / `？` / `！` 是候选边界，不是硬规则。
- 小数、千分位、`et al.`、`e.g.`、`Fig.` 等缩写内部不切。
- 行内代码、链接目标、公式、HTML 标签内部不切。
- 跨行句子可以是一个 placement，使用多个 `source_ranges` 或一个跨行范围。
- 表格、代码块、数学块可整体 `untracked`，并保留原文；需要 Quantity 时由 Agent 明确细分与抽取。
- 重复出现的同一句话使用不同 Container，避免一次局部修改误伤另一处。

## 3. 可选自动辅助（`--auto`）

`papercheck` 自带一套机械基线，仅用于首次启动或明确同意的机械路径：

```text
paper.md 字节快照
  → markdown-it block parser（保留 line map）
  → inline token content
  → 保护 inline code / link / math / HTML / escape
  → 中英边界规则
  → 字节偏移映射
```

实现位置：`papercheck/markdown.py`、`papercheck/segment.py`。

自动辅助的局限：

- Markdown inline token 的精确位置是近似映射，不保证所有扩展语法；
- 不判断语义等价；
- 不替代 Agent 的 container 复用/拆并判断。

## 4. 字节与保护范围

- 所有范围是 UTF-8 字节偏移，左闭右开。
- `raw_text` 必须与源字节一致；`normalized_text` 只用于对齐。
- 行内保护范围：反引号代码、`[label](url)`、`$...$`、`<tag>`、反斜杠转义。
- 表格/公式/代码块在自动路径中进入 `untracked_blocks`。

## 5. 验收阈值（自动辅助）

`schema/registry.yaml` 固定了 Phase 1 的验收线：

| 指标 | 阈值 |
|---|---|
| 边界 precision | ≥ 0.98 |
| 原文字节覆盖 | 100% |
| Container ID retention | ≥ 0.95（基准集） |
| 误匹配率 | ≤ 0.01 |

这些阈值只约束自动辅助；Agent proposal 的验收是**覆盖完整、引用合法、语义决定可解释**。
