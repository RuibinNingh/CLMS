"""复习卷打印（对标 OMRS 的 A4 导出，但只做语文需要的：原文 + 小题 + 答题横线）。

- 每道小题后面按 blank_lines（录入时 AI 判断、可手调）画答题横线，行距与答题卡相近（9mm）。
- 默写把 {书写区域} 画成下划线，长度按答案字数估；同一道默写拆出的几个空都在卷上时合成一行，
  每个空标题号（不会出现「考上句时下句已印在卷上」）。
- 同一篇材料的小题排在原文之后；题号在整张卷子里连续编号。
- 附答案时另起一页，只列题号与答案，方便对照批改。
独立打印与页面内预览使用同一 HTML、内联 CSS 与浏览器排版模块（从当前服务 /assets/ 加载）。
自动留白由显式点击后真实测量参考答案得出；读取页面不修改题库。
"""

import html
import json

from .dictation import TARGET
from .taxonomy import GENRE_BY_CODE

CSS = """
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
body { margin: 0; color: #111; background: #e9ebe6; font-family: 'Songti SC','STSong','Noto Serif SC','Source Han Serif SC','SimSun',serif;
       font-size: 11pt; line-height: 1.75; }
.sheet { width: 178mm; margin: 0 auto; }
.print-page { width: 210mm; height: 297mm; padding: 16mm 16mm 18mm; background: white;
              position: relative; margin: 8mm auto; break-after: page; overflow: hidden; }
.print-page:last-child { break-after: auto; }
.print-content { height: 263mm; overflow: hidden; }
.print-page-number { position: absolute; bottom: 7mm; left: 16mm; right: 16mm;
                     text-align: center; font: 9pt sans-serif; color: #555; }
#print-pages { zoom: var(--print-scale, 1); }
#print-source, #print-measure { position: absolute; left: -20000px; top: 0; width: 178mm; visibility: hidden; }
#print-source { display: none; }
#print-measure { pointer-events: none; }
header { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: baseline; gap: 1mm 4mm;
         border-bottom: 1.5pt solid #111; padding-bottom: 2mm; margin-bottom: 5mm; }
header h1 { font-size: 16pt; margin: 0; letter-spacing: 0.1em; flex: 1 1 60%; min-width: 0; overflow-wrap: anywhere; }
header .meta { font-size: 9pt; color: #444; font-family: 'Noto Sans SC','PingFang SC','Microsoft YaHei',sans-serif; white-space: nowrap; }
section { margin-bottom: 7mm; }
h2 { font-size: 12pt; margin: 0 0 1mm; font-family: 'Noto Sans SC','PingFang SC','Microsoft YaHei',sans-serif; overflow-wrap: anywhere; }
.byline { font-size: 9pt; color: #555; margin: 0 0 2.5mm; font-family: 'Noto Sans SC','PingFang SC','Microsoft YaHei',sans-serif;
          overflow-wrap: anywhere; }
.text { border-left: 1pt solid #999; padding-left: 4mm; margin-bottom: 4mm; }
.text p { margin: 0 0 1mm; text-indent: 2em; }
.text.poetry p { text-indent: 0; text-align: center; letter-spacing: 0.08em; }
.text .note { font-size: 9pt; color: #444; text-indent: 0; }
.q { break-inside: avoid; margin-bottom: 3mm; }
.q .stem { white-space: pre-wrap; overflow-wrap: anywhere; }
.q .no { font-weight: bold; margin-right: 1mm; }
.q .tag { font-size: 8.5pt; color: #555; border: 0.6pt solid #888; border-radius: 2pt; padding: 0 1.2mm; margin-right: 1mm;
          font-family: 'Noto Sans SC','PingFang SC','Microsoft YaHei',sans-serif; }
.lines { margin-top: 1mm; font: inherit; line-height: 9mm; white-space: pre-wrap; overflow-wrap: anywhere; }
.lines div { height: 9mm; border-bottom: 0.6pt solid #9aa; }
.answer-measure { font: inherit; line-height: 9mm; white-space: pre-wrap; overflow-wrap: anywhere; }
.q-continued { font: 8.5pt sans-serif; color: #555; }
.blank { display: inline-block; border-bottom: 0.8pt solid #111; vertical-align: bottom; height: 1.4em; position: relative; }
.blank sup { position: absolute; left: 0.2em; top: -0.2em; font-size: 7pt; color: #666; font-family: sans-serif; }
.answers { break-before: page; }
.answers ol { padding-left: 7mm; }
.answers li, .answer-entry { margin-bottom: 1.5mm; white-space: pre-wrap; overflow-wrap: anywhere; break-inside: avoid; }
.toolbar { position: fixed; top: 8px; right: 8px; font-family: sans-serif; }
.toolbar button { font-size: 13px; padding: 6px 14px; }
@media print {
  body { background: white; }
  .toolbar, #print-source { display: none; }
  #print-pages { zoom: 1; }
  .print-page { margin: 0; box-shadow: none; }
}
"""


