# CLMS 作文档案馆开发索引

当前产品和实现要求见 `../AGENTS.md`、`../docs/architecture/contract.md` 与 `../docs/plans/essay-archive-rebuild/plan.md`。旧功能历史仅在 Git 历史和 changelog 中保留，不能按旧 Ledger、OCR 或调度说明扩展新系统。

## 按任务找文档

| 任务 | 先读 |
| --- | --- |
| 实体、快照、分类、版本、评价、事务与审核 | `data.md` → `../docs/architecture/contract.md` → `../docs/architecture/decisions.md` |
| MCP 工具、scope、提案、图像与客户端兼容 | `ai.md` → `api.md` |
| HTTP、登录、CSRF、媒体、CLI | `api.md` |
| 页面、阅读器、审核、响应式与主题 | `frontend.md` |
| 正式源码目录、生产发布身份、旧主目录与未提交修改恢复 | `../docs/operations/workspace.md` |
| 部署、备份、恢复、一次性旧数据清理 | `../docs/operations/workspace.md` → `../docs/operations/deployment.md` → `../docs/operations/cutover.md` |
| 验收与证据 | `../docs/plans/essay-archive-rebuild/acceptance.md` |
| 版本记录 | `changelog.md`（旧条目描述当时版本） |

## 代码到文档

| 代码 | 文档 |
| --- | --- |
| `backend/app/config.py`、`backend/app/main.py`、`backend/app/cli.py` | `api.md`、operations |
| `backend/app/db/`、`backend/migrations/`、`backend/app/domain/` | `data.md` |
| `backend/app/auth/`、`backend/app/api/` | `api.md` |
| `backend/app/media/` | `data.md`、`api.md`、`../docs/architecture/media.md` |
| `backend/app/mcp/`、`scripts/simulate_client.py` | `ai.md`、`api.md`、`../docs/mcp/tools.md` |
| `backend/app/mcp/uploads.py`、`body_limit.py` | `ai.md`「附件录入」、`../docs/architecture/media.md`、`../docs/mcp/tools.md` |
| `frontend/src/app/`、`frontend/src/shared/` | `frontend.md` |
| `frontend/public/icons/`、`frontend/index.html`、`frontend/src/shared/Brand.tsx`、`Icon.tsx`、`ReadingLayout.tsx` | `frontend.md`「书页档案设计语言」及阅读布局 |
| `frontend/src/features/archive/`、`submission/`、`document-viewer/`、`evaluation/` | `frontend.md` |
| `frontend/src/features/review-center/`、`categories/`、`settings/` | `frontend.md` |
| `review-center/reviewPresentation.ts`、`ProposalContent.tsx`、`PendingReviewBadge.tsx`、`shared/HelpTip.tsx` | `frontend.md`「审核中心可读提案草稿」；操作/影响、逐字段预览、真实待审数量、可访问气泡 |
| `backend/tests/`、`frontend/tests/`、`scripts/verify.py`、`scripts/browser_verify.py`、`scripts/clean_deploy_verify.py` | acceptance、operations |
| `scripts/legacy_cleanup.py`、`deploy/` | operations、legacy-removal |

OMRS 仅提供审核行为及旧视觉参考，不是运行依赖，不修改其代码或数据。

## 必需门禁

```bash
uv run --frozen python scripts/verify.py --all --report artifacts/verification.json
```

依赖缺失、必需测试 skip、零用例均不能通过。真实浏览器和真实 MCP SDK 网络测试是必需自动化项；模拟客户端不证明模型已理解图像，生产切换也必须独立记录。
