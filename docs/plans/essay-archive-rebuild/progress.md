# 重构进度

## 2026-10-24 · MCP附件上传修复（0.10.2）

- 用户授权修复附件上传、提交GitHub并部署生产。独立分支 `codex/mcp-attachment-upload` 从实际生产0.10.1的后续维护提交 `8b3b3d8` 建立；原工作区及未提交 `output/` 保留。
- 新增 `upload_attachment` 的ChatGPT原生文件参数与 `upload_asset` 的通用Base64入口，均复用媒体服务，仅创建当前凭据的私人暂存页；正式练习/版本仍须网页审核。
- 附件下载严格域名/HTTPS/公网解析/禁重定向/限流限时，不转发CLMS凭据；下载前后校验scope/到期/撤销。MCP JSON在解析前限制Content-Length及chunked体积，错误和HTTPX日志不回显临时链接或文件字节。
- 完整九项工程门禁全部pass/exit0/skip0：后端87、前端23、真实浏览器6、官方MCP协议10、安全23（包含重叠用例）；依赖审计0漏洞，干净安装/迁移/启动/重启通过。已查看MCP上传待审和正式原稿截图，工程报告 `artifacts/verification.json`。GitHub提交与生产部署正在执行。ChatGPT宿主真实附件透传、E01–E05与实体设备尚未验收。

## 2026-10-11 · 审核中心生产发布（0.10.1）

