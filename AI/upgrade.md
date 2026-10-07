# 0.8.0 升级与验收记录

本次对应附件中的完整升级目标。原始目录无 Git 元数据；按脱敏源码导出白名单记录源码基线 `f3c4e5407129f42c5b94a78b66a19bb1038b999a`，用户数据不进入 Git。原版本为 0.7.0，本次遵循次版本规则升至 0.8.0。

## 目标清单与依赖

1. 真正 A4 打印预览，创建复习后先预览。
2. 与答题区域同样式的浏览器答案测量；明确动作自动适配当前/全部。
3. 预览即时调行、重新分页、防抖永久写回默认留白。
4. 录入和题库编辑保留默认留白控件。
5. 持久全局助手，工具执行与轻量页面上下文。
6. 助手/MCP 共用审核中心，正式写操作人工决定并复核快照。
7. 可选官方 MCP SDK、独立 Key/scope/端口、幂等、安全边界。
8. 学习 Ledger 与系统运行分开的按日历史、筛选和对象跳转。
9. OMRS 风格分区设置、MCP Key 管理。
10. 作文 Prompt → Attempt → Version → Evaluation，原图/OCR/校对/确认/自由分类/笔记。
11. 共享领域业务、HTTP 注册表、兼容旧库、文档与源码包。

依赖：共享领域服务 → 审核 → 助手/MCP；作文领域 → 作文界面/助手/MCP；打印模板 → 预览/自动留白。三路汇合后完成历史、设置、兼容与验收。

## 开始前实际执行的基线

- `python3 -m unittest discover -s tests -q`：79 项，全部通过。
- `python3 tests/check_ui.py`：0 处问题。
- `python3 tests/e2e_main.py --shots /tmp/clms-baseline-shots`：PDF 浏览器路径和主路径通过。
- 参照相邻 OMRS 当前 Agent、AI Review、MCP/技术存储、runtime、settings、HTTP registry、shell/component 文档与实现。

## 已交付的行为

上述 11 项均已实现。创建复习后默认进入 A4 预览；手动和自动留白都会更新题目默认值。全局助手、审核中心、作文、历史成为一级页面，设置按外观、复习打印、AI 识别、AI 助手、外部 AI/MCP、数据、服务分区。

作文完整流程包括题目搜索、独立练习、多页上传一稿、逐字 OCR、人工校对确认、评价展示/采用、追加下一稿、文本增删对比、自由分类和讨论笔记。OCR 校对不增加版本，确认正文不可覆盖，旧评价始终留在被评价的版本。首版满分固定 60，不硬编码分项权重，作文不进入普通题目的记忆曲线。

## 关键架构与主要模块

| 范围 | 模块与决定 |
| --- | --- |
| 领域与审核 | `clms/domain_ops.py`、`clms/ai_review.py`、`clms/tool_catalog.py`；复用 `creation/sessions/records/drafts/essays`，工具 schema、权限与 scope 只有一份权威。正式 Session、改题/材料和录入 Agent 的高影响更正先提案。 |
| HTTP | `clms/http_registry.py`、`clms/http_legacy.py`、`clms/http_upgrade.py`、`clms/http_assistant.py`、`clms/essay_http.py`、`clms/mcp_http.py`；重复路由注册立即失败，`server.py` 专注传输。 |
| 打印 | `clms/printing.py`、`assets/app/domain/print-layout.js`、`features/review/preview*.js`；预览 iframe 与独立打印文档共享模板/CSS和分页代码。真实不可见答案等待字体、以相同宽度/字号/行高/换行规则排版测量，不用字数公式。 |
| 全局助手 | `clms/assistant.py`、`clms/assistant_store.py`、`features/assistant/`；复用 harness 和模型兼容层，持久会话、思考/工具/用量/结束状态，轻量页面编号以数据输入，不作为系统指令。 |
| MCP | `clms/mcp/{keys,authorization,http,images,server}.py`、`requirements-mcp.txt`；可选官方 SDK、独立本机端口、独立 Key、实时授权与原生图片输出，复用领域和审核。 |
| 作文 | `clms/essays.py`、`clms/essays_projection.py`、`clms/essays_ocr.py`、`features/essays/`；正式状态/正文/评价/关系只在 Ledger，图片沿用已有 `images/` 附件库。 |
| 历史 | `clms/history.py`、`clms/runtime_history.py`、`features/history/`；Ledger 学习与变更、脱敏系统运行分轨，按日分组、搜索/日期/来源/类型筛选和稳定对象跳转。 |
| 集成 | `features/audit/`、`features/settings/`、`core/router.js`、`shell.js`、`domain/object-links.js`；同一审核卡/中心共用服务端决定，深链接、键盘操作、卸载取消与过期回包保护。 |
| 源码与文档 | `clms/source_export.py` 覆盖新增模块，排除全部私有库/附件；README、全部相关 AI 文档及 AGENTS 映射同步，版本与 HTML 入口一致为 0.8.0。 |

