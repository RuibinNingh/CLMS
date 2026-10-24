# 本机源码、生产发布与旧版恢复边界

## 正式维护入口

- 正式源码目录：`/root/workspace/apps/clms`，主分支为 `master`；0.10.0 前端与发布记录在 `codex/book-page-frontend` 分支；0.10.1 审核中心与最新发布记录在 `codex/review-center-draft` 分支（`/root/.codex/worktrees/review-center-draft/clms`）。本次生产发布直接取已验证提交，不改变主分支。
- 2026-10-11 经用户明确授权，主分支从 `50f2721` 快进合并到重构提交 `cbbe05b8f76956f052db8ece8eaa584f55b0b56f`；后续工作区交接文档提交不改变应用运行代码或版本。
- `/root/.codex/worktrees/essay-archive-rebuild/clms` 保留原重构分支和工程证据，但不是默认维护入口。不要删除其 Git 注册元数据，也不要在两个工作树同时修改同一维护任务。
- 后端入口为 `backend/app/`，前端为 `frontend/`；旧 `clms/`、`assets/app/`、`clms.html`、旧测试和旧数据不属于当前运行源码。
- `output/design/clms-icon/` 是已完成的独立设计产物，原位保留，未纳入旧修改 stash。0.10.0 的前端从这里精确复制 SVG/ICO/Apple touch icon 到 `frontend/public/icons/`，保留原图原色；运行时不读取 output。原设计目录仍不整体提交，不要用宽泛的 `git add .` 或 `git clean` 吸收或删除它。0.10.0 已于 2026-10-11 发布到生产。

## 当前生产身份与源码关系

2026-10-11 用户明确要求「发布生产啊」后，将审核中心固定提交 `969ad07626d315a83f7f0678ea98b39e3d188f24` 构建为独立 release，10:11:55（Asia/Shanghai）完成切换及健康核验：

- 服务：`clms.service`，版本 `0.10.1`；[审核中心](http://192.168.0.145:8473/#/reviews)。
- 发布目录：`/root/workspace/apps/clms-archive/releases/969ad07`；unit、实际进程工作目录与线上构建哈希均已核对。
- 持久数据：`/root/workspace/apps/clms-archive/data-archive`；原运行配置、管理员、MCP 凭据与会话沿用。
- 上一版 `6030883`（0.10.0）保留用于回退，迁移文件未变；生产只运行一个 CLMS 服务。
- 切换前私有冷备份：`/root/workspace/backups/clms/before-review-center-deploy-20261011-021153Z/`；原 unit、私有配置、完整数据归档、逐文件比对、完整解压及 SQLite 完整性/外键验证通过。
- 停服请求至健康核验 2.295 秒；发布摘要 `artifacts/review-center-ui/production-969ad07.json`，完整运维证据和实际截图在 `/root/workspace/apps/clms-archive/deployment/review-center-0.10.1-969ad07/`。

统一工程门禁已通过，固定提交的121个源码文件与门禁时工作树一致，锁定重建的前端与工程验收产物逐字节一致，原图标不变。生产20项 HTTP 检查和四种桌面/手机/主题登录布局通过，无控制台错误、请求失败、溢出或新增 warning/error 日志；数据库及认证行仍与冷备份一致。

没有管理员密码或生产 MCP secret，生产登录后的业务与真实凭据调用未复测；完整 F01–F08 与官方 SDK 协议已在临时库通过。真实外部 AI 和实体设备另行验收，不计入本次 DEPLOYED。

实际运行身份以 live unit、进程和 HTTP 为准。回退步骤见 `/root/workspace/apps/clms-archive/deployment/README.md`；最新状态 `status.json`，前一版身份保存在 `status.book-page-0.10.0.json`，更早的初次发布在 `status.initial-cutover.json`。原维护工作区、`output/` 与主分支保留，当前生产不从它们直接运行。

历史0.10.0发布提交 `6030883acc89b8ae0ccf5f403dd0d9956886de06` 的摘要仍为 `artifacts/book-page-ui/production-6030883.json`，当次备份 `/root/workspace/backups/clms/before-book-page-deploy-20261011-013833Z/` 保留。本次发布未修改 OMRS 或旧产品恢复资料。

## 旧主目录的完整保存

私有备份目录：

`/root/workspace/backups/clms/before-main-workspace-merge-20261011-081847/`

该目录保存：

- `legacy-main-workspace.tar.gz`：合并前完整主目录，包括 Git 元数据、未提交文件、旧 Ledger 和已有设计产物快照；`manifest.sha256` 为归档校验。
- `file-inventory.json`、`backup-verification.json`：逐文件校验和完整解压比对证据；解压后的旧 Ledger 已通过只读 SQLite integrity_check。
- `restored/clms/`：已验证的旧工作区完整解压副本。其 `.git` 只作为恢复资料，不应作为与原工作树共享操作的第二个活动仓库。
- `repository-with-legacy-stash.bundle`：完整 Git 历史与旧修改 stash，已经 `git bundle verify`；`merge-result.json` 记录 bundle 校验值和操作身份。
- `tracked-working.diff`、`tracked-index.diff`、`git-status-before.bin`：原修改基线。
- `legacy-residuals/`：新版合并后移出的旧 `clms/`、旧 `tests/` 缓存和 `语文/` 数据残留，不在新源码树内。
- `deployment-docs-before/`：本次修改前的生产定位文档副本。

旧源码修改另存为 stash 对象 `c813afbc089f748d9522b30e93c094562a00490f`。它只含旧版修改，不含原位保留的并行 `output/`。禁止直接在当前新版 `master` 上 `stash pop`；如需查看或恢复，应使用独立、私有、明确路径的旧版恢复工作区，不把 Ledger、OCR、调度或旧接口重新混入新版。

## 验证与后续操作

在正式源码目录运行锁定安装：

```bash
cd /root/workspace/apps/clms
uv sync --frozen
npm --prefix frontend ci
npm --prefix frontend run build
```

统一门禁仍是 `uv run --frozen python scripts/verify.py --all --report <独立证据目录>/verification.json`。本次新门禁报告放在上述备份目录的 `verification/` 下，不覆盖仓库中原工程验收证据。

本机 Chromium 的测试专用启动器为 `/root/workspace/apps/clms-archive/deployment/playwright-chromium.py`，保留 native `/dev/shm`；仅在测试进程中设置 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`，不能改变生产程序或放宽目录权限。测试使用临时新库与动态回环端口，不能复用生产数据目录或导入旧 Ledger。

本次源码合并、工程自动化、生产运行、外部 AI 与实体设备分别验收。旧交接文档中的“未部署”或“主工作区仍旧版”描述属于其原工程交付阶段，不能覆盖当前 live 证据与本页维护入口。