- 用户原话「发布生产啊」，状态 DEPLOYED。固定提交 `969ad07626d315a83f7f0678ea98b39e3d188f24`，独立发布目录 `/root/workspace/apps/clms-archive/releases/969ad07`，地址 [审核中心](http://192.168.0.145:8473/#/reviews)。
- 工程九项门禁全部 pass/exit0/skip0，报告保持提交前的真实身份；提交后121个源码哈希一致，锁定重建的前端与通过门禁的草稿逐字节一致，原图标和迁移文件未变。实际 release 已用新临时库试启动。
- 冷备份 `/root/workspace/backups/clms/before-review-center-deploy-20261011-021153Z/` 已完成归档逐文件、完整解压、SQLite完整性/外键校验。10:11:55（Asia/Shanghai）完成切换及健康核验，停服请求至核验2.295秒。
- 生产20项 HTTP检查通过：健康0.10.1、静态资源哈希、Web/媒体/MCP未登录限制、同源校验；live unit/PID/cwd确认新release，服务enabled/active且无自动重启。检查后数据库、管理员、MCP凭据、会话、bootstrap token与运行配置仍一致，无新增warning/error日志。
- 真实生产Chromium检查1440×900、390×844、320×720和手机深色登录页，四张截图均已查看；无控制台错误、失败请求或横向溢出。
- 未提供管理员密码或生产MCP secret，生产登录后业务未复测；工程F01–F08及官方SDK实际端口另在临时库通过。真实外部AI E01–E05、实际生产MCP凭据调用和实体设备未验收，不混称ACCEPTED。
- 发布摘要 `artifacts/review-center-ui/production-969ad07.json`，工程证据 `artifacts/review-center-ui/ready/`；完整运维证据 `/root/workspace/apps/clms-archive/deployment/review-center-0.10.1-969ad07/`。保留0.10.0 release与回退unit，原工作区仍仅原先`?? output/`，未改master或OMRS。

## 2026-10-11 · 审核中心草稿工程交付阶段（0.10.1）

- 用户要求「优化审核中心UI」「不明确具体AI做了什么」「有审核页不会显示」「加上气泡提示」「做一个草稿」。独立分支 `codex/review-center-draft`，工作树 `/root/.codex/worktrees/review-center-draft/clms`；原工作区 `output/` 与生产 0.10.0 保留。
- 对应 R07、计划8.6及 F03/F04：明确操作/目标/入档影响，六类提案可读预览与差异，真实待审数量气泡及可访问说明气泡；题目材料接入阅读器，修改稿展示提案 pages，上一稿单独查看。空筛选提供全部记录入口，已处理提案详情保留。
- 草稿阶段状态 DRAFT_VERIFIED；`uv run --frozen python scripts/verify.py --all --report artifacts/verification.json` 九项门禁全部 pass/exit0/skip0：后端83例、前端单元23例、浏览器5个流程测试、官方 MCP 协议6例及安全23例；锁定干净安装/构建/迁移/实际启动和重启通过。
- 真服务/真浏览器完成 F01–F08及本次六类提案/气泡回归；官方 SDK 经实际端口提交合成题目、材料、修改稿、组合入档、分类、反思和评价。五种视口/明暗主题与触屏模拟共48张合成截图，已实际查看桌面提示、材料、修改稿及手机/深色窄屏；`artifacts/browser/review-draft-*.png` 是本次草稿图。
- 摘要明确操作和影响；桌面长队列独立滚动且选中项保持可见，手机详情收起筛选，审批按钮放在正文末尾避免遮挡。原工作区状态核对仍仅有原先的 `?? output/`。
- 草稿工程阶段未执行真实外部 AI E01–E05、实体设备及生产切换；后续生产发布见上节，外部 AI 的 ACCEPTED 与实体设备仍未达成。

## 2026-10-11 · 书页档案生产发布（0.10.0）

- 用户原话「发布到生产」：已完成实际发布，状态 DEPLOYED；生产固定提交 `6030883acc89b8ae0ccf5f403dd0d9956886de06`，独立目录 `/root/workspace/apps/clms-archive/releases/6030883`，地址 `http://192.168.0.145:8473/`。
- 已验证源码的111个文件哈希一致；锁定安装、构建及临时数据试启动通过，构建与工程验收产物一致，三个原图标字节一致，迁移文件未变。
- 私有备份 `/root/workspace/backups/clms/before-book-page-deploy-20261011-013833Z/` 完成归档逐文件校验与完整解压/SQLite 验证。09:38:38（Asia/Shanghai）切换及启动核验完成，从停服请求至启动核验4.449秒。
- 生产 HTTP 检查20项通过：健康0.10.0、资源哈希、Web/媒体/MCP 未登录限制及同源校验；unit、进程工作目录和新 PID 均证实实际加载新 release。检查后数据库、管理员、凭据及会话行仍与冷备份前一致；SQLite 完整性及外键通过，无新 warning/error 日志。
- 真实生产 Chromium 检查桌面1440×900、手机390×844、窄屏320×720及手机深色；登录页、原图标、主题与资源加载通过，无控制台错误或横向溢出，已查看桌面及手机截图。
- 没有管理员密码，生产登录后的业务流程未复测；工程 F01–F08 已在临时库通过。没有新增/重置凭据或写入合成业务记录；真实 MCP secret 调用、外部 AI 和实体设备未在本次发布验证。
- 发布摘要 `artifacts/book-page-ui/production-6030883.json`；完整运维证据和回退步骤见 `docs/operations/workspace.md` 指向的生产部署目录。部署记录不改变应用版本，生产仍是已验证的0.10.0源码。

## 2026-10-11 · 书页档案前端工程交付阶段（0.10.0）

- 工程交付时状态：前端实现与工程验证完成，当时未生产发布。源码入口为 `/root/workspace/apps/clms`，分支 `codex/book-page-frontend`，起点 `4638179`；最新生产发布身份见上节与 `docs/operations/workspace.md`。
- 用户诉求逐项落实：
  - 「帮我精致打磨前端，先画草稿」「重新设计草稿吧」：已确认的「书页档案」草图落实到当前 FastAPI + React 作文档案馆，双列卡片、原稿/评价对照、精简审核队列。
  - 「纸白 + 墨蓝，精致的语文工作台」：统一色彩与排版 token、阅读标题和总体评价层级，深色主题保留原稿原色。
  - 对新旧版本并存的追问：改动正式维护源码的新版四个导航入口，不引入旧 Ledger、OCR、调度或内置模型页面。
  - 「可以，记得套用已经设计完的 icon」：导航、登录、favicon 与 Apple touch icon 接入「墨燕」原产物；源文件、运行资源及构建资源逐字节一致，原 output 目录保留。
- 详情收起题目要求、反思和管理信息，默认以原稿与当前版本评价为主体。冻结题目读取所选练习快照，版本状态读取真实 API；复制任务、独立练习、历史评价与作废记录仍可使用。
- 手机可切换原稿/评价及对比稿件。反馈定位移入原稿并避开顶栏，重复定位同页仍生效；修订保存后保持评价预览，面板切换保留本地输入。切到新审核目标会刷新真实队列。
- 最终统一门禁：`artifacts/book-page-ui/ready/verification.json`，2026-10-11T01:28:31.008526+00:00 至 01:29:31.563461+00:00，9/9 pass；后端83、前端17、浏览器4、官方 MCP 协议6、安全23，skip=0；npm audit 所有等级均0，干净部署检查通过。
- 真服务/真浏览器完成 F01–F08；1440×900、1280×800、800×1280、390×844、320×740 的明暗主题检查和触屏浏览器模拟通过，共42张合成截图。查看了档案、阅读、待审对照、手机原稿视口及深色窄屏的实际渲染。图标校验见 `artifacts/book-page-ui/ready/icon-verification.json`。
- 验证过程保留于独立目录：最初 smoke 发现静态图标入口缺失，后续窄屏回归发现保存后面板回跳，均修复并重跑完整门禁；旧重构验收证据未覆盖。
- 工程交付阶段未测试实体手机/平板与真实外部 AI；MCP 验证使用明确标记的确定性模拟客户端。当时未修改生产 release、服务、凭据或生产数据，未上线0.10.0；后续实际发布独立记录于上节。

## 原重构工程交付时的历史快照

以下是原0.9.0重构任务结束时的记录；其中「未部署」「原主工作区仍旧版」不代表当前生产或正式维护入口，现状以 `docs/operations/workspace.md` 和上述本次任务记录为准。

- 当前状态：ENGINEERING_COMPLETE。真实外部 AI 的 ACCEPTED 与生产 DEPLOYED 均未达成。
- 代码提交：de292c9b632fd08e7a033f0684d12f0c0a87f048；分支 codex/essay-archive-rebuild。后续提交仅归档交接文档和合成验证证据，运行代码不变。
- 基线：实际 50f272167b14df9fc27f55fd6f185e5de3418ab2；计划基线 cf78871843be8c31560d0c8be36841813386b734 本地不存在，无配置 Git remote。
- 工作树：/root/.codex/worktrees/essay-archive-rebuild/clms；原工作区 /root/workspace/apps/clms 的全部未提交修改保持原样，主分支未改变。
- M0–M4：完成隔离与协议/媒体试跑、冻结契约、新关系库/原件、事务审核闭环、全部真实页面，以及并发/崩溃/权限/规模自动化。R01–R12 与 T01–T40 的映射见 plan/acceptance/handover。
- M5 可执行部分：干净目录安装、构建、迁移、启动、重启，以及 Linux Docker 镜像/非 root 只读容器/持久卷实际验证通过。生产切换保持 NOT_RUN。
- 最终统一门禁：2026-10-10T16:32:47.060256+00:00 至 2026-10-10T16:33:44.983939+00:00（UTC；北京时间2026-10-11），9/9 pass，全部退出0；后端83、前端17、浏览器3、官方SDK协议6、安全23，skip=0；npm audit 所有等级均0。证据 artifacts/verification.json 与 artifacts/gates/。
- 浏览器：F01–F08，桌面1440×900、横平板1280×800、竖平板800×1280、手机390×844，明暗主题共28张合成样例截图。截图等待真实内容和图像解码后捕获；已实际查看两种主题及四种视口。实体设备未测试。
- 浏览器环境：统一门禁显式使用已安装的匹配 Chromium1194 完整版，路径在报告中；第一次缺 headless 依赖的失败报告保留在 artifacts/attempts/default-browser-dependency。安装完成后默认浏览器无 override 补验3项通过，记录 artifacts/default-browser-ready/browser/playwright.json。
- Docker：镜像 sha256:4ed7bd200e845a1f4be3b904d6e80816f6a3bbf5c7d9656c48b8f24fb95ca842，UID10001:10001、只读运行、原件SHA与重启持久化通过；测试容器/卷已清理。证据 artifacts/docker/report.json 与 build.log。
- 外部客户端：用户选择“先写脚本模拟自测”。官方SDK经真实TCP读取冻结题目及图片/PDF、提交明确标记的模拟pending评价/分类，真实网页修订并批准；脚本不调用模型、不自行批准。E01–E05未作为真实AI验收通过。
- 数据与权限：未修改生产，未删除原工作区或真实旧业务数据；无旧数据迁移，仅临时清理演练。OMRS仅只读参考，无修改。
- 环境：Python3.12.13、Node22.23.0、SDK1.30.0、Pdfium5.14.0、Pillow12.3.0，实际协商协议2025-11-25；锁文件与部署材料已提交。
- 后续条件：真实外部客户端补验按 external-client-verification.md；确认生产实例与专属旧数据路径后按 operations/cutover.md 操作。工程实现与当前授权的脚本自测已完成。
