# CLMS 开发文档索引

## 按任务找文档

| 要做的事 | 先读 |
| --- | --- |
| 改数据结构、加提交类型、改去重、改入库 | `data.md` |
| 改用户题型、旧库题型迁移、未分类 | `data.md` → `algorithm.md` → `ai.md` → `api.md` → `frontend.md` |
| 改复习节奏、评分档、记忆类型（记忆型 / 理解型）、排复习的推荐规则与理由、估时 | `algorithm.md` |
| 改 AI 提示词、草稿结构、默写模板格式、对话修订 | `ai.md` |
| 改复习助手（评分页右侧的只读 AI：按需查题和原文、引用、提问、打分、写反馈） | `ai.md`「复习助手」、`api.md`「复习助手」、`frontend.md`「复习页」 |
| 改 Agent harness、工具、子代理委派、插话 / 停止 | `ai.md`「Agent harness」 |
| 改复习记录的增删改查、删除后恢复 | `data.md`「复习记录」 |
| 改脱敏源码导出 | `api.md`「脱敏源码包」 |
| 加 / 改 HTTP 接口、题库查询（分面、分组、分页）、打印卷面、命令行 | `api.md` |
| 改界面、页面路由与上下文、设置分区、手机布局、样式 token | `frontend.md` |
| 改服务状态、设置页重启、CLI 生命周期 | `api.md`「服务状态与重启」「命令行」→ `frontend.md`「其它页面」 |
| 改 A4 预览、答案实际测量、默认留白批量回写 | `api.md`「打印」→ `frontend.md`「复习页」 |
| 改全局助手、公共工具 schema / 权限 / scope | `ai.md`「全局助手与公共工具目录」→ `api.md` |
| 改统一审核、快照冲突、幂等回执与启动恢复 | `data.md`「统一领域操作与审核」→ `ai.md` → `api.md` |
| 改 MCP Key、实时授权、独立服务与官方 SDK | `api.md`「MCP」→ `ai.md` |
| 改作文数据、OCR、校对确认、评价与分类 | `data.md`「完整作文」→ `ai.md` → `api.md` → `frontend.md`「作文」 |
| 改学习 / 系统运行历史、脱敏与对象定位 | `data.md`「辅助运行存储与历史」→ `frontend.md`「历史记录」 |
| 看版本变化 | `changelog.md` |

## 与 OMRS 的对应

| OMRS | CLMS | 说明 |
| --- | --- | --- |
| `错题/.omrs/ledger.db` | `语文/.clms/ledger.db` | 同样的哈希链提交表与编号计数器 |
| 题目 Markdown 文件 | Ledger 提交的 payload | 语文题没有公式和手绘图，内容直接存在提交里，省掉文件与索引同步 |
| inbox 收件箱 | `drafts/*.json` 草稿 | 暂存层，不进 Ledger；多了多轮对话与版本（revision） |
| HTTP registry / 领域适配 | `http_registry.py` / `http_legacy.py` / 分模块 HTTP 适配 | 唯一路由注册，重复注册立即失败；Web 只处理传输 |
| AI Review / 公共领域服务 | `ai_review.py` / `domain_ops.py` / `tool_catalog.py` | 人工 Web、录入 Agent、全局助手、MCP 共用原有业务；模型正式写操作服务端审核 |
| MCP Key 与独立服务 | `clms/mcp/` / `mcp_http.py` | 可选官方 SDK、实时 scope、原生幂等回执；没有自批准工具 |
| runtime / 全局助手持久库 | `runtime_history.py` / `assistant_store.py` | 与学习 Ledger 分离，运行只存脱敏摘要；模型会话单独保存 |
| 0–10 分自评 | 四档（默写三档） | 更贴近语文主观题的采分点感觉 |
| 历史页 review.replace / retract / restore | 复习记录增删改查（void + grade，见 `data.md`） | 不新增提交类型，改 / 撤销 / 恢复都落成已有的 grade 与 void |
| `source_export.py` 脱敏源码包 | 同名模块 + 设置页按钮 + `export-source` 命令 | 另把当前模型 Key 与 `sk-…` / `clms_mcp_…` 串替换掉 |
| Agent 循环与工具 | 共享 `harness.Agent` 与模型兼容层 | 录入按大题委派；全局助手持久聊天及等待审核 |
| 每天复习 | 复习日（默认周二 / 五 / 日），到期日对齐复习日 | 低频复习 |
| `assets/app/{core,ui,domain,features}` + `check_ui.py` | 同左 | 核心模块（html / dom / events / router / store / bus / api）直接沿用 |