正式写的回执与学习事件在同一个 Ledger SQLite 事务提交；草稿回执随草稿原子保存。审核库/助手库/运行库均不作为学习事实源。重启只凭精确原生回执恢复已成功结果，无回执的中断操作不猜测成功、不重新执行。

审核修订限定原请求已有字段，不能扩大模型写权限；批准再次检查 revision、内容快照及实时 MCP Key/scope。等待模型、网络和人工审核不持 Ledger 写锁。MCP 没有批准工具，Web 路由也在业务执行前拒绝 MCP 认证头。

留白控件范围统一为 0–1000。连续调整即时重绘并以 450ms 防抖持久化；刷新、打印、开始复习会提交待保存值。单纯打开预览不写题库；新 Session 使用更新后的默认留白。

## 原地升级与数据兼容

- 保留 `<vault>/语文/.clms/`，直接以新代码启动，不需清空、导入导出或重新编号。
- Ledger 的 `commits/counters` 及旧哈希链不重写；`operation_receipts` 通过可重复的 `CREATE TABLE IF NOT EXISTS` 增补。新作文编号使用独立前缀；没有作文事件的旧库投影得到空作文集合。
- `ai_review.db`、`assistant.db`、`runtime.db`、`mcp_keys.json` 按需初始化，与学习事实分开。启动恢复处理未完成助手/OCR及审核回执，不重启模型或重复写入。
- 草稿继续在 JSON 暂存层，只有原有整份 `entry.commit` 入库。原题库、录入 Agent、复习评分和现有复习记录路径保留。
- 当前真实库只做读取/校验：20 条提交链完整，仍为 9 道题、2 份材料、4 份 Session、0 个作文题；所有新增写入和浏览器验收均使用临时库。

## MCP scopes 与工具清单

完整参数、认证和部署说明见 `AI/api.md`「外部 AI / MCP」；schema、权限及假模型说明见 `AI/ai.md`「全局助手与公共工具目录」。共有 27 个 MCP 工具：18 个读取、9 个写入；内置助手共用其中 26 个，图片工具仅 MCP 提供。

| Scope | 工具或能力 |
| --- | --- |
| `clms:read` | `list_taxonomy`、`search_items`、`get_item`、`get_material`、`get_overview`、`get_recommendations`、`list_sessions`、`get_session`、`list_drafts`、`get_draft`、`get_operation` |
| `draft:create` | `create_draft`，自动暂存 |
| `draft:update` | `update_draft`，还须 `clms:read`，自动暂存且检查 revision |
| `session:create` | `create_review_session`，还须 `clms:read`，等待人工审核 |
| `question:propose` | `propose_item_update`，还须 `clms:read`，等待人工审核 |
| `material:propose` | `propose_material_update`，还须 `clms:read`，等待人工审核 |
| `essay:read` | `list_essay_prompts`、`get_essay_prompt`、`get_essay_attempt`、`get_essay_version`、`list_essay_evaluations`、`list_essay_classifications` |
| `essay:images` | `get_essay_image`，还须 `essay:read`，仅指定 Version 的对应原图 |
| `essay:evaluate` | `append_essay_evaluation`，还须 `essay:read`，自动追加 0–60 分评价 |
| `essay:note` | `append_essay_note`，还须 `essay:read`，自动追加讨论重点 |
| `essay:classify` | `create_essay_classification`；`set_essay_classifications` 还须 `essay:read`，自动追加自由分类 |

