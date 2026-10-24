# 数据、快照与审核

数据库为全新 SQLite 格式，SQLAlchemy 管理模型，Alembic 管理迁移。没有 Ledger 重放、旧数据自动迁移或启动清库。实体及 HTTP 字段以 `../docs/architecture/contract.md` 为契约。

## 档案关系

Category 是用户自建扁平多选分类，初始为空；名称 trim、Unicode 规范化并大小写一致比较，同语种范围内规范化名称唯一。停用保留历史引用，新的题目不能选停用分类。

Prompt 保存题目、要求、材料、语言及可空 rubric。题目文字或题目附件至少一种。Attempt 是一次独立写作，冻结当时题目/材料/rubric 和 `snapshot_hash`。同题重写新建 Attempt；修改上一稿只新增 Version。

Version 保存有序页清单、原件哈希、源页号、旋转及 `manifest_hash`；至少一页，`(attempt_id,version_no)` 唯一。入档后清单和原件不可覆盖，作废也保留历史。

Evaluation 绑定精确版本和两个预期哈希；页定位只能引用该版本的页，bbox 可空，非空为规范化的 `[x0,y0,x1,y1]`。`error`、`improvement`、`uncertain` 分别表示明确问题、优化建议、待确认。`score=null` 不等于 0；有分数时校验范围和当时 rubric，只有 `aggregation=sum` 才要求分项相加一致。部分评价不算完整。修订正式评价追加一条并通过 `supersedes_id` 指向旧结果。

## 媒体

Asset 保存不可变 JPEG/PNG/WebP/PDF 原始字节，AssetPage 映射稳定页 ID 与 PDF 源页。路径由服务端生成，原文件名只是数据。派生图用于视觉阅读，不运行 OCR、转写或全文索引。

正式版本、题目快照和 pending 提案通过 FileReference 保护原件。只允许回收无引用、超过 TTL 的暂存文件；事务边界内复查引用。先持久化文件，后事务性引用，失败时允许有可回收未引用文件，不能存在入档但原件缺失的记录。

## 审核与事务

MCP 正式写入只产生 ReviewOperation。来源、credential ID、request ID、目标基线和权限由服务端确定，修订只允许固定字段，不能改身份。保存原始 payload/digest 与当前有效 payload/digest，ReviewRevision 留存完整修订历史。

状态为 pending → applied/rejected/withdrawn/conflict/failed。网页决定检查会话、同源、CSRF、CAS revision、有效 digest、目标快照、文件与凭据现状。正式业务、人工决定、审计及结果回执在同一 `BEGIN IMMEDIATE` 事务提交；领域函数只 flush，不自行 commit。

修改既有对象的 `target_snapshot.before` 冻结修改前值，审核时比较防止目标变化被覆盖。评价目标快照包含完整冻结题目快照与稿件页清单，页面可把当前原稿、评分依据和提案放在一起核对。

幂等作用域为 credential ID、工具种类、request ID。同原请求返回同提案/结果，不覆盖人工修订；同 ID 异内容冲突。重复决定返回已存在回执，不再次写业务。失败回滚，重启保留 pending，不自动批准或由 GET 重放。

AuditEvent 保存 actor、动作、实体关系和真实结果；不保存凭据明文、Cookie、Base64 图像或任意文件路径。WebSession 与 MCP Credential 完全独立。凭据明文仅创建时返回，数据库只保存摘要。
