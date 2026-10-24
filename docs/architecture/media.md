# 私有原件和视觉派生页

`backend/app/media/` 被 Web 和 MCP 共用。上传经文件签名、扩展名一致性和完整解码校验，只接受单帧 JPEG、PNG、WebP 和普通未加密 PDF。客户端文件名只作为展示信息；含路径分隔符的名称被拒绝。存储目录、文件引用的任意组件出现符号链接均拒绝，业务输入不接受磁盘路径或 URL。

原件字节先写入服务端 UUID 目录并 fsync，之后创建 Asset 和 AssetPage。原件和生成的 JPEG 为只读文件；旋转和局部查看仅在内存生成新图像。读取原件需要网页登录，读取页面的 MCP 需要 `media.read`；读取指定版本还需要 `archive.read`。

图片由 Pillow 验证及完整解码。EXIF 方向应用于派生页，透明背景合成为白色纸面，避免透明黑底吞掉黑色笔迹；原始字节保持不变。派生页最长边上限由 `media_high_edge` 控制。PDF 用 `pypdfium2` 在短命 Python 子进程中渲染：限制地址空间、CPU 时间、文件句柄、最大页数和页面像素；父进程有硬超时和并发 semaphore。渲染器不初始化表单、执行 JavaScript 或打开嵌入附件，不做文字提取。解析子进程不继承服务凭据环境变量。Web/MCP 在工作线程调用服务，PDF 不阻塞 ASGI 事件循环。

每个 AssetPage 有稳定 `page_id`、`asset_id`、`source_page`（从 1 开始）和视觉派生页尺寸。稿件 manifest 的 `order` 和 `rotation` 由领域服务冻结。图片工具附上原文件 SHA、精确版本 ID、两个哈希、源文件页号和稿件顺序。区域参数为旋转后的 `[x,y,width,height]` 归一化坐标；返回 region、旋转前后尺寸和输出尺寸，width/height与冻结稿件manifest的旋转后整页尺寸一致，source_width/source_height保留旋转前尺寸；评价位置仍引用原 page_id。

单用户网页上传的未入档素材可被具 `media.read` 的凭据读取。由某个 MCP 凭据产生的暂存文件只允许同凭据读取，只有正式引用建立后才共享；待审引用不会使私人暂存可被别的凭据读取。

清理调用 `cleanup(session,settings)`，调用者必须使用 `db.transaction()`（SQLite BEGIN IMMEDIATE）以序列化清理与新建引用。任何 FileReference（包括 pending）均阻止 TTL 清理。数据库删除提交后才删除文件，因此回滚不会导致现存 Asset 丢失原件。`cleanup_orphan_files` 回收数据库失败/崩溃遗留的超过 TTL 的 UUID 目录；不得清理其他名称或符号链接。两者支持 dry_run。文件与 SQLite 不是跨介质原子事务，允许失败遗留可回收孤儿文件，不允许正式引用指向未持久化文件。

默认限制集中在 `config.Settings`，`get_capabilities` 和设置页公开限额：图片 25 MiB、PDF 100 MiB/50页、解码 40 MP、普通图 2048 px、清晰图 4096 px、TTL 72小时、PDF 20秒/512MiB/并发2。MCP默认1页，最多2页，整个MCP工具结果JSON预算4MiB（包括图像Base64、文本与structuredContent映射和读取回执ID）；超限明确失败，不以占位图成功返回。

## MCP 附件暂存（0.10.2）

`mcp/uploads.py` 将真实Base64字节或宿主提供的受控ChatGPT附件交给同一个 `media.service.upload`，保留原件、全部页映射及来源actor。暂存允许直接保存，正式业务仍须审核。新入口不接受任意URL或服务端路径，不增加OCR/模型调用。

ChatGPT工具声明标准 `openai/fileParams` 文件对象，仅下载HTTPS/443的 `files.oaiusercontent.com` 附件，不跟随重定向、拒绝非公网解析、不携带CLMS凭据；限额流式读取到临时文件，关闭即清除。下载不持有SQLite事务，前后各自校验scope/撤销/到期；链接与文件参数验证内容不进入错误和HTTPX日志。

Base64入口默认8MiB（`CLMS_MCP_UPLOAD_MAX_BYTES`）。`mcp/body_limit.py` 在Bearer鉴权之后、SDK解析之前限制完整MCP JSON大小，Content-Length或chunked均适用；超限返回413。它不会放宽网页multipart或图片/PDF的既有限额。两个入口都只创建当前MCP凭据拥有的私人暂存页；pending引用防止TTL清理，正式入档前不向其他凭据共享。
