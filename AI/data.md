# 数据：Ledger、投影、草稿、去重

> 速查：一切持久状态都在 `<vault>/语文/.clms/`。`ledger.db` 是唯一事实源（只追加）；草稿和原图是暂存；内存投影由 Ledger 增量重放得到。

## 目录

```
<vault>/语文/.clms/
  ledger.db          SQLite（WAL）：commits + counters
  config.json        设置（AI、复习日、时长、tuning、qtypes）
  drafts/D-*.json    录入草稿（不进 Ledger）
  images/<sha24>.<ext>  上传的原图（录入、复习助手里的作答照片），按内容哈希命名，重复上传自动合并
```

## Ledger（`clms/ledger.py`）

`commits(seq, commit_id, created_at, source, commit_type, message, payload, prev_hash, commit_hash)`

- `commit_id` 形如 `C-000001`；`commit_hash = sha256(prev_hash + created_at + source + commit_type + canonical_json(payload))`，第一条的 `prev_hash` 是 64 个 0。
- `counters(name, value)` 分配 `M-000001`（材料）、`Q-000001`（小题）、`S-0001`（复习）编号，和提交在同一事务里。
- 写入：`transact(vault, fn(tx))`，在 `fn` 里用 `tx.next_id(prefix)`、`tx.append(source, type, message, payload)`；抛异常就整体回滚（编号也回滚）。单条写入用 `append_commit()`。全局一把写锁。
- `verify_ledger()` 逐条重算哈希，返回 `{ok, count, error}`。

### 提交类型

| commit_type | payload | 说明 |
| --- | --- | --- |
| `entry.commit` | `{draft_id, images, materials:[…], items:[…], reencounters:[{item_id}]}` | 一份草稿入库。materials / items 是新建的；reencounters 是库里已有、这次又错了的题 |
| `item.update` | `{item_id, changes:{…}, key?}` | 改题（可改字段见 `creation.EDITABLE`）；改了题干或默写答案时带新的去重键，和别的题撞键会被拒绝 |
| `material.update` | `{material_id, changes:{title,author,source,text}}` | 改材料 |
| `item.suspend` | `{item_id, suspended}` | 停用 / 恢复（停用的题不排复习、不计入统计） |
| `item.delete` | `{item_id}` | 删除（投影里移到 `state.deleted`；提交仍在链上） |
| `item.restore` | `{item_id}` | 撤销删除（去重键没被别的题占用时才允许） |
| `session.create` | `{session_id, items:[{id}], minutes, planned_for, title}` | 安排一次复习 |
| `session.cancel` | `{session_id}` | 删除复习（先对其中的评分逐条写 `review.void`） |
| `review.grade` | `{session_id, item_id, grade, note, at?, replaces?, restored_from?}` | 评分 = 一条复习记录。session_id 可空（补记）；`at` 是补记 / 改记录 / 恢复时沿用的日期；`replaces` 指向被它改掉的记录，`restored_from` 指向被它恢复的记录 |
| `review.void` | `{commit_id}` | 作废某条评分；改评分 = void + 新 grade |

### 记录字段

材料：`id, genre, title, author, source, text, key, image`（投影另加 `created_at, item_ids, commit_id`）。

阅读小题：`id, material_id, genre, order, no, qtype, stem, answer, answer_origin, analysis, score, blank_lines, user_answer, note, key, image`。

默写小题：`id, material_id=null, genre="dictation", qtype(直接默写/理解性默写), stem(含 {书写区域}), answer, source, template(原模板), blank_lines=1, key, image`。

投影另加 `created_at, events[], suspended, commit_id, draft_id`。`events` 是 `{kind: review|reencounter, grade?, at, commit_id, session_id?}`，已作废的评分会被移除。

## 投影（`clms/projections.py`）

`get_state(vault)` 返回常驻内存的 `State`，每次调用先读 `seq > last_seq` 的新提交并应用。`reset_state()` 只给测试用。`item_view(id, ctx)` 在读的时候调用 `scheduling.derive()` 现算记忆状态（`sched`），并附 `material_title`、`encounters`（录入次数 = 1 + reencounter 数）。

## 去重

| 对象 | 精确键 | 模糊匹配 |
| --- | --- | --- |
| 阅读材料 | `mat:` + 原文汉字的哈希（≥ 8 个汉字才有键） | 同板块、长度比 ≥ 0.6、汉字二元组重合系数 ≥ 0.85，取最高者 |
| 阅读小题 | `item:<material_id>:` + 题干 `content_chars`（NFKC 后保留汉字、数字、字母）的哈希 | 同一材料下，长度比 ≥ 0.7、重合系数 ≥ 0.9 |
| 默写（每个空） | `dict:` + 答案汉字；答案不足 4 个汉字时再加 `|` + 题面汉字前 24 个 | 无 |

重合系数 = |A∩B| / min(|A|,|B|)，对「多一行标题」「几个字识别不同」不敏感。题干保留数字，所以「第③段」和「第⑤段」是两道题，「第③段」和「第3段」是同一道。

`creation.annotate()` 给草稿标注去重结果（前端显示「新 / 库中已有 / 本稿重复」）；`commit_draft()` 在同一事务里重新判断一次：库中已有 → 写进 reencounters；同一草稿里重复 → 跳过；新材料建 `M-`，新题建 `Q-`，命中已有材料时新题挂到它下面。

