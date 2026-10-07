# 数据：Ledger、投影、草稿、去重

> 速查：一切持久状态都在 `<vault>/语文/.clms/`。`ledger.db` 是唯一学习事实源（只追加）；录入草稿是暂存，原图是按内容哈希保存的附件，正式归属由 Ledger 决定；内存投影由 Ledger 增量重放得到。

## 目录

```
<vault>/语文/.clms/
  ledger.db          SQLite（WAL）：commits + counters + operation_receipts
  config.json        设置（AI、复习日、时长、tuning、qtypes、qtype_kinds）
  drafts/D-*.json    录入草稿（不进 Ledger）
  images/<sha24>.<ext>  上传的原图（录入、复习作答、作文），按内容哈希命名，重复上传自动合并
  ai_review.db       原始请求、人工修订/决定、快照与执行结果（私有辅助库）
  assistant.db       全局助手会话、模型上下文、块事件与运行状态（私有辅助库）
  runtime.db         脱敏运行摘要（不保存学习全文/聊天/原图/密钥）
  mcp_keys.json      MCP Key SHA256摘要、scope、到期/吊销元数据（明文不保存）
```

## Ledger（`clms/ledger.py`）

`commits(seq, commit_id, created_at, source, commit_type, message, payload, prev_hash, commit_hash)`

- `commit_id` 形如 `C-000001`；`commit_hash = sha256(prev_hash + created_at + source + commit_type + canonical_json(payload))`，第一条的 `prev_hash` 是 64 个 0。
- `counters(name, value)` 分配 `M-000001`（材料）、`Q-000001`（小题）、`S-0001`（复习）编号，和提交在同一事务里。
- 作文沿用同一计数器和事务，按需分配 `EP-`（作文题）、`EA-`（独立练习）、`EV-`（稿件）、`EE-`（评价）、`EN-`（笔记）、`EC-`（自由分类），均为六位序号；不改变原有材料、题目和 Session 编号。
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
| `essay.prompt.create` | `{prompt:{id,title,text,requirements,source,metadata,practice_type,max_score}}` | 新建完整作文题；`practice_type=complete`、满分固定 60 |
| `essay.attempt.create` | `{attempt:{id,prompt_id,title,source,metadata}}` | 同一作文题下新建一次独立练习 |
| `essay.version.create` | `{version:{id,attempt_id,prompt_id,number,images[],source,metadata}}` | 同一次练习上传下一稿，多张图片只建一个稿件版本 |
| `essay.version.ocr.start` | `{version_id,token}` | 开始一次转写，令牌限定本次后台任务 |
| `essay.version.ocr.result` | `{version_id,text,raw_response,uncertainties[],model}` | 保存原始 OCR 全文、完整模型回复和存疑处，进入人工校对 |
| `essay.version.ocr.failed` | `{version_id,error}` | 转写失败或服务重启中断，原版本可重试 |
| `essay.version.correct` | `{version_id,text}` | 修改待确认的校对文本，不创建新稿件 |
| `essay.version.confirm` | `{version_id,text}` | 确认不可覆盖的正式正文，后续重写必须创建新稿件 |
| `essay.evaluation.add` | `{evaluation:{id,version_id,attempt_id,prompt_id,total_score,max_score,summary,strengths[],issues[],suggestions[],dimensions,evaluator,source,model,metadata}}` | 追加一份 0–60 分评价，永久绑定被评价的版本 |
| `essay.evaluation.adopt` | `{version_id,evaluation_id}` | 选择该版本当前采用的评价，保留所有旧评价 |
| `essay.note.add` | `{note:{id,attempt_id,prompt_id,version_id?,text,source,metadata}}` | 追加讨论笔记或下一稿重点，可关联某一版本 |
| `essay.classification.create` | `{classification:{id,name,group,source,metadata}}` | 创建自由分类实体，`group` 可空且没有预定义必选组 |
| `essay.classification.assign` | `{target_type,target_id,classification_ids[],metadata}` | 为作文题、练习或稿件追加组合分类；已有分类不会被覆盖 |

### 记录字段

材料：`id, genre, title, author, source, text, key, image`（投影另加 `created_at, item_ids, commit_id`）。

阅读小题：`id, material_id, genre, order, no, qtype, stem, answer, answer_origin, analysis, score, blank_lines, user_answer, note, key, image`。

默写小题：`id, material_id=null, genre="dictation", qtype(直接默写/理解性默写), stem(含 {书写区域}), answer, source, template(原模板), blank_lines=1, key, image`。

投影另加 `created_at, events[], suspended, commit_id, draft_id`。`events` 是 `{kind: review|reencounter, grade?, at, commit_id, session_id?}`，已作废的评分会被移除。

### 题型配置与迁移

