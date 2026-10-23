# papercheck 开发与使用

这是一个 Agent 驱动的论文检查工作流脚手架，可生成独立项目文件夹。领域分析由外部 Agent 完成；Python 提交器提供字节、身份、引用、数值、不可变状态与流程完整性保障。

开发前读 README.md、docs/agent-workflow.md 和 docs/semantic-contract.md。模板位于 papercheck/template；不要把模型服务或某一 Harness 变成必需依赖。

正文默认只读；命题、证据、审核和修订不得编造或覆盖历史。未知项保留待办，不得标成通过。修改 schema 时运行 scripts/build_contracts.py，同步仓库与包内契约并测试安装后的包。

验证使用 python -m pytest。重要行为需有有意义的回归或端到端测试。Git 按可审查的模块提交，避免提交 .env、凭证、运行缓存、构建产物与用户未授权的论文材料。
