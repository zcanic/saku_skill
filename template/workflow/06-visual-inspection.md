# 可视化人工核读

此层是当前不可变账本的只读投影，不负责自动认定论文正确，不替代 workflow 待办。

## 首次创建

先完成本轮 validate → commit → verify，再运行：

```powershell
python -m papercheck inspector init
python -m papercheck inspector export
python -m papercheck inspector serve
```

默认访问 http://127.0.0.1:4178。可加 `--port 4180`。需要 Node.js 24；前端已有构建，无需 npm 安装。PDF 原页预览另需当前 Python 安装 PyMuPDF。PDF 非必需；若提供，使用 `inspector export --pdf paper.pdf`，Agent 先确认该 PDF 与当前稿一致；哈希仅保证文件完整性，不证明 MD/PDF 内容一致。

在 `inspector/config.json` 的 `source_roots` 中配置作者允许随检查层复制的材料目录（默认 `references`，路径相对工作区）。证据由登记的文件、行号、JSON pointer、页码定位；不执行来源代码和 SQL，不自动联网下载。未授权、不可用及未支持格式只保留登记记录。允许目录的全部内容不会被复制，只有被命题证据引用的文件会进入包。

## 每次修改

1. 冻结 context，完成命题拆分、关联、证据核对；validate → commit → verify。
2. 运行 `inspector export` 创建新 release，再刷新页面。
3. 点击左侧原文，逐条展开右侧命题，检查精确证据及当前核查。默认不展开第一个命题。
4. 未拆分正文、未跟踪内容和工作流待办不得当成已核查。历史核查保留追溯，但不参与当前状态。
5. “我的检查”存入 `inspector/reviews`，不改写论文或账本；需要正式结论时，由 Agent 重新查证后提出新 proposal。

本地 serve 会检测工作区正文和 CURRENT 变化；旧页面变为冻结视图并暂停保存。新 release 不自动继承旧版的个人勾选。不要修改 release 内文件；更正通过登记、重新导出完成。

## 交付与切换

只有用户要求部署/打包时执行：

```powershell
python -m papercheck inspector package --output site.zip
python -m papercheck inspector package --release-only --output version.zip
```

完整包包含当前论文、引用的允许来源、冻结账本、网页及部署说明；因此需确认材料分发权限。包不含个人备注、真实 `.env` 或其他 release 目录；冻结账本保留必要的历史记录。ZIP 附 SHA-256；数据更新按包内 UPDATE_SOP.md 验证、预暂存、激活或回滚。不接受覆盖服务器整个目录的更新，不从网页接收上传，不自动公开发布。
