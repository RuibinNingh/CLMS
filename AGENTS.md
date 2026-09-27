# CLMS 仓库协作准则

CLMS 是 OMRS 的语文姊妹项目，架构、纪律和门禁都沿用 OMRS。本文件写给接手的维护者和 AI 助手。

## 开始任务前

- 先读 `AI/README.md` 的「按任务找文档」，只读和任务相关的模块文档。
- 判断现状以当前代码和测试为准；如果和 `AI/` 文档冲突，要在本任务里把文档改到与可验证的行为一致。
- 用户原话是目的，计划只是手段：先把诉求逐条抄成清单，每一步都能指回清单里的某一条。录入页（对话式录入 + 纸面草稿）是本项目的主诉求，改动它时优先保证真实浏览器里的体验。

## 不变量（改动前先确认没有破坏）

1. **Ledger 是唯一事实源。** 题库、材料、复习、评分只能通过 `ledger.transact()` / `append_commit()` 追加提交；修正也是追加（如 `review.void`），不改写、不删除旧行。新增提交类型时，要同时改 `projections.State` 的 `_on_<type>` 和 `AI/data.md`。
2. **草稿不进 Ledger。** `drafts/*.json` 是暂存层，只有入库时整份草稿写成一条 `entry.commit`，要么全部成功，要么全部失败。
3. **只比汉字。** 去重键和相似度都建立在 `common.chinese_only()` / `content_chars()` 之上；标点、全半角、空白的差异不能产生新题。
4. **默写一个空就是一道题。** 模板占位符统一写成 `{书写区域n}`，拆分后的题面用 `{书写区域}` 标出自己的空。
5. **记忆状态现算，不落表。** `scheduling.derive()` 按「今天」和复习日重放事件；不要把 sched 字段写进 Ledger。
6. **核心运行路径只用标准库。** Pillow 是可选依赖（缩图、切长图），缺了要能降级。
7. **默认只监听 127.0.0.1**；POST 请求校验同源。
8. **Agent 只经工具读写。** 模型不直接产出整份草稿；草稿、题库、记录、复习反馈都通过 `agent_draft.py` / `agent_ops.py` 的工具，工具再调用上面这些模块，所以 1–5 条对 Agent 同样成立。新增工具时同时改 `AI/ai.md` 的工具表和 `tests/fake_ai.py`。

## 前端纪律（`python3 tests/check_ui.py` 强制）

- 页面契约：`{ id, title, icon, workbench?, mount(root, ctx) → unmount }`，`ctx = { bus, store, router }`。页面之间不互相 import，联动走 bus。
- 模板一律用 `core/html.js` 的 html``（默认转义）；写 DOM 只经 `core/dom.js`（render / morph）。
- 事件一律用 `data-action / data-change / data-input` 委托，动作用 `defineActions('页面', {...})` 登记，卸载时注销。
- 颜色只写在 `styles/tokens.css`；字号、间距、圆角、阴影、层级、动效都用 token。断点只有 760 / 1160 / 1500。
- 单个 JS 文件不超过 400 行，CSS 不超过 300 行；超了就拆。
- 新增 `assets/app/features/<x>/` 时，必须同时登记到下表。

## 代码到文档的对应关系

| 代码 | 文档 |
| --- | --- |
| `clms/ledger.py`、`clms/projections.py`、`clms/creation.py`、`clms/drafts.py` | `AI/data.md` |
| `clms/scheduling.py`、`clms/sessions.py`、`clms/taxonomy.py` | `AI/algorithm.md` |
| `clms/ai_assist.py`、`clms/draft_schema.py`、`clms/dictation.py` | `AI/ai.md` |
| `clms/harness.py`、`clms/agent.py`、`clms/agent_draft.py`、`clms/agent_ops.py` | `AI/ai.md`「Agent harness」 |
| `clms/records.py` | `AI/data.md`「复习记录」 |
| `clms/source_export.py` | `AI/api.md`「脱敏源码包」 |
| `clms/server.py`、`clms/library.py`、`clms/printing.py`、`clms/cli.py` | `AI/api.md` |
| `assets/app/core/`、`assets/app/ui/`、`assets/app/domain/`、`assets/app/shell.js`、`assets/app/styles/` | `AI/frontend.md` |
| `assets/app/features/entry/` | `AI/frontend.md`「录入页」 |
| `assets/app/features/dashboard/` | `AI/frontend.md`「其它页面」 |
| `assets/app/features/library/` | `AI/frontend.md`「其它页面」 |
| `assets/app/features/review/` | `AI/frontend.md`「其它页面」 |
| `assets/app/features/settings/` | `AI/frontend.md`「其它页面」 |
| `tests/` | `AI/README.md`「门禁」 |

## 交付前

1. 门禁全部通过：
   ```bash
   python3 -m unittest discover -s tests -q
   python3 tests/check_ui.py
   python3 tests/e2e_main.py            # 改了页面行为时必须跑
   ```
2. 涉及页面的改动，真起服务、真开浏览器走一遍受影响的路径；单测全绿不等于能用。
3. 同步受影响的 `AI/` 文档，在 `AI/changelog.md` 顶部追加一条。
4. 交付说明区分「已实际执行的验证」和「没有执行的验证」（例如真实模型没测）。
