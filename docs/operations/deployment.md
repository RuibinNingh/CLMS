# 部署与日常运维

首次从旧题库切换到作文档案馆时使用全新数据目录；作文档案馆后续版本发布沿用已确认的生产数据目录。下文是通用操作手册；本机正式源码、实际生产发布目录和旧版恢复分工先读 [工作区说明](workspace.md)。生成配置或在临时实例试跑不等于已更新用户生产服务。工程历史证据看 `artifacts/verification.json` 和 handover，新主目录门禁及生产核验看对应的独立证据。

## 安装、迁移、启动

根 README 给出锁定依赖安装与本机启动命令。建议应用放 `/opt/clms`，数据放全新 `/var/lib/clms-archive`，由专用 `clms` 用户拥有，目录权限 0700、umask 0077。原件、派生页、SQLite 与认证状态都在数据目录内，不应放进公开 web 根目录。

复制 `.env.example` 为私有配置，填写实际 origin，HTTPS 时启用 Secure Cookie。`CLMS_DATA_DIR` 必须指向新库；本机默认监听 127.0.0.1。设置页显示受控限额和 MCP endpoint，不暴露管理员密钥。

服务端迁移：`uv run --frozen alembic upgrade head`。CLI `init` 建立/检查目录和 bootstrap token，`serve` 启动，`cleanup` 只回收新库无引用超期暂存。迁移与初次启动不会读取旧 CLMS 数据。首次创建管理员后数据库拒绝再次 bootstrap；本机令牌文件仍保留供 init 检查，但不能再授权管理员创建。不要把其内容写进日志。

## 已有作文档案馆的版本发布

从通过完整门禁的固定提交建立独立 release，使用锁文件安装依赖并构建前端；切换前核对源码哈希、构建文件、图标和迁移差异，并以临时新库试启动实际发布包。保留现有 origin、监听地址、数据路径和认证配置。构建与试启动期间原服务继续运行。

准备并验证只替换发布目录的 unit。停止 CLMS 后确认进程退出、数据文件没有其他打开者，私有冷备份原 unit、运行配置和完整数据目录，逐文件比对并在独立目录解压验证 SQLite。备份验证通过后安装新 unit、daemon-reload、启动并检查健康、实际进程目录、静态资源、权限和生产浏览器。启动失败时恢复原 unit 并启动上一版；是否恢复数据库取决于迁移兼容性与后续写入，不能直接覆盖运行中的库。

此前 0.10.1 已按上述流程从 `6030883` 切到 `969ad07`，迁移文件没有变化。应用版本与源提交见 `artifacts/review-center-ui/production-969ad07.json`；完整备份及回退步骤见生产部署目录 README。生产20项 HTTP 检查与四种真实浏览器登录布局通过；未提供管理员密码或 MCP secret，登录后的业务与真实凭据调用没有复测。工程九项门禁及源码/构建对应证据保存在 `artifacts/review-center-ui/ready/`。此前0.10.0发布记录仍在 `artifacts/book-page-ui/production-6030883.json`。

本机当前0.10.2已从 `969ad07` 切换至 `f0099d6`。此次新增MCP附件暂存，无数据库迁移，原数据和认证配置保留；工程完整门禁、冷备份、发布包试启动、生产HTTP/浏览器及已连接MCP调用均分别验证。摘要见 [0.10.2发布记录](releases/0.10.2.json)，真实ChatGPT文件透传仍独立补验。

## 单镜像

```bash
docker build -f deploy/Dockerfile -t clms-archive:0.10.2 .
docker compose -f deploy/compose.yaml up -d --build
```

Compose 仅映射 `127.0.0.1:8472`，持久卷 `clms_archive`，非 root UID 10001、只读镜像、丢弃 capability。用户配置中的数据路径应保持 `/var/lib/clms-archive` 与卷一致；改变路径时必须同步修改挂载。镜像启动执行迁移后启动一个应用进程，MCP 与网页同端口。

托管云构建需要继承平台代理并挂载 CA，不能关闭 TLS 校验：

```bash
env -u DOCKER_HOST -u DOCKER_CONTEXT -u DOCKER_TLS -u DOCKER_TLS_VERIFY -u DOCKER_CERT_PATH \
  docker --host=unix:///var/run/docker.sock build \
  --secret id=proxy_ca,src="$CODEX_PROXY_CERT" \
  --secret id=system_ca,src=/etc/ssl/certs/ca-certificates.crt \
  -f deploy/Dockerfile -t clms-archive:0.10.2 .
```

构建阶段联网安装锁定依赖。运行时无模型请求、远端字体/CDN 或动态安装，不需要代理 CA。

## HTTPS 与可信代理

`deploy/nginx.conf` 为 HTTPS 示例，替换域名与证书路径。外层代理覆盖客户端伪造的 Forwarded 头，不直接透传；应用仅信任配置中确认的代理 IP。默认可信边界为 127.0.0.1，容器网络代理需要明确配置 `CLMS_TRUSTED_PROXY_IPS`，不能使用 `*`。

MCP 是 Streamable HTTP `/mcp/`，与 Web 同 origin，独立 Bearer 凭据。不将 MCP key 写入 URL、proxy 日志或前端配置。长连接禁用 proxy buffering，但每次 HTTP 请求仍重新授权。实际外部客户端的自定义 Bearer 支持必须单独测试；本期没有 OAuth 身份提供者。

## 健康、日志、重启

```bash
curl --fail http://127.0.0.1:8472/api/health
docker compose -f deploy/compose.yaml logs --tail=100 clms
docker compose -f deploy/compose.yaml restart clms
docker compose -f deploy/compose.yaml stop clms
```

健康接口只提供状态/版本。容器日志输出 stdout/stderr，systemd 示例为 `deploy/clms.service`，使用 `journalctl -u clms`。日志不应含 Authorization、Cookie、原件 Base64 或 bootstrap token；调试也不 dump 环境。重启不批准 pending 提案、不重复执行已应用操作。

## 媒体限额

集中 Settings 默认：单图 25 MiB、PDF 100 MiB/50 页、单稿 100 页、40MP 像素、无引用暂存 72 小时；常规长边 2048 px、高质量 4096 px；PDF 渲染 20 秒/512 MiB/2 并发；MCP 最多 2 页/4 MiB。自托管者修改限额需同时核对内存/磁盘和前置代理 upload limit；不能只提高 HTTP 限制而取消渲染隔离。

## 最小备份与恢复

备份新库和原件，不运行旧数据迁移。为获得简单一致快照，先停止服务，确认无写入进程，使用私有目录和 umask 0077 完整归档数据目录。SQLite 主文件、WAL/SHM 和原件一起保留，随后重启并核对健康与一个档案。

恢复时停止服务，恢复到新的空目录，保持专用 UID/0700 权限，指向该目录，迁移并启动，检查原件下载 SHA-256、练习/稿件/评价与 pending 状态。不要在运行中的数据目录解压覆盖，不把备份解压到静态目录。保护备份中的认证摘要和私人作文；回滚快照生命周期由操作者记录。
