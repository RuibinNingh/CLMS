# CLMS 仓库协作准则

CLMS 是 OMRS 的语文姊妹项目，架构、纪律和门禁都沿用 OMRS。本文件写给接手的维护者和 AI 助手：既是「别破坏什么」的清单，也是「怎么维护」的操作手册。

## 开始任务前

- 先读 `AI/README.md` 的「按任务找文档」，只读和任务相关的模块文档；不要因为要改一处就通读全部 `AI/`。
- 判断现状以**当前代码和测试**为准。文档和代码冲突时，代码是对的——但不能放着不管：本任务里顺手把文档改到跟可验证的行为一致（见「文档维护」）。
- 用户原话是目的，计划只是手段：先把诉求逐条抄成清单，每一步都能指回清单里的某一条。录入页（准备 → Agent 实时执行 → 纸面校对 → 入库，左侧录入记录）是本项目的主诉求，改动它时优先保证真实浏览器里的体验，不要只看单测通过就收工。

## 不变量（改动前先确认没有破坏）

1. **Ledger 是唯一事实源。** 题库、材料、复习、评分只能通过 `ledger.transact()` / `append_commit()` 追加提交；修正也是追加（如 `review.void`），不改写、不删除旧行。新增提交类型时，要同时改 `projections.State` 的 `_on_<type>` 和 `AI/data.md`。
2. **草稿不进 Ledger。** `drafts/*.json` 是暂存层，只有入库时整份草稿写成一条 `entry.commit`，要么全部成功，要么全部失败。
3. **只比汉字。** 去重键和相似度都建立在 `common.chinese_only()` / `content_chars()` 之上；标点、全半角、空白的差异不能产生新题。
4. **默写一个空就是一道题。** 模板占位符统一写成 `{书写区域n}`，拆分后的题面用 `{书写区域}` 标出自己的空。
5. **记忆状态现算，不落表。** `scheduling.derive()` 按「今天」和复习日重放事件；不要把 sched 字段写进 Ledger。
6. **核心运行路径只用标准库。** Pillow 是可选依赖（缩图、切长图、旋转），缺了要能降级。
7. **默认只监听 127.0.0.1**；POST 请求校验同源。
8. **Agent 只经工具读写。** 模型不直接产出整份草稿；草稿、题库、记录、复习反馈都通过 `agent_draft.py` / `agent_ops.py` 的工具，工具再调用上面这些模块，所以 1–5 条对 Agent 同样成立。新增工具时同时改 `AI/ai.md` 的工具表和 `tests/fake_ai.py`。
9. **AI 的评分 / 反馈只是建议。** 复习助手（`review_ai.py`）不写 Ledger，只返回 suggestion；写入由用户点「采用」后经已有的 `/api/session/grade`、`/api/record/update` 完成。

## 前端纪律（`python3 tests/check_ui.py` 强制）

- 页面契约：`{ id, title, icon, workbench?, mount(root, ctx) → unmount }`，`ctx = { bus, store, router }`。页面之间不互相 import，联动走 bus。
- 模板一律用 `core/html.js` 的 html``（默认转义）；写 DOM 只经 `core/dom.js`（render / morph）。
- 事件一律用 `data-action / data-change / data-input` 委托，动作用 `defineActions('页面', {...})` 登记，卸载时注销。
- 颜色只写在 `styles/tokens.css`；字号、间距、圆角、阴影、层级、动效都用 token。断点只有 760 / 1160 / 1500。
- 单个 JS 文件不超过 400 行，CSS 不超过 300 行；超了就拆，不要为了塞进行数上限而牺牲可读性。
- 新增 `assets/app/features/<x>/` 时，必须同时登记到「代码到文档的对应关系」表和 `AI/frontend.md`。

## 文档维护规范

`AI/` 下的文档和代码同等重要——它们是唯一写清楚「为什么这么设计」「字段是什么意思」「接口怎么用」的地方，没有第二份记录。维护规则：

### 文档分工

| 文件 | 内容 |
| --- | --- |
| `AI/README.md` | 索引：按「要做的事」查该先读哪份文档；与 OMRS 的对应关系；门禁命令 |
| `AI/data.md` | Ledger、投影、去重、草稿结构、复习记录字段 |
| `AI/algorithm.md` | 评分档、记忆曲线、排复习、估时 |
| `AI/ai.md` | 提示词、草稿 schema、默写模板、Agent harness、对话时间线与实时流、模型接口 |
| `AI/api.md` | HTTP 接口、打印、脱敏源码包、命令行 |
| `AI/frontend.md` | 前端分层、设计语言、各页面职责 |
| `AI/changelog.md` | 版本变更记录（只追加，见下） |

