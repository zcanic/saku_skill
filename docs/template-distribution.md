# 完整模板分发

成品目录：`template/`。ZIP 按下文命令在本机生成，dist 不纳入源码仓库。当前工具版本为 0.3.0。

目录和 ZIP 包含同一套文件，初始 paper.md 和 references 为空。TEMPLATE-MANIFEST.json 列出初始文件的 SHA-256，清单本身不参与自引用哈希。0.3.0 增加项目级 skill 与通用可视化检查层，资产清单另见 papercheck/inspector_assets/ASSET-MANIFEST.json。

## 包含的内容

- README、PROJECT、面向使用者的 AGENTS。
- 四阶段工作流及完整语义指南。
- 可直接查看的 proposal/records 机器契约与提案格式示例。
- 完整 papercheck Python 源码、包内契约、工厂模板和安装声明。
- 空白论文、材料目录、Git 忽略与行尾设置。
- 保留远端版权署名的 MIT LICENSE（完整模板、脚手架与检查层运行包均携带）；第三方许可另列。
- 项目级 `.agents/skills/papercheck/SKILL.md`、可视化核读工作流、React/Radix/Motion 源码与有意分发的已构建静态网页；独立 Node 运行时、Docker 配置、ZIP 校验/激活/回滚 SOP 和第三方许可声明。

依赖通过 pip 安装，不绑定模型服务或 Harness。默认 SQLite；Postgres 依赖可选。模板自带源码，因此不依赖父目录的开发仓库或某个预装的 papercheck 版本。

开发用 AGENTS、历史设计与验收报告、测试材料、实际论文、真实 .env、Git 历史、缓存、非分发构建产物、安装依赖和 .papercheck 运行状态均不进入成品。导出器使用显式文件类别清单及校验过的资产清单，不递归复制整个开发目录。字体等二进制不进行文本行尾转换。

## 验证

0.2.0 的历史验收为 80 项测试，并从 ZIP 安装执行基础流程。0.3.0 的检查层接入与验证记录见 [visual-inspection.md](visual-inspection.md)；不沿用历史测试数量作为本次验收结论。

测试仅使用明确标注的合成材料，不向干净模板写入测试论文或生成运行目录。测试产物位于 .tmp/template-practical-check，未进入分发包或 Git。SQLite 路径已实测，Postgres 服务和真实学术判断质量不在本次分发验证范围。

导出器的四项测试覆盖文件清洁度/完整性、哈希、ZIP 内容一致性、用户修改保护和可重复归档。验证目录与 ZIP 内容保持一致；归档按固定文件顺序与时间元数据生成，同样输入可以生成字节一致的 ZIP。

## 维护

```powershell
# 校验当前成品是否与源文件一致
python scripts/export_template.py --output template --check

# 首次导出到全新目录并归档
python scripts/export_template.py --output .tmp/new-template --zip dist/new-template.zip

# 当前成品校验通过后，写入一个全新的归档文件
python scripts/export_template.py --output template --check --zip dist/checked-template.zip
```

导出器不覆盖已有目录、归档或论文。若成品中已经放入论文或产生用户修改，校验会明确报错；应从新目录导出，并通过 Git 审查需要更新的模板文件。

源配置位于 scripts/export_template.py 和 distribution/README.md；完整模板不附带开发测试套件或验收日志。主仓库可继续开发，template 目录可单独复制出去作为项目起点。
