# CLMS 开发文档索引

## 按任务找文档

| 要做的事 | 先读 |
| --- | --- |
| 改数据结构、加提交类型、改去重、改入库 | `data.md` |
| 改复习节奏、评分档、排复习的挑题规则、估时 | `algorithm.md` |
| 改 AI 提示词、草稿结构、默写模板格式、对话修订 | `ai.md` |
| 改 Agent harness、工具、子代理委派、插话 / 停止 | `ai.md`「Agent harness」 |
| 改复习记录的增删改查、删除后恢复 | `data.md`「复习记录」 |
| 改脱敏源码导出 | `api.md`「脱敏源码包」 |
| 加 / 改 HTTP 接口、题库查询、打印卷面、命令行 | `api.md` |
| 改界面：录入页、概览、题库、复习、设置、样式 token | `frontend.md` |
| 看版本变化 | `changelog.md` |

## 与 OMRS 的对应

| OMRS | CLMS | 说明 |
| --- | --- | --- |
| `错题/.omrs/ledger.db` | `语文/.clms/ledger.db` | 同样的哈希链提交表与编号计数器 |
| 题目 Markdown 文件 | Ledger 提交的 payload | 语文题没有公式和手绘图，内容直接存在提交里，省掉文件与索引同步 |
| inbox 收件箱 | `drafts/*.json` 草稿 | 暂存层，不进 Ledger；多了多轮对话与版本（revision） |
| `projections.py` 每次全量重放 | 常驻内存、按 seq 增量应用 | OMRS 技术债之一 |
| 单线程 `HTTPServer` | `ThreadingHTTPServer` + 后台 AI 线程 | OMRS 技术债之二 |
| 路由 if 链 | 路由表 `@route(method, path)` | OMRS 技术债之三 |
| 0–10 分自评 | 四档（默写三档） | 更贴近语文主观题的采分点感觉 |
| 历史页 review.replace / retract / restore | 复习记录增删改查（void + grade，见 `data.md`） | 不新增提交类型，改 / 撤销 / 恢复都落成已有的 grade 与 void |
| `source_export.py` 脱敏源码包 | 同名模块 + 设置页按钮 + `export-source` 命令 | 另把当前 API Key 与 `sk-…` 串替换掉 |
| （无） | Agent harness（对标 Pi agent-core） | 录入对话直连工具调用的 Agent，大试卷委派子代理 |
| 每天复习 | 复习日（默认周二 / 五 / 日），到期日对齐复习日 | 低频复习 |
| `assets/app/{core,ui,domain,features}` + `check_ui.py` | 同左 | 核心模块（html / dom / events / router / store / bus / api）直接沿用 |

## 门禁

```bash
python3 -m unittest discover -s tests -q   # tests/test_core.py：去重、提交链、调度、入库、复习、HTTP 全流程
python3 tests/check_ui.py                  # 前端纪律 R1–R9
python3 tests/e2e_main.py --shots /tmp/s   # 真浏览器主路径（playwright），可另存截图
```

`tests/test_agent.py` 覆盖 harness（工具出错回给模型、截断不执行、旧图省略、插话、停止）、草稿工具、复习记录增删改查、脱敏导出，以及 Agent 模式的 HTTP 全流程。`tests/fake_ai.py` 是 OpenAI 兼容的假模型（带 `tools` 的请求扮演确定性的工具调用 Agent）：识图请求轮流返回三套草稿（现代文《老街的灯》+ 默写、古诗《山居秋暝》+ 标点不同的重复默写、文言文《咏雪》），修订请求能听懂「第 N 题 + 答案 / 题型 / 留白」。环境变量 `FAKE_AI_DELAY=秒` 可以模拟慢模型；`CLMS_TODAY=YYYY-MM-DD` 可以固定「今天」。
