# 一次性切换与回滚

本页是通用切换和清理流程，不代表当前生产状态。本机正式源码、生产定位与旧版恢复入口见 [工作区说明](workspace.md)。下面命令必须由有权限的操作者用核对后的绝对路径执行；路径示例不构成对真实目录的确认，也不授权停服或删除。OMRS 始终不在操作范围。

1. 记录旧服务启动命令/版本、监听端口、专属 CLMS 根及旧数据目录的规范化路径。停止旧服务，确认没有写入者。旧数据目录不能是用户主目录、项目根、共享素材根或 OMRS。
2. 建立新目录，按部署手册安装/迁移/启动新版本。验证登录、上传、下载原件哈希、MCP 权限、网页审核及重启持久化。旧路径不能被新服务引用。
3. 确认旧目录仅属于 CLMS，在其中手工建立 `.clms-legacy-data.json`，内容必须恰好为 `{"application":"CLMS","purpose":"legacy-data"}`。该步骤是操作者明确确认边界，不是启动自动识别。
4. 先运行 dry-run，审核逐文件清单、规范化 root、数量、容量及 SHA-256。

```bash
uv run --frozen python scripts/legacy_cleanup.py \
  --clms-root /confirmed/CLMS \
  --root /confirmed/CLMS/old-data \
  --manifest /private/operations/legacy-inventory.json
```

5. 停服状态保持到清理结束。执行必须复用完全一致的 dry-run 清单，精确重复规范化 root，并提供 CLMS 边界之外的新快照文件；工具在删除前创建 0600 tar 快照、核对每个文件哈希并再次核对目录清单。目录出现符号链接、特殊文件、清单变化或快照验证失败时不删除。

```bash
uv run --frozen python scripts/legacy_cleanup.py \
  --clms-root /confirmed/CLMS \
  --root /confirmed/CLMS/old-data \
  --manifest /private/operations/legacy-inventory.json \
  --execute --confirm-root /confirmed/CLMS/old-data \
  --snapshot /private/operations/legacy-rollback.tar.gz
```

6. 保存实际切换时间、版本、健康/重启结果、移除根、快照路径与快照哈希。快照只作工程回滚，不挂入新产品，也不构建旧版业务浏览页。稳定期结束由操作者按明确路径清理快照，当前任务不会自动删除。

## 回滚

停止新服务，保留新目录私有备份。恢复旧代码的已记录版本和旧启动配置；核对 tar 成员没有越界路径后将 `legacy-data/` 解压到独立恢复目录，检查清单哈希，再配置旧服务读取恢复目录。不要把旧库导入新 SQLite，不能用旧服务打开新数据目录。

回滚到旧版将无法展示新系统期间新增的作文/评价；新数据必须保留私有备份供重新切换。恢复后按记录重启旧服务、检查原业务；新旧两个写入服务不能同时指向同一数据目录。

## 演练证据

`backend/tests/test_cleanup_tool.py` 仅操作临时目录，验证 dry-run、范围、变化检测、快照与删除顺序。临时演练通过不代表真实旧数据已清理。实际生产环境缺失时将 DEPLOYED 保持未达成。
