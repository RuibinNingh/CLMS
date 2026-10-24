# 架构决定与实际兼容性

## ADR-001：一个模块化应用和同库事务

采用任务书默认 FastAPI/Pydantic、SQLAlchemy/Alembic、React/TypeScript/Vite；正式关系与审核记录同在新 SQLite 库中。审批只产生 applied/rejected 或明确冲突/失败，决定、业务、审计和回执一次提交，不持久化“已批准但待执行”的假成功。BEGIN IMMEDIATE 跨线程/进程序列化版本号分配与 CAS。原件先 fsync 持久化再建立引用，失败孤儿由受控 TTL 清理。不会复用 Ledger、旧 vault 或旧运行入口。

等价验收：迁移空库、外键/唯一约束、不可变内容触发器、组合回滚、两窗口审核、并发稿号、提交前/后进程崩溃与重启回执测试。未来结构变化必须新建 Alembic revision，不改已发布迁移。

## ADR-002：官方 SDK 与受限 Bearer

锁定的官方 Python MCP SDK 为 1.30.0。实际官方客户端协商 2025-11-25，capabilities 返回真实支持版本和当前请求版本。任务书示例日期不是兼容性承诺。Web 会话与 MCP 密钥严格分离；stateless Streamable HTTP 每请求、每工具重新校验，连接 ID 不授权。提供受控 Bearer，不声称标准远程 OAuth 自动发现或所有客户端支持。

等价验收：真实 TCP tools/list/tools/call、严格工具 schema、ImageContent 解码、实时 scope/撤销、跨凭据待审隔离、不能调用网页批准。用户当前选择脚本模拟评价者；E01–E05 真实模型能力仍未验收。

## ADR-003：服务端视觉渲染

使用 Pillow 12.3.0 和 pypdfium2 5.14.0，PDF 在独立受限子进程栅格化，保留原始字节，无文字提取或 OCR。CPU/内存/超时/并发/页数/像素限额集中配置；Linux 为已验证的运行平台，推荐提供的 Linux 镜像。浏览器不承担外部 AI 读取前置步骤。

等价验收：PNG/JPEG/WebP、多页与混合 PDF、实际加密/空密码 PDF拒绝、损坏/超限/硬超时/内存限制、旋转和区域映射、响应预算不产生假回执、原件 SHA一致、事务回滚/保存点不误清理。

## 参考核对

只读读取 OMRS 固定基线 `2b030a6e4cbd916a60c42883ba34547734bc924b` 的 `AI/frontend/ai-review.md` 与 `omrs/ai_review.py`，借鉴有效提案摘要、CAS、来源复验、脏表单和实际回执；不复制其 Ledger、训练/OCR 或线程状态机。CLMS 计划基线本地不存在，当前实际基线与保留的未提交变更记录在 progress.md。

官方实现参考：[Python SDK](https://github.com/modelcontextprotocol/python-sdk)、[MCP Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)、[FastAPI](https://fastapi.tiangolo.com/features/)、[Vite](https://vite.dev/guide/)。SDK 与 Vite 公共来源读取成功；规范/FastAPI网络读取超时，实际协议与schema结论以已安装锁版本代码和真实协议测试为证据，不把网络失败写成核对通过。
