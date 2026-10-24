# 验收矩阵

状态仅由真实执行报告决定。要求基线 `50f272167b14df9fc27f55fd6f185e5de3418ab2`；当前分支/commit、脏状态、环境、命令、时间与退出码记录在 `artifacts/verification.json`。本文映射用例，不用未经执行的勾选冒充通过。

| 编号 | 验证入口/证据 |
| --- | --- |
| T01–T03 | backend tests：空初始化、分类、纯附件题目 |
| T04–T09 | `backend/tests/test_media.py`、MCP协议媒体测试、cleanup引用保护 |
| T10–T18 | domain tests：独立练习、不可变多稿、快照、严格评价/评分、部分覆盖和追加历史 |
| T19–T25 | review tests：pending隔离、人工决定、CAS、幂等、并发、故障注入/重启 |
| T26–T29 | `backend/tests/test_security.py`、官方协议 scope/撤销、浏览器输出安全 |
| T30–T31 | `backend/tests/test_mcp_protocol.py`，官方SDK经真实端口+有效图像字节 |
| T32–T34 | `frontend/tests/browser/archive.spec.ts`，F01–F08、脏表单、各视口/主题；`artifacts/browser/` |
| T35 | `test_paginated_listing_stays_bounded`、`test_list_summaries_do_not_expand_full_documents_or_materials`：较大数据分页、列表不展开原图/全文详情 |
| T36 | restart/persistence tests、`scripts/clean_deploy_verify.py` |
| T37–T39 | 删除清单、旧路由拒绝、运行依赖无模型/OCR、无外网模型配置核心闭环 |
| T40 | `scripts/clean_deploy_verify.py`：干净目录锁定安装、迁移、构建、实际启动、重启 |

## 统一门禁

```bash
uv run --frozen python scripts/verify.py --all --report artifacts/verification.json
```

所有门禁必须 pass，缺依赖、skip 或零 pytest 用例必需失败。开发子集报告 `complete_required_suite=false`，不能作为工程完成证据。截图采集先核对题目卡、精确稿件与已入档评价预览/真实结果，等待全部加载指示消失及原稿图像解码；仅 `networkidle` 不足以证明 React 级联详情请求已完成。截图必须实际查看，错误/console和返回的业务 ID核对；浏览器模拟不等于实体平板/手机。

真实外部 E01–E05 按 `external-client-verification.md` 独立记录。用户选择先模拟自测，因此模拟通过也不能标 ACCEPTED。生产路径/权限未确认，生产切换和真实旧数据删除保持 NOT_RUN，不能标 DEPLOYED。

## 交付等级

- ENGINEERING_COMPLETE：M0–M4、T01–T40全通过，代码/文档/锁定依赖/干净部署一致。
- ACCEPTED：上述基础上真实外部 AI E01–E05完成。
- DEPLOYED：实际目标生产切换、旧目录清理、重启与回滚记录完成。

当前等级：ENGINEERING_COMPLETE。`artifacts/verification.json` 对 `de292c9b632fd08e7a033f0684d12f0c0a87f048` 的完整九门禁均pass、exit0、skip0，工作区采样为干净；Docker实际构建/运行证据独立保留。E01–E05/实体设备/生产仍按上述边界未执行，不标ACCEPTED或DEPLOYED。
