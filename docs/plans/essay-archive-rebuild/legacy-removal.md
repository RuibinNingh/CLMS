# 旧业务移除与替换清单

重构边界由 plan R03/R04明确授权。历史源码通过 Git保留，不复制到运行时 legacy 包，不迁移旧业务数据。实际差异以交付 commit 的 `git diff --stat`和旧接口拒绝测试为准。

逐文件删除记录：[removed-files.txt](removed-files.txt)。原工作区的未提交修改保持独立，删除仅发生在重构工作树。

| 原组件 | 新系统处理 |
| --- | --- |
| `clms/ledger.py`、projections、creation、drafts | 以新SQLite关系库、领域服务、不可变原件/版本与事务性审核替代；不重放Ledger |
| taxonomy、scheduling、sessions、records、review_ai | 用户自建作文分类/结构化评价替代；移除记忆曲线、复习、题型训练和复习AI |
| ai_assist、dictation、harness、agent、agent_draft、agent_ops | 移除内置模型、录入Agent、默写拆空；外部MCP只提交待审提案 |
| assistant、assistant_store、tool_catalog、http_assistant | 移除全局AI助手/供应商配置/聊天队列；官方MCP新工具目录 |
| essays、essays_projection、essays_ocr、essay_http | 重新实现题目/练习/稿件/评价，移除OCR/confirmed/60分强约束 |
| server、http_registry、http_legacy、http_upgrade、mcp_http | FastAPI严格Web API、独立会话/CSRF、官方MCP SDK挂载 |
| library、printing、source_export、runtime_history、history | 移除旧题库/打印/学习运行历史/导出功能；新审计只围绕作文档案与审核 |
| `assets/app/`旧页面/JS、`clms.html` | React/TypeScript/Vite，只有作文档案/审核/分类/设置；媒体仍鉴权 |
| `clms_engine.py`、run.sh、run.bat、旧CLI | 新 `backend.app.cli` init/serve/cleanup，无旧命令兼容 |
| 旧 `tests/`与fake_ai | 新pytest/前端单测/Playwright/真实官方SDK，关键用例不可skip；模拟评价不调用模型 |
| 旧requirements与部署手册 | 锁定 `uv.lock`/package-lock、新Docker/systemd/HTTPS配置 |
| AI/algorithm与旧开发说明 | 重建AI索引/data/api/ai/frontend；无调度算法当前说明；旧changelog条目仅历史 |

## 旧 API/MCP与数据

旧 `/api/state`、`/api/session/*`、`/api/drafts`、`/api/assistant`、OCR及模型配置不提供原功能。MCP仅暴露新作文工具，不能通过旧别名、通用execute/SQL/任意路由重获旧业务。

新库从空分类、空档案开始。没有确认生产路径或生产权限，故没有删除真实旧数据、迁移数据或改动目标生产实例。`scripts/legacy_cleanup.py`支持显式边界dry-run、清单变化检测、0600快照和核验后删除；测试只用临时CLMS目录，具体操作见 operations/cutover。
