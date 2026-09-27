# HTTP 接口与命令行

> 速查：`clms/server.py` 用 `@route(method, path)` 登记，每个端点一行；`ThreadingHTTPServer`，默认 `127.0.0.1:8472`。请求 / 响应都是 JSON（打印页和图片除外）。POST 校验 `Origin` 与 `Host` 一致，请求体上限 80MB。

## 错误约定

处理函数抛 `KeyError` → 404，`ValueError` → 400，其它异常 → 500（打印堆栈）。响应体 `{"error": "not_found|invalid|server|origin|too_large|bad_json", "msg": "给人看的中文说明"}`。前端 `core/api.js` 把 `msg` 作为 `error.message`。

## 端点

| 方法 路径 | 参数 | 返回 |
| --- | --- | --- |
| GET `/api/summary` | — | 概览统计（见 `algorithm.md`）+ `ai_ready`、`version` |
| GET `/api/taxonomy` | — | `{genres, qtypes:{genre:[题型]}}` |
| GET `/api/config` | — | 配置；密钥不回显，只给 `ai_api_key_set` |
| POST `/api/config` | 配置补丁；`ai_api_key` 留空表示不改，`clear_api_key: true` 清除 | 同 GET |
| GET `/api/activity` | `limit` | `{items:[{commit_id, created_at, type, message}]}` |
| GET `/api/ledger/verify` | — | `{ok, count, error}` |
| GET `/api/source/export` | — | 脱敏源码包 zip（`Content-Disposition` 带文件名，见下文） |
| GET `/api/drafts` | — | `{drafts:[{id,status,title,images,genres,error,committed,…}], ai_ready}`；未入库的在前，已入库的最多 12 份 |
| POST `/api/drafts` | `{images:[{name, data(dataURL 或 base64)}], combine, hint}`、`{manual: genre}`、`{chat: true}`（空白对话）或 `{images, review_session}`（复习作答照片交给 AI 批改） | `{drafts:[草稿视图]}`；每张一份，`combine` 时合成一份 |
| GET `/api/draft` | `id` | 草稿视图（见下） |
| POST `/api/draft/message` | `{id, text, with_image, images:[{name,data}]}` | 草稿视图；AI 在后台执行，状态变为 `thinking`。Agent 模式下 AI 正在执行时进插话队列（`queued` 计数），已入库的草稿也能继续聊 |
| POST `/api/draft/abort` | `{id}` | 草稿视图；停止正在执行的 Agent |
| POST `/api/draft/edit` | `{id, groups, revision}` | 草稿视图；`revision` 不是最新时 400 |
| POST `/api/draft/restore` | `{id, revision}` | 草稿视图（新增一版，内容等于目标版） |
| POST `/api/draft/retry` | `{id}` | 草稿视图（重跑 `last_job`） |
| POST `/api/draft/commit` | `{id}` | 草稿视图，`committed = {commit_id, created, reencountered, skipped, item_ids, material_ids}` |
| POST `/api/draft/discard` | `{id}` | `{id, status}` |
| GET `/api/image` | `id`（`<sha24>.<ext>`） | 图片字节，长缓存 |
| GET `/api/items` | `genre, qtype, status(新录入/巩固中/待攻克/已掌握/leech/deleted), q, sort(priority/due/mastery/created), suspended=1` | `{items, total, counts, deleted}` |
| GET `/api/item` | `id` | 小题 + `sched`、`events`、`records`（含已作废）、`material`、`siblings`、`deleted` |
| POST `/api/item/update` | `{id, changes}` | 小题详情 |
| POST `/api/item/suspend` | `{id, suspended}` | 小题详情 |
| POST `/api/item/delete` | `{id}` | 提交 |
| POST `/api/item/restore` | `{id}` | 小题详情（撤销删除；删除后又录入了同一道题时 400） |
| GET `/api/records` | `item_id, session_id, voided(1/0), limit` | `{records:[{commit_id, item_id, item_name, genre, session_id, grade, grade_label, note, at, voided, voided_by, restored_by, restored_from, replaces}], total}` |
| POST `/api/record/add` | `{item_id, grade, note, date, session_id}` | 记录（补记；`date` 不能晚于今天） |
| POST `/api/record/update` | `{commit_id, grade?, note?}` | 新记录（旧的作废） |
| POST `/api/record/delete` | `{commit_id}` | 记录（已作废） |
| POST `/api/record/restore` | `{commit_id}` | 新记录（恢复的） |
| GET `/api/material` | `id` | 材料 + 其下小题 |
| POST `/api/material/update` | `{id, changes}` | 材料详情 |
| POST `/api/sessions/plan` | `{minutes, genres[], fill}` | `{items:[{id, reason, minutes, item}], minutes, budget, due_total, due_left, horizon}`（不写 Ledger） |
| GET `/api/sessions` | — | `{sessions:[{id, planned_for, minutes, title, progress, genres}]}` |
| POST `/api/sessions` | `{item_ids, minutes, title}` | 复习视图 |
| GET `/api/session` | `id` | `{id, planned_for, progress, items:[小题 + grade], materials:{id: 材料}}` |
| POST `/api/session/grade` | `{session_id, item_id, grade, note}` | `{commit_id, session}`；已评过则先 void 再评 |
| POST `/api/session/ungrade` | `{session_id, item_id}` | 复习视图 |
| POST `/api/session/cancel` | `{id}` | `{id, cancelled}` |
| GET `/print/session` | `id, answers=1` | A4 打印页（自包含 HTML） |