## 门禁

```bash
python3 -m unittest discover -s tests -q   # tests/test_core.py：去重、提交链、调度、入库、复习、HTTP 全流程
python3 tests/check_ui.py                  # 前端纪律 R1–R9
CLMS_TODAY=2026-10-06 python3 tests/e2e_main.py  # 真浏览器旧主路径与统一审核，固定复习日（周二）
python3 tests/e2e_http_upload.py           # 真非安全 HTTP：PNG/PDF 暂存、进度、加页、入队异常、重试与安全上下文
python3 tests/e2e_pdf.py                   # 真 PDF.js 专项（e2e_main 也包含）：拆页、管理器、重试、取消、手机
python3 tests/e2e_service.py              # 设置页取消/确认重启、真实进程重载、超时/离页与手机布局
python3 tests/e2e_print.py                 # A4实际测量、持久默认留白、打印一致性
python3 tests/e2e_essays.py                # 真浏览器作文OCR/校对/版本/评价
python3 tests/e2e_upgrade.py               # 审核修订、历史跳转、设置Key与生命周期
python3 tests/e2e_assistant.py             # 真浏览器全局助手、人工审核与持久会话
python3 tests/e2e_mcp.py                   # 可选SDK真实Streamable HTTP协议
```

`e2e_main.py` 的「今天刚复习过」题数断言需要固定复习日；使用上面的 `CLMS_TODAY`，避免非复习日排期到下一复习日改变题数。截图可加 `--shots <隔离输出目录>`；临时 vault 跟随 `TMPDIR`。`e2e_http_upload.py` 用 Chromium 原生共享内存（保留 `/dev/shm`，不使用 Playwright 默认的 `--disable-dev-shm-usage`），以避免受限 HOME 下 renderer 无权写临时共享文件。

`tests/test_review.py` 覆盖两种记忆类型、推荐（自选 / 移除 / 未完成复习 / 薄弱题型 / 最近做过）、题库分面与分组、复习历史筛选、复习助手（只读 Agent 按需调用工具而不是整篇注入——检查发给模型的每一轮请求里带了什么、没带什么；段号范围与关键词、范围限定在这次复习；引用带位置；照片跨轮仍发原图；建议解析；流式块；关掉 Agent 模式时的旧做法）。`tests/test_taxonomy.py` 覆盖空库、增改删排序、记忆类型、旧库迁移、未分类、AI 和 Agent 的陌生题型约束。`tests/test_agent.py` 覆盖 harness（工具出错回给模型、截断不执行、旧图省略、插话、停止）、草稿工具、复习记录增删改查、脱敏导出，以及 Agent 模式的 HTTP 全流程。`tests/fake_ai.py` 是 OpenAI 兼容的假模型（带 `tools` 的请求扮演确定性的工具调用 Agent，包括复习助手；`REQUESTS` 记着最近的请求体）：识图请求轮流返回三套草稿（现代文《老街的灯》+ 默写、古诗《山居秋暝》+ 标点不同的重复默写、文言文《咏雪》），修订请求能听懂「第 N 题 + 答案 / 题型 / 留白」。环境变量 `FAKE_AI_UNKNOWN_QTYPE=1` 会故意提交陌生题型；`FAKE_AI_DELAY=秒` 模拟慢模型；`FAKE_AI_STREAM_DELAY=秒` 控制流式每片的间隔（e2e 默认 0.02，观察流式那一步临时放慢到 0.12）；`FAKE_AI_NO_STREAM_OPTIONS=1` 让假模型拒绝 `stream_options`（测试用量回退到估算）；`CLMS_TODAY=YYYY-MM-DD` 可以固定「今天」。

专项后端：`test_service.py` 覆盖重启同源门禁、服务实例隔离、重复请求、真实 CLI 重载、持久数据和中断草稿恢复；`test_ai_review.py` 覆盖拒绝、过期、revision/内容冲突、重复决定、原生回执崩溃恢复与草稿不进 Ledger；`test_print.py` 覆盖批量留白的全事务校验；`test_essays.py` 覆盖完整作文事件、正文不可变及版本评价归属；`test_history.py` 覆盖筛选分页、模型来源、旧事件及源码隐私；`test_mcp_keys.py` / `test_mcp.py` 覆盖 Key 摘要、实时 scope、到期吊销、幂等与授权发现；`test_assistant.py` 覆盖持久运行与公共目录。SDK 未装时相关 SDK 单测跳过，普通 Web/Key 管理仍要通过。浏览器专项使用临时库和本机确定性假模型；不等同于真实模型、外部账户或实体手机测试。
