# Mini-RBN 部署

## 运行入口

- CLMS 版本：0.7.0。
- 源码与 vault：`/root/workspace/apps/clms/`。
- 数据：`语文/.clms/`，保留上传压缩包里的 Ledger、草稿、图片和 AI 配置。
- 内网地址：`http://192.168.0.145:8473/`。
- systemd：`clms.service`，开机启动、失败自动重启。
- 8472 已由 OMRS HTTPS 入口使用，本部署改用 8473，未修改 CLMS 默认 CLI 端口或原有服务。

## 安全和网络

应用没有登录保护，仅绑定 `192.168.0.145`，不监听 IPv6，不新增 Nginx、路由器转发或 FRP 公网入口。宝塔/UFW 新增规则为 `192.168.0.0/24 → TCP 8473`；Homepage 容器使用主机既有 Docker 信任规则访问。

systemd 以 root 运行，启用 NoNewPrivileges、PrivateTmp、ProtectSystem=strict、ProtectHome=read-only，只有 `语文/.clms` 可写。配置文件权限为 600，数据目录为 700。AI 配置已保留，但部署验收未发起真实模型请求、未上传历史材料给模型。

## Homepage

卡片：工作 → CLMS 语文错题本。

- href：`http://192.168.0.145:8473/`
- siteMonitor：`http://192.168.0.145:8473/api/summary`

服务仅绑定 LAN IP，因此监控使用同一个 LAN 地址，而不是未监听的 `host.docker.internal` 网关地址。

## 已完成的验收

- 79 个 unittest 全部通过，check_ui 为 0 处问题。
- 独立临时 vault + 假模型的真浏览器主路径通过，包含 PDF 浏览器路径；未修改测试或应用源码。
- 生产首页、JS、摘要、配置脱敏与 Ledger 验证接口返回 200。
- 原有题库为 9 题、2 篇材料，19 条提交链完整。
- 服务重启后恢复，active/enabled。
- Homepage 容器可访问摘要接口；真实页面卡片只出现一次，处于工作分类，监控返回 HTTP 200；点击进入 CLMS。
- 主机浏览器验证概览、题库、录入、复习、设置，无 uncaught error 或 unhandled rejection。
- 未从独立手机/电脑验收；真实 AI 识别未测。

## 备份与回滚

备份：`/root/workspace/backups/recycle/clms-deploy-20261003-125319/`，目录权限 700，包含原始 CLMS.zip、迁移清单、Homepage 和防火墙变更前备份。

原始 `/tmp/CLMS.zip` 未删除。压缩包 SHA-256：`2eeaed3e80e10a71166239bf332b9bf4cdc3126fb6d21df412677ed000e0d54d`。

回滚时先停止并禁用 `clms.service`，保留数据并将部署目录移入新的回收目录；仅移除 CLMS Homepage 卡片和宝塔/UFW 的 TCP 8473 LAN 规则。不要把全量历史 iptables/nft 快照恢复到运行中的 Docker/UFW/v2rayA 混合环境；Homepage 全文件恢复前也应比较是否存在本部署之后的其它修改。