阅读题的 `qtype=""` 是正式的「未分类」状态，允许入库、排普通到期复习，也可在题库筛出再编辑；不参与薄弱题型统计。非空题型必须属于该板块用户题型表。题型配置在 `config.json`：`qtypes={modern:[…],classical:[…],poetry:[…]}` 按顺序存名称，`qtype_kinds={modern:{名称:skill|recall},…}` 存记忆语义；名句默写的直接 / 理解性默写是固定结构，不归用户题型管理。新库三个阅读板块均为空表，删光后仍为空。第一次读取旧库时，如果配置的 `qtype_initialized` 不为 true，就扫描现存及已删除题中实际使用的非空题型，按板块去重写入配置并标记已初始化；只给旧文言「实词解释题 / 虚词题 / 文化常识题」保留 `recall`，其余为 `skill`，不带入未使用的预置题型，不写 Ledger。配置中已有用户题型时保留，并补齐实际使用项。

题型新增、排序、记忆类型切换只改配置。重命名先在配置中登记新名称与原记忆类型，并保存 `qtype_migration` 进度标记，再对包括已删除题在内的旧题逐条追加 `item.update`，最后删除旧名称和进度标记；中断后可重试。删除仍被使用的题型时必须显式选择同板块目标或空字符串（未分类），逐题追加 `item.update` 后才移除配置。投影对已删除题同样应用 `item.update`，以免恢复后出现幽灵题型；复习记录查询读取题目的当前题型。`commit_draft`、`update_item` 与题型管理共用一把进程内锁，避免题目在旧题型迁移完成后才落入 Ledger。

## 投影（`clms/projections.py`）

`get_state(vault)` 返回常驻内存的 `State`，每次调用先读 `seq > last_seq` 的新提交并应用。`reset_state()` 只给测试用。`item_view(id, ctx)` 在读的时候调用 `scheduling.derive()` 现算记忆状态（`sched`），并附 `material_title`、`encounters`（录入次数 = 1 + reencounter 数）。

## 完整作文（`clms/essays.py`、`clms/essays_projection.py`）

作文使用独立领域关系：**Prompt → Attempt → 多个 Version → 每个 Version 的多份 Evaluation**。同一题可以写多次独立练习；一次练习的一版作文允许 1–30 张有序原图，整次上传只创建一个 `Version`。页面的修改次数为 `max(0, version_count - 1)`，人工修正 OCR 不增加版本数。作文不进入 `state.items` / `state.sessions`，不写普通评分或 `sched`，不套记忆曲线。

`State` 继承 `EssayProjection`，初始化 `essay_prompts`、`essay_attempts`、`essay_versions`、`essay_evaluations`、`essay_notes`、`essay_classifications` 六张内存字典。每种作文事件都有 `_on_essay_*` 处理器，投影保存父子 ID 数组而非另一份数据库；`essays.py` 在读取时组装页面详情，并返回深复制，调用方修改返回对象不会改写投影。

### 原图、转写与正文

上传先在已有 `images/` 内容库保存原图，再在短 Ledger 事务中写 `essay.version.create` 和原图引用。解码、文件保存不持 Ledger 写锁；即使后续领域校验失败，孤立图片也不构成学习事实。原图读取只能使用指定版本实际包含的图片，不能提交任意本地路径。

版本流程为 `uploaded → ocr_running → proofreading → confirmed`；OCR 异常为 `ocr_failed`，重试仍是同一个 `EV-`。后台任务在开始时追加令牌，在模型请求结束后重新检查状态与令牌，旧任务结果不能覆盖重试结果。服务启动的 `essays_ocr.recover()` 把上个进程留下的 `ocr_running` 追加为可重试失败；恢复不调用模型。OCR 运行摘要单独记录在 runtime，学习状态以 Ledger 为准。

四个文本字段职责不同：`raw_ocr_text` 保存原始转写，`raw_ocr_response` 保存完整模型回复，`corrected_text` 保存人工校对内容，`text` 只保存确认后的正式全文。OCR 不润色，原作文的错字、病句和标点应原样保留，识别不清写存疑标记并另存 `uncertainties`。校对也只修识别错误。可以在未确认且没有运行中的 OCR 时手工转写；它仍只追加校对事件。

OCR 和校对状态事件增加整数 `revision`。网页校对/确认可带当前 revision，旧页面提交被拒绝；确认后再校对或重跑 OCR 均被拒绝。同样内容的重复确认只返回已有版本，不再提交；不同正文的再次确认被拒绝。评价操作只追加评价和评价 ID，永远不修改正式正文。

### 评价、笔记与自由分类

评价分数必须是有限数字且在闭区间 0–60，固定保存 `max_score=60`，不硬编码分项或权重。`dimensions` 可保存自由 JSON 结构；其它必要字段为摘要、优点/问题/建议数组、评价者、来源、模型及创建时间。评价只允许正式确认后追加，多份评价分别拥有 `EE-`，上传下一稿不会迁移旧评价。采用评价只改当前版本的 `adopted_evaluation_id`，且该评价必须属于同一版本。

