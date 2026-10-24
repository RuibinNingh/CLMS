# CLMS 作文档案馆

CLMS 保存语文、英语作文的题目材料、图片/PDF 原稿、独立练习、多稿版本和评价历史。分类由用户创建，初始为空。网页直接保存人工操作；外部 AI 仅通过 MCP 读图和提交待审提案，人工在网页通过后才正式入档。

系统不调用模型，不做 OCR，不保留原题库、默写、复习调度或旧版兼容入口。新数据目录必须与旧数据目录分开。

## 正式开发工作区

本机正式源码目录为 `/root/workspace/apps/clms`，主分支 `master` 已合入作文档案馆重构。原 Codex 工作树仅保留分支与工程证据，不再作为默认开发入口。旧源码、未提交修改和旧数据已独立保存，不混入新版源码。

源码目录与生产 release、生产数据目录分开；改源码不等于上线。定位、并行设计产物与旧版恢复边界见 [本机工作区说明](docs/operations/workspace.md)。

## 本机启动

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/)、Node.js 22.12+ 和 npm。依赖由 `uv.lock`、`frontend/package-lock.json` 锁定。

```bash
uv sync --frozen
npm --prefix frontend ci
npm --prefix frontend run build
export CLMS_DATA_DIR="$PWD/data-archive"
export CLMS_PUBLIC_ORIGIN=http://127.0.0.1:8472
uv run --frozen python -m backend.app.cli init
uv run --frozen alembic upgrade head
uv run --frozen uvicorn backend.app.main:app --host 127.0.0.1 --port 8472
```

打开 [http://127.0.0.1:8472](http://127.0.0.1:8472)，在本机读取新数据目录的 `bootstrap.token`，用网页设置管理员用户名和密码。令牌只用于首次初始化；不要写进聊天、日志或提交文件。远程访问使用 HTTPS，并设置正确的 `CLMS_PUBLIC_ORIGIN` 和 `CLMS_SECURE_COOKIE=true`。

## 使用路径

1. 在分类管理创建需要的分类，也可以保留未分类。
2. 新建作文，输入题目说明或上传题目材料；上传原稿图片/PDF，排序后保存。
3. 在稿件详情复制任务上下文，向外部 AI 提供稿件 ID；AI 经 MCP 获取快照与图像，提交评价提案。
4. 在审核中心核对原稿、目标版本和评价，修订后通过并入档或驳回。
5. 修改上一稿创建 V2；同题重新写一篇创建新的练习并从 V1 开始。原稿和旧评价保留。

设置页创建独立 MCP 凭据，密钥只展示一次。端点为同源 `/mcp/`，使用 `Authorization: Bearer <secret>`。允许的 scope 是 `archive.read`、`media.read`、`proposals.write`；凭据不能批准提案或管理其他密钥。实际外部客户端是否支持自定义 Bearer 接入需单独核验。

从0.10.2起，可把作文图片/PDF交给支持原生附件传递的ChatGPT客户端，由 `upload_attachment` 暂存原件，再由AI提交练习待审；通用MCP客户端可用 `upload_asset` 上传真实文件字节。上传结果是暂存件，网页批准后才入档。更新后刷新客户端工具列表。附件域名、权限和限额见 [MCP工具目录](docs/mcp/tools.md)。

用户当前选择先模拟自测。设置页取得测试凭据后，将它放入当前进程的 `CLMS_MCP_TOKEN` 环境变量（不要写入命令历史/证据），运行官方 SDK 脚本：

```bash
uv run --frozen python scripts/simulate_client.py \
  --endpoint http://127.0.0.1:8472/mcp/ --version-id <网页复制的版本ID> \
  --request-id manual-simulation-1
```

脚本实际读取快照与图像、提交明确标为模拟的 pending 评价，随后在网页人工审核；它不调用模型、不自动批准，也不代表真实模型识图验收。

直接 `python -m backend.app.cli serve` 或 `./run.sh` 的默认端口为 **18474**，默认 origin 同为 `http://127.0.0.1:18474`；上面的显式 uvicorn 与容器例子使用 **8472**。自定端口时同步设置 `CLMS_PUBLIC_ORIGIN`。

## 验证

```bash
npm --prefix frontend exec playwright install chromium
uv run --frozen python scripts/verify.py --all --report artifacts/verification.json
```

统一入口运行后端、前端类型/单测/构建、依赖审计、真实浏览器、官方 MCP SDK 经实际端口、安全边界和干净安装部署。缺依赖、跳过必需测试或零测试收集均失败。开发时可以用 `--gate backend` 等子集；子集不代表全套验收。

报告与截图位于 `artifacts/`。模拟外部评价者、官方协议验证、真实外部 AI、实体设备和生产切换分别记载；自动化退出 0 不能代替真实模型验收。

- 开发入口：[AI/README.md](AI/README.md)
- 实施契约：[docs/architecture/contract.md](docs/architecture/contract.md)
- 部署与运维：[docs/operations/deployment.md](docs/operations/deployment.md)
- 旧版切换与回滚：[docs/operations/cutover.md](docs/operations/cutover.md)
- 验收矩阵：[docs/plans/essay-archive-rebuild/acceptance.md](docs/plans/essay-archive-rebuild/acceptance.md)
- 外部客户端记录：[external-client-verification.md](docs/plans/essay-archive-rebuild/external-client-verification.md)