Key 明文只在创建时显示一次，磁盘仅 SHA-256 摘要和元数据，文件权限 0600。每次协议调用、工具前后、事务提交及人工批准实时重新授权。所有写工具须有 `request_id`；同身份同内容返回原结果，同编号不同内容冲突。没有任意文件读取、HTTP 转发、自批或删除正式数据的工具。

普通 Web 使用标准库，无需安装 MCP。启用时安装 `requirements-mcp.txt`，例如：

```bash
python3 -m pip install -r requirements-mcp.txt
python3 clms_engine.py --vault /path/to/vault serve --port 8472 --mcp-port 18473
```

设置创建 Key 后，客户端使用 `http://127.0.0.1:18473/mcp` 和独立 Bearer Key；缺少依赖时只影响启用 MCP，已有 Web/Key 管理正常使用。

## 实际执行的最终验证

| 命令 | 实际结果 |
| --- | --- |
| `python3 -m unittest discover -s tests -q` | 164 项，32.856 秒，全部通过，无跳过。 |
| `python3 tests/check_ui.py` | 0 处问题；页面契约、事件/DOM纪律、token、断点和文件行数门禁通过。 |
| `python3 tests/e2e_main.py --shots /tmp/clms-final-main-shots` | 旧录入/校对/入库、题库、复习评分、PDF处理、深色与手机主路径通过。 |
| `python3 tests/e2e_print.py` | A4尺寸、实际答案测量、当前/全部适配、中文/换行/超长内容、即时调行、防抖/刷新保存、新 Session 默认值、共享打印模板和PDF通过。 |
| `python3 tests/e2e_assistant.py` | 持久会话、实时思考/工具、中心修订后批准、实际 Session 返回、刷新恢复、375px及卸载晚回包保护通过。 |
| `python3 tests/e2e_essays.py` | 多页一版、OCR/校对确认、原文保留、多评价/采用、下一稿、差异高亮、自由分类、笔记、手机和卸载保护通过。 |
| `python3 tests/e2e_mcp.py` | 官方 `mcp==1.28.1` ClientSession 真 Streamable HTTP 初始化/发现/调用、原图、评价/笔记/分类、幂等/权限/吊销及 Session 人工批准通过。 |
| `python3 tests/e2e_upgrade.py` | SDK提案→网页批准→正式Session、审核修订/拒绝、47分原版本评价/笔记、分轨历史跳转、Key创建/修改/吊销、键盘、390px和晚回包保护通过。 |
| `python3 -m compileall -q clms tests`、`git diff --check` | 通过；最终暂存内容也通过 diff 格式检查。 |
| `python3 clms_engine.py verify` | 真实旧库20条提交哈希链完整。 |

后端异常验证包括：审核拒绝/过期/revision与内容冲突/并发重复批准/自批拒绝；Key到期吊销、发现与执行权限一致、等待锁后重授权、request冲突；辅助库失败后的原生回执恢复及回滚；助手写盘/改名/线程启动失败、未保存等待指针窗口、停止/重启/终态事件分页；OCR失败重试/旧token丢弃/校对版本冲突；多评价旧稿归属、正文不可覆盖、0–60边界和分类整体回滚。缺少可选 SDK 的导入/普通 Web 启动路径也通过隔离子进程测试。