讨论笔记拥有 `EN-`，归属一次练习，可选关联该练习中的具体 `EV-`；跨练习的版本关联会被拒绝。只保存明确选择的讨论结论或修改重点，不默认保存完整聊天。评价和笔记没有覆盖或删除接口。内置助手与 MCP 共用 `domain_ops` 的同一领域函数与原子 receipt；外部来源由服务端操作上下文绑定，模型不能通过参数冒充网页来源。

分类实体拥有 `EC-`，保存自由 `name`、可选 `group`、`source`、`metadata`；没有写死文体/主题/问题三棵树。相同名称和分组复用同一实体，不同自由分组可以有同名实体。组合分类可以按现有 ID 或新名称添加到 Prompt / Attempt / Version，创建新分类和追加归属在同一个 Ledger 事务中完成，任一参数失败整体回滚。分类来源保留在实体创建事件和归属提交中。各作文对象均可保存自由 `metadata`；网页题目出处使用 `metadata.origin`，上传原页名使用 `metadata.page_names`。

### 旧库兼容

不迁移、不清空旧 Ledger，不修改任何旧提交或原 ID。没有作文事件的旧库重放后得到六张空字典，原题库和复习继续可用；首次作文写入只按需分配新计数器。所有正文和关系均在现有 Ledger 中，原图仍是已有内容附件库；恢复投影可重复执行，不依赖辅助库保存作文学习事实。

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

## 统一领域操作与审核

`domain_ops.py` 把共享预览/校验/快照/执行/回执恢复组成工具规格；`creation`、`sessions`、`records`、`drafts`、`essays` 仍是原有领域实现。Web 人工操作直接调用对应领域业务；模型正式写操作必须经 `ai_review.propose()`，不能只依赖提示词。分类：read 自动读；草稿创建/修改、作文评价/笔记/自由分类 auto 执行并留痕；正式 Session、题目/材料修改以及录入 Agent 的停用/删除/恢复、旧评分更正均 confirm。

`ai_review.db` 保存操作身份、原始/有效摘要、原始/有效 payload、显示预览、内容 snapshot、可修订字段、状态、revision、创建/到期时间、result/commits；修订与人工决定单独保存。幂等身份来自 source + tool + Key/会话身份 + request_id。相同请求返回原操作，不同原请求内容报 `request_conflict`；人工修订不改变原始摘要，重试不能覆盖人工决定。修订只允许最初请求已有的开放字段；Session 不允许修订题目集合。批准由 Web 固定 human reviewer，并校验 expected_revision；模型/MCP没有自批准工具。

提案 `pending_confirmation → applying → applied`，也可 rejected / expired / conflict / failed / cancelled / interrupted。批准再次按快照检查题目、材料、停用/删除状态或原评分；冲突拒写。MCP 在真正提交前再次检查当时 Key/scope；助手运行中断后不应用旧提案。网络/模型/等待审核不持 Ledger 写锁。判定审核库状态与执行领域写分开，不把辅助库当学习事实源。

幂等回执在原生学习事务中一起保存：`operation_receipts(operation_id,digest,result_json,commits_json,created_at)`。表由 `CREATE TABLE IF NOT EXISTS` 按需创建，不改旧提交。线程局部 `ledger.operation()` 把服务端 provenance 写到新增 payload 的 `_operation={id,digest,source,key_id?,conversation_id?,run_id?,call_id?}`；用户不能伪造此字段。事务开始、提交前均再次校验授权和快照。同一操作重复进入事务读回执，既不重新分配 ID，也不追加重复学习事件。无需写学习事件的无变化操作仍保存回执。

草稿回执与草稿内容同一次原子 `os.replace` 保存到 `_operation_receipts`，草稿创建也只保存一次，始终不进 Ledger。启动 `ai_review.recover()` 只按原生 receipt 对账；有精确回执恢复 applied，没有则 interrupted，绝不重新执行不确定的写请求。恢复重复运行安全。

## 辅助运行存储与历史

`runtime_history.py` 的 `runtime.db` 保存 call_id、source、tool、标题、开始/结束、状态、耗时和脱敏 arguments/result/actor。使用正向字段白名单：允许稳定对象编号、数量、状态、revision和用量；正文/用户文字/Key/request_id/URL/图片内容不保存，未知自由字段直接舍弃。运行故障不反向影响已经成功的领域结果。启动将未结束记录标 interrupted，不推测成功。助手会话正文属于单独的私有 assistant.db，不进入运行摘要或作文笔记。

`history.py` 只读 Ledger，搜索、source/type、日期先筛选再分页。模型提交有效 source 取 `_operation.source`，并保留原 `domain_source`；旧提交继续用原 source。学习与系统运行分轨，均按日展示，并有题目、草稿、Session、作文、审核、助手会话的稳定定位。评价/笔记直接使用事件中固定的 version_id；分类按 target_type/target_id 跳转。无通用回滚器，历史本身不执行领域写。