def _e(text) -> str:
    return html.escape(str(text or ""))


def _paragraphs(text: str, genre: str) -> str:
    out = []
    for para in [p.strip() for p in str(text or "").split("\n") if p.strip()]:
        cls = ' class="note"' if para.startswith("注") else ""
        out.append(f"<p{cls}>{_e(para)}</p>")
    extra = " poetry" if genre == "poetry" else ""
    return f'<div class="text{extra}">{"".join(out)}</div>'


def _blank(answer: str, label: str = "") -> str:
    width = max(4, round(len(answer or "") * 1.15 + 1.5))
    tag = f'<sup>{_e(label)}</sup>' if label else ""
    return f'<span class="blank" style="width:{width}em">{tag}</span>'


def _dictation_line(group) -> str:
    """同一道默写题拆出的几个空如果都在这次复习里，合成一行、每个空标上题号，
    避免「考上句时下句已经印在卷子上」。group = [(题号, item), …]，第一项的题面是基准。"""
    first_no, first = group[0]
    stem = first["stem"]
    markers = {}
    for no, item in group[1:]:
        marker = f"\x00{no}\x00"
        if item["answer"] and item["answer"] in stem:
            stem = stem.replace(item["answer"], marker, 1)
            markers[marker] = (no, item)
    labelled = len(group) > 1
    out = []
    for piece in stem.split(TARGET):
        chunk = _e(piece)
        for marker, (no, item) in markers.items():
            chunk = chunk.replace(_e(marker), _blank(item["answer"], str(no)))
        out.append(chunk)
    body = _blank(first["answer"], str(first_no) if labelled else "").join(out)
    source = f' <span class="tag">{_e(first.get("source"))}</span>' if first.get("source") else ""
    return body + source


def _dictation_groups(items):
    """按录入时的同一模板把默写小题分组（模板相同且答案能在题面里找到才合并）。"""
    groups, index = [], {}
    for no, item in items:
        key = item.get("template") or ""
        target = index.get(key) if key else None
        if target is not None and item["answer"] and item["answer"] in groups[target][0][1]["stem"]:
            groups[target].append((no, item))
            continue
        if key:
            index[key] = len(groups)
        groups.append([(no, item)])
    return groups