## 真实浏览器人工验收 A–E

实际启动 CLMS 与本机确定性假模型，使用真实 Chromium 点击、输入、上传、刷新并检查截图。验收库为 `/tmp/clms-acceptance-qq1n3nbb`；模拟图片和假模型用于验证流程，不代表真实手写识别质量。临时服务已在验收后停止，真实用户库没有参与新增写入。

| 场景 | 实际观察 |
| --- | --- |
| A：打印 | Session创建后进入A4预览。长答案由7行自动适配为27行，手动+1到28行，立即重排为2页；刷新仍为28行。专项另检查同模板打印、PDF与新Session默认值。 |
| B：助手 | 输入“给我创建一份30分钟现代文复习”，助手选题并等待审核；中心显示题目/影响，人工批准后只创建一次 `S-0001`，重开会话显示实际完成结果。 |
| C：MCP | 官方客户端只得到 pending且没有批准工具；浏览器批准后查询得到 `S-0002`，同请求重查不重复创建。 |
| D：作文 | 一次上传3张模拟原图形成 `EV-000001`；OCR保留“一顺间”等原文，人工修正识别内容后确认仍为1版/修改0次。MCP读取正式全文、保存47/60评价与笔记；网页显示来源/分数/内容。再上传 `EV-000002` 后2版/修改1次，评价仍只在第一稿。 |
| E：历史 | 学习历史的作文评价打开原 `EV-000001`；系统运行的MCP Session调用可打开审核和正式Session。最终跨模块测试特别断言Session链接使用 `S-` 而非 operation ID。 |

人工截图在 `.playwright-mcp/acceptance-{preview,assistant,audit,mcp-session,essay-mcp}.png`，该目录已忽略、不进入源码包。专项截图/PDF分别在 `/tmp/clms-{final-main,print,assistant,essay,upgrade}-shots/`。已实际查看桌面助手、打印、作文和手机设置/作文渲染；键盘与移动视口专项通过，无页面卸载后重绘。

## 脱敏源码包与隐私证据

实际导出当前工作区：503个源码文件，加1份manifest；60个新增代码、测试和可选依赖文件全部收录，0遗漏，AGENTS映射全部覆盖。临时副本注入23个私有路径/符号链接，Ledger/config/drafts/作文原图/辅助数据库/MCP Key/日志/备份全部排除，私有哨兵0泄漏；配置识别Key、配置助手Key、`sk-…`、`clms_mcp_…` 四类模拟密钥均替换。

核验证据：`/tmp/clms-source-export-audit-k1l3d2dz/audit-result.json`。最终代码可在设置“数据与存储”或 `export-source` 重新导出，包含本交付文档；导出不依赖 Git。真实库、Key、运行DB及用户原图不进入 Git。

## 尚未实际验证

- 真实外网视觉/工具模型及真实手写作文识别质量；本次全部模型路径使用本机假模型。
- ChatGPT账户连接、外部HTTPS反向代理、公网Origin/Host部署；本地官方SDK协议已测。
- 实体手机的相机、软键盘和系统打印，Windows环境及实体打印机；桌面Chromium、375/390px视口和PDF已测。

## Git 与交付范围

源码基线为 `f3c4e5407129f42c5b94a78b66a19bb1038b999a`。本次交付提交标题为 `Upgrade CLMS to 0.8.0`，最终commit可通过 `git log -1 --oneline` 查看；相对基线涉及107个源码/文档/测试文件，主要范围见上表。无远程推送或部署。原目录自带的未跟踪 `SOURCE_EXPORT_MANIFEST.txt` 保留，不混入交付提交；浏览器和隐私审计临时产物不入Git。

## 未扩大处理的既有技术债

普通Web仍没有账户/PIN登录；手动监听非本机地址会向局域网开放既有人工接口。本次沿用默认127.0.0.1、同源POST和独立MCP认证，没有扩大为账户系统。README已明确此限制。