## 草稿（`clms/drafts.py`）

```json
{
  "id": "D-20260927-120501-ab12", "status": "ready",
  "images": ["<sha24>.jpg"], "hint": "",
  "messages": [ … ], "revisions": [{"n": 1, "at": "…", "source": "ai|manual|restore", "groups": [ … ]}],
  "error": "", "committed": null, "last_job": {"type": "extract"},
  "activity": {"started_at": "…", "finished_at": "…", "steps": [{"id": "model", "label": "调用识图模型", "kind": "model", "status": "done", "at": "…", "ended_at": "…"}]}
}
```

- 状态：上传后先 `staged`（准备：`pages = [{image, rotate, note}]` 排页序、旋转、每页说明，`images` 与之同序），「开始」后识图 `queued → extracting → ready`，对话修订 `queued → thinking → ready`；丢弃是 `discarded`（回收站，`discarded_from` 记原状态，可恢复，可彻底删除文件）；`name` 是用户起的名字；失败为 `error`（`last_job` 可重试）；终态 `committed` / `discarded`。服务启动时 `recover()` 把卡在处理中的草稿标成可重试的 `error`。
- `activity` 保存最近一次 AI 任务实际经过的阶段、状态和时间；阶段为排队、图片 / 上下文准备、模型请求、解析、保存。它属于草稿暂存层，不进入 Ledger。
- `groups` 的结构见 `ai.md`。每次 AI 修订、手工编辑、恢复都追加一个 revision，最多保留 40 版。
- 消息 `role`：`user`（文字 / 原图）、`ai`（`text, notes?, changes[], revision, base_revision?, error?, kind?`）、`edit`（手改或恢复，`changes[], revision, base_revision, merge?`，连续手改合并成一条）、`system`（入库结果）。`changes` 来自 `draft_schema.diff()`：`[{gid, iid, field, label}]`，field 为 `*` 表示新增、`-` 表示删除。
- 手工编辑带 `revision`（乐观锁）：AI 在这期间改过草稿，就拒绝并提示刷新。
- AI 任务在后台线程运行，并发上限 `config.ai_concurrency`（改配置后新任务立即按新值排队）。

## 复习记录（`clms/records.py`）

一条记录 = 一条 `review.grade`。投影 `state.reviews` 保存全部记录（含已作废，`voided_by` / `restored_by` 标记），`state.review_index` 只含有效的。增删改查全部落成已有的两种提交，没有新类型：

| 操作 | 写入 | 规则 |
| --- | --- | --- |
| 增（补记） | `review.grade`，可带 `at` | 可不属于任何复习；指定复习时题必须在其中且还没评过；日期不能晚于今天 |
| 改 | `review.void` 旧 + `review.grade` 新（同复习、同日期，`replaces`） | 只能改有效记录；评分与反馈都没变时不写 |
| 删 | `review.void` | 只能删有效记录 |
| 恢复 | （所在复习里这题已有别的有效评分时先 void 它）+ `review.grade`（`restored_from`） | 只能恢复已作废、且还没被恢复过的；所在复习已删除时拒绝 |

评分档按板块校验：阅读 0–3，默写 0 / 1 / 3。`sessions.grade_many` 在一个事务里写多题（Agent 批改用）。

查询（`list_records`）可按题、复习、板块、评分（low / mid / high 或分值）、起始日期、是否写了反馈筛选，`offset / limit` 分页；每条记录另附 `qtype`、`material_title`，供题库「复习记录」分页显示。复习助手采用的评分和反馈也只是普通的 `review.grade` / 「改」，没有新的提交类型。

## 草稿里的对话块（v0.3）

`messages` 是一串带 `id` 的块：`user`（`text, images, queued?, qid?, dropped?`）、`thinking`（`text, status: streaming/done`）、`assistant`（`text, status`）、`tool`（`call_id, name, label, args_text, args, result, summary, status: preparing/pending/running/done/error/stopped, tasks?, started_at, ended_at`）、`run`（`status: done/error/stopped, turns, tool_calls, seconds, changes?, revision?, base_revision?, text?`）、`edit`、`system`、`ai`（旧流程）。Agent 产生的块带 `run`；子代理的块带 `parent`（delegate 工具块的 id）与 `task`。进行中的逐字内容在 `live.py` 内存里，读草稿时盖上；服务重启后进行中的块由 `recover()` 收尾为出错。`agent.running = {run, kind, started_at}` 是正在执行的 run（前端计时用）。

## 草稿里的 Agent 字段

`kind`（extract / manual / chat / review）、`session_id`（review）、`agent: {messages, run, inbox, token, running, stats}`：

- `messages` 是模型上下文（OpenAI 形状，图片只存引用，思考不存进去）；`inbox` 是插话队列；`token` 是当前 run 的令牌（停止或结束时清空，旧 run 的写入按令牌作废）；`running = {run, kind, started_at}`。
- `stats = {turns, sub_turns, tool_calls, input_total, output_total, context, tps, ttft, estimated}`：累计用量，读草稿时再补上 `window`（设置 `ai_context_window`）。见 `ai.md`「模型接口」。
- 对话里给用户看的内容是 `messages` 顶层那串块（见上一节「草稿里的对话块」），不是这里的模型上下文。插话的用户块带 `queued` / `qid`，停止时没送达的标 `dropped`。一次 run 的所有改动只占一版 revision。