静态文件：`/`、`/clms.html`、`/assets/**`（弱 ETag + `no-cache`）。

### 草稿视图

`{id, status, kind, session_id, agent, queued, created_at, updated_at, images, hint, messages, error, committed, revision, revisions:[{n, at, source}], groups, title, issues:[{gid, iid, message}], dedupe, activity, can_retry}`。`kind` 为 extract / manual / chat / review；`agent` 表示当前是否 Agent 模式。`activity = {started_at, finished_at, steps:[{id,label,kind,status,at,ended_at?}]}`，轮询草稿时可看到真实执行阶段。

`dedupe = {units, new_units, dup_units, groups:{gid: {material_match:{id,title,items}|null, items:{iid:{dup_item_id}}, dictation:{iid:[{blank, key, dup_item_id, dup_in_draft}]}}}}`。

## 打印（`clms/printing.py`）

材料按篇排：标题、作者 / 出处、原文（古诗居中），接着是该篇的小题：题号、题型标签、题干、分值、按 `blank_lines` 画的 9mm 答题横线。默写集中在最后，同一模板的几个空合成一行。`answers=1` 时另起一页列答案（`<li value=题号>`）。页面右上角有「打印」按钮，打印时隐藏。

## 脱敏源码包（`clms/source_export.py`）

设置页「导出脱敏源代码」与 `export-source` 命令共用。不依赖 Git：从程序目录收集根目录项目文件（`AGENTS.md`、`README.md`、`clms.html`、`clms_engine.py`、`run.*`、`.gitignore`）和 `AI/`、`assets/`、`clms/`、`deploy/`、`tests/` 下的源码类型文件（含未提交的改动）；跳过 `语文/`、`.clms`、`__pycache__`、隐藏文件 / 目录、符号链接、日志、备份、`.db`、`config.json` 和之前导出的包。文本文件里的当前 `ai_api_key` 与形如 `sk-…` 的串替换成 `<已脱敏>`。zip 顶层目录 `CLMS/`，附 `SOURCE_EXPORT_MANIFEST.txt`（规则、时间、文件数、脱敏替换了哪些文件、文件清单）。文件名 `CLMS-source-sanitized-<UTC 时间>.zip`。

## 命令行（`clms/cli.py`）

`python3 clms_engine.py [--vault 目录] {serve [-p 端口] [--host 地址] [--open] | stats | verify | export-source [-o 目录]}`。`serve` 启动时先 `drafts.recover()`；监听非本机地址时打印警告。

`verify` 在控制台用 `[OK]` / `[FAIL]` 报告结果，避免 Windows GBK 控制台无法编码特殊符号而在输出时崩溃。
