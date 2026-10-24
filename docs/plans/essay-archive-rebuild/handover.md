# 重构工程交接（历史验收记录）

CLMS 0.9.0 已重建为中英作文档案馆，交付等级 **ENGINEERING_COMPLETE**。代码提交 `de292c9b632fd08e7a033f0684d12f0c0a87f048`，分支 `codex/essay-archive-rebuild`；最终证据与文档在后续提交归档，运行代码保持该提交一致。工作树 `/root/.codex/worktrees/essay-archive-rebuild/clms`。

## 当前维护入口

2026-10-11 经用户授权，重构提交 `cbbe05b` 已快进合入 `/root/workspace/apps/clms` 的 `master`。后续开发从该主目录开始；原 Codex 工作树保留但不是默认维护入口。旧主目录、未提交修改和旧数据已私有归档；源码/生产/恢复分工见 [工作区说明](../../operations/workspace.md)。

以下工程验收、当时未执行项目和原工作区保留描述均为原交付阶段记录，不是本机当前部署状态。生产部署证据与 live 核验入口为 `/root/workspace/apps/clms-archive/deployment/README.md`。

## 已可使用的流程

新库空分类 → 自建分类/题目（纯图片或PDF材料合法）→ 混合原稿上传、页排序/旋转 → 不可变入档 → 官方MCP按页读图、提交pending提案 → 网页看原稿、修订、通过并入档或驳回 → 精确版本评价历史。上传修改稿建立同一练习V2；同题重新写一篇建立独立Attempt/V1；支持双稿查看、教师评价、反思/选定定稿、过滤检索与作废留史。

审核与正式业务同库事务，CAS/有效摘要/目标基线防覆盖；重复请求与重复批准不重复写入；提交前后崩溃、重启pending、撤销凭据和scope变化均已验证。Web会话/同源/CSRF与MCP密钥分离，MCP没有批准、凭据管理或任意执行权限。

旧 `clms/`、`assets/`、旧页面/API/MCP/CLI、题库/Ledger/默写/调度/内置模型/OCR与旧测试已从此分支移除，替换为FastAPI、SQLite迁移、官方MCP SDK、React/TS/Vite及新测试。逐文件清单见 legacy-removal.md/removed-files.txt。没有运行时兼容包或旧数据迁移。原用户工作区保留全部未提交修改，主分支没有改写；OMRS只读参考。

## 实际验证

`uv run --frozen python scripts/verify.py --all --report artifacts/verification.json` 对代码提交执行退出0，九项全部pass：

| 门禁 | 结果/证据 |
| --- | --- |
| 后端 | 83项，无skip；backend.xml/log |
| 前端类型、单测、构建 | 退出0；17单测，无skip；frontend.xml及日志 |
| 依赖审计 | 退出0，所有严重等级均0；dependency-audit.log |
| 真浏览器 | 3条综合流程，无skip/flaky；F01–F08与28张明暗/四视口截图 |
| 真TCP MCP | 官方SDK6项，无skip；mcp.xml/log |
| 安全 | 23项，无skip；security.xml/log |
| 干净部署 | 锁定安装、迁移/构建/启动/上传/评价、进程重启及原件哈希一致；clean-deployment/report.json |

主报告记录源码commit、开始/结束时间、环境、命令、退出码与证据路径；采样时工作区干净。MCP和安全测试也包含在后端83项内，不应相加为独立用例总数。

统一门禁浏览器使用匹配Chromium1194完整版的显式路径；最初默认headless未安装导致的失败报告单独保留，未冒充通过。安装后默认无override浏览器补验也3/3通过，证据 default-browser-ready/browser/playwright.json。实际查看桌面、两种平板、手机的明暗截图；响应式浏览器模拟不等于实体设备。

额外执行 `uv run --frozen python scripts/docker_verify.py --build`：实际镜像 `sha256:4ed7bd200e845a1f4be3b904d6e80816f6a3bbf5c7d9656c48b8f24fb95ca842` 构建、UID10001非root/只读容器、持久数据卷与原件SHA/重启均通过，临时容器与卷已清理。不是用户生产部署。Ruff与git diff检查退出0。

## 启动与模拟自测

在正式主工作区按根 README 的锁定安装/迁移命令启动独立开发实例；不要指向生产或旧数据目录：

```bash
cd /root/workspace/apps/clms
./run.sh
```

默认访问 `http://127.0.0.1:18474`，在本机读取新数据目录的bootstrap.token，网页设置管理员。不要用旧数据目录。README显式uvicorn/容器例子使用8472，改变端口时同步设置CLMS_PUBLIC_ORIGIN；HTTPS启用Secure Cookie。

设置页创建独立MCP测试密钥，放入当前进程CLMS_MCP_TOKEN环境变量，然后运行：

```bash
uv run --frozen python scripts/simulate_client.py \
  --endpoint http://127.0.0.1:18474/mcp/ --version-id <网页复制的版本ID> \
  --request-id simulation-1
```

脚本解码真实图片/PDF派生页，读取冻结快照，提交明确标为模拟的无分数评价；可加 `--category 模拟分类` 提交分类提案。然后由人到网页审核，脚本不能批准。

## 未执行与后续条件

用户选择先模拟；未调用真实模型，因此E01–E05的实际外部AI验收未达成，不能标 **ACCEPTED**。受控Bearer接入不是通用OAuth授权承诺；补验需实际客户端/模型的鉴权与图片消费证据，步骤见external-client-verification.md。

实体平板/手机、目标生产切换、真实旧业务数据删除均未执行，不能标 **DEPLOYED**。没有确认的生产目标或CLMS专属旧路径；清理只在临时目录演练。后续停服、核对路径、dry-run、受保护快照和回滚按operations/cutover.md。新库与原件备份按operations/deployment.md；私人作文、真实Token/Cookie不得提交。