def render_session(session: dict, with_answers: bool = False) -> str:
    materials = session["materials"]
    blocks, answers = [], []
    numbered = list(enumerate(session["items"], 1))
    dictation = [(no, it) for no, it in numbered if it["genre"] == "dictation"]
    current_mat = None
    for no, item in numbered:
        genre = item["genre"]
        answers.append((no, item["answer"]))
        if genre == "dictation":
            continue
        mid = item.get("material_id")
        if mid != current_mat:
            if current_mat is not None:
                blocks.append("</section>")
            mat = materials.get(mid, {})
            byline = " ".join(x for x in (mat.get("author"), mat.get("source")) if x)
            by = f'<p class="byline">{_e(byline)}</p>' if byline else ""      # 作者 / 出处另起一行：长标题、长出处都能完整换行
            blocks.append(f'<section><h2>{_e(GENRE_BY_CODE[genre]["short"])} · {_e(mat.get("title") or "无题")}</h2>'
                          f'{by}{_paragraphs(mat.get("text"), genre)}')
            current_mat = mid
        score = f'（{item["score"]:g} 分）' if isinstance(item.get("score"), (int, float)) else ""
        lines = "".join("<div></div>" for _ in range(int(item.get("blank_lines") or 0)))
        blocks.append(f'<div class="q" data-item="{_e(item["id"])}" data-no="{no}"><div class="stem"><span class="no">{no}.</span>'
                      f'<span class="tag">{_e(item.get("qtype") or "未分类")}</span>{_e(item["stem"])}{score}</div>'
                      f'<div class="lines">{lines}</div></div>')
    if current_mat is not None:
        blocks.append("</section>")
    if dictation:
        blocks.append('<section><h2>名句默写</h2>')
        for group in _dictation_groups(dictation):
            nos = [str(no) for no, _ in group]
            label = nos[0] if len(nos) == 1 else "、".join(nos)
            blocks.append(f'<div class="q dictation"><span class="no">{label}.</span>{_dictation_line(group)}</div>')
        blocks.append("</section>")
    answer_html = ""
    if with_answers:
        answer_html = ('<section class="answers"><h2>参考答案</h2><ol>'
                       + "".join(f'<li value="{no}">{_e(a)}</li>' for no, a in answers) + "</ol></section>")
    title = session.get("title") or f"语文复习 {session['id']}"
    meta = f"{_e(session.get('planned_for'))} · {len(session['items'])} 题 · 约 {session.get('minutes') or '—'} 分钟"
    data = json.dumps({"session": session, "with_answers": with_answers}, ensure_ascii=False).replace("<", "\\u003c")
    return (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{_e(title)}</title>'
            f'<style id="print-css">{CSS}</style></head><body>'
            '<div class="toolbar"><button data-action="paper.print">打印</button></div>'
            f'<div class="sheet" id="print-source"><header><h1>{_e(title)}</h1><span class="meta">{meta}</span></header>'
            f'{"".join(blocks)}{answer_html}</div><div id="print-measure"></div><main id="print-pages"></main>'
            f'<script type="application/json" id="print-data">{data}</script>'
            '<script type="module" src="/assets/app/domain/print-layout.js"></script></body></html>')


def update_blank_lines(vault: str, session_id: str, changes: list) -> dict:
    """人工调整默认留白；批量整体验证与提交，不改变 Session 的身份或评分。"""
    from . import creation, ledger, sessions
    from .projections import get_state

    if not isinstance(changes, list) or not changes or len(changes) > 500:
        raise ValueError("请提交 1–500 道题的留白调整")
    rows, seen = [], set()
    for row in changes:
        if not isinstance(row, dict):
            raise ValueError("留白调整格式不正确")
        item_id, value = row.get("item_id"), row.get("blank_lines")
        if not isinstance(item_id, str) or item_id in seen:
            raise ValueError("题目编号为空或重复")
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1000:
            raise ValueError("答题留白必须是 0–1000 的整数")
        seen.add(item_id)
        rows.append((item_id, value))

    def build(tx):
        state = get_state(vault)
        sess = state.sessions.get(session_id)
        if not sess or sess["cancelled"]:
            raise KeyError("找不到这次复习")
        members = {entry["id"] for entry in sess["items"]}
        updates = []
        for item_id, value in rows:
            if item_id not in members:
                raise ValueError("这道题不在本次复习里：" + item_id)
            payload = creation.prepare_item_changes(vault, item_id, {"blank_lines": value}, state=state)
            if state.items[item_id].get("blank_lines", 0) != value:
                updates.append(payload)
        for payload in updates:
            tx.append("library", "item.update", f"调整 {sessions.describe(state, payload['item_id'])} 的默认留白",
                      payload)
        return [p["item_id"] for p in updates]

    updated, _ = ledger.transact(vault, build)
    return {"session": sessions.view(vault, session_id), "updated": updated}