### 同步规则（不是「以后补」，是本次改动的一部分）

1. **改了行为，就要改对应文档段落**，在同一个改动里完成，不要留 TODO。判断标准：如果一个新接手的人只看 `AI/` 文档、不看代码，能不能正确理解这处改动——不能就是没写够。
2. **新增模块 / 页面 / 接口 / 工具时，四件事一起做**：
   - 在「代码到文档的对应关系」表里加一行；
   - 在对应的 `AI/*.md` 里加一节；
   - 如果是「按任务找文档」表里列的任务类型，检查 `AI/README.md` 是否要补一行；
   - 涉及 Agent 工具的，同时改 `tests/fake_ai.py` 让假模型能用到新工具，否则 `test_agent.py` 测不出问题。
3. **发现文档和代码不一致**（不管是不是这次任务引入的），顺手修掉，不要绕过去；如果范围明显超出本次任务，至少在交付说明里指出来，不要假装没看见。
4. **`AI/changelog.md` 只追加，不改写旧条目**。新版本插在文件最上面（`# 变更记录` 之后），格式：

   ```markdown
   ## <版本号> · <日期 YYYY-MM-DD> · <一句话标题>

   - <这次改了什么，站在使用者角度写，不是站在代码角度>
   - <…>
   ```

   条目写「做了什么、为什么」，不写实现细节（实现细节在对应的 `AI/*.md` 里）。

### 版本号

`clms/version.py` 和 `clms.html` 里的 `main.js?v=` 要保持一致。0.x 阶段按下面的规则自然递增，不用等到「攒够功能」再统一发版：

- **改了用户能感知的行为**（新功能、交互方式改变、接口变化）→ **次版本号 +1**（如 0.2.0 → 0.3.0），修订号清零。
- **只是修 bug、补文档、加测试、内部重构，用户感知不到差异** → **修订号 +1**（如 0.3.0 → 0.3.1）。
- 每次版本号变化都要在 `AI/changelog.md` 加一条对应条目；反过来，`changelog.md` 不应该出现没有对应版本号的条目。

## 代码到文档的对应关系

| 代码 | 文档 |
| --- | --- |
| `clms/ledger.py`、`clms/projections.py`、`clms/creation.py`、`clms/drafts.py` | `AI/data.md` |
| `clms/scheduling.py`、`clms/sessions.py`、`clms/taxonomy.py` | `AI/algorithm.md` |
| `clms/ai_assist.py`、`clms/draft_schema.py`、`clms/dictation.py` | `AI/ai.md` |
| `clms/harness.py`、`clms/agent.py`、`clms/agent_draft.py`、`clms/agent_ops.py` | `AI/ai.md`「Agent harness」 |
| `clms/review_ai.py` | `AI/ai.md`「复习助手」、`AI/api.md`「复习助手」 |
| `clms/records.py` | `AI/data.md`「复习记录」 |
| `clms/draft_runs.py`、`clms/live.py` | `AI/ai.md`「对话时间线与实时流」、`AI/data.md`「草稿」 |
| `clms/source_export.py` | `AI/api.md`「脱敏源码包」 |
| `clms/server.py`、`clms/library.py`、`clms/printing.py`、`clms/cli.py` | `AI/api.md` |
| `assets/app/core/`、`assets/app/ui/`、`assets/app/domain/`、`assets/app/shell.js`、`assets/app/styles/` | `AI/frontend.md` |
| `assets/app/features/entry/` | `AI/frontend.md`「录入页」 |
| `assets/app/features/dashboard/` | `AI/frontend.md`「其它页面」 |
| `assets/app/features/library/` | `AI/frontend.md`「其它页面」 |
| `assets/app/features/review/` | `AI/frontend.md`「其它页面」 |
| `assets/app/features/settings/` | `AI/frontend.md`「其它页面」 |
| `tests/` | `AI/README.md`「门禁」 |

新增文件找不到合适的行时，先补一行，不要让代码「挂空」在文档之外。

## 交付前

1. 门禁全部通过：
   ```bash
   python3 -m unittest discover -s tests -q
   python3 tests/check_ui.py
   python3 tests/e2e_main.py            # 改了页面行为时必须跑
   ```
2. 涉及页面的改动，真起服务、真开浏览器走一遍受影响的路径；单测全绿不等于能用，截图或肉眼看一眼实际渲染效果。
3. 按「文档维护规范」同步受影响的 `AI/` 文档，在 `AI/changelog.md` 顶部追加一条，按规则调整版本号。
4. 交付说明区分「已实际执行的验证」和「没有执行的验证」（例如真实模型没测、只测过模拟数据），不要用「应该没问题」代替实际跑过的证据。
