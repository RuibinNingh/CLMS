"""完整作文领域服务。Prompt → Attempt → 多 Version → 多 Evaluation。

作文从不进入普通题目、Session 或记忆曲线。原图只保存不可变内容文件，
其归属、OCR、校对、正式文本、评价、笔记与分类全部追加到 Ledger。
"""

import copy
import difflib
import json
import math
import os

from . import drafts, ledger
from .projections import get_state

TARGETS = {"prompt": "essay_prompts", "attempt": "essay_attempts", "version": "essay_versions"}
MAX_TEXT = 100000


def _text(value, label, *, required=False, maximum=MAX_TEXT):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(label + "必须是文本")
    if len(value) > maximum:
        raise ValueError(f"{label}不能超过 {maximum} 字")
    if required and not value.strip():
        raise ValueError(label + "不能为空")
    return value


def _metadata(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("metadata 必须是对象")
    try:
        serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError("metadata 必须是有效 JSON 对象") from None
    if len(serialized) > 16000:
        raise ValueError("metadata 过长")
    return json.loads(serialized)


def _source(value):
    return _text(value or "web", "来源", maximum=200)


def _get(state, table, object_id, label):
    if object_id is not None and not isinstance(object_id, str):
        raise ValueError(label + "编号必须是文本")
    result = getattr(state, table).get(object_id)
    if result is None:
        raise KeyError(f"{label}不存在：{object_id}")
    return result


def _revision(record, expected):
    if expected is not None and (type(expected) is not int or expected != record["revision"]):
        raise ValueError("作文版本已变化，请刷新后再操作")


def _public(record):
    return copy.deepcopy({key: value for key, value in record.items() if key not in ("ocr_token",)})


def _classes(state, record):
    return [_public(state.essay_classifications[cid]) for cid in record.get("classification_ids", [])
            if cid in state.essay_classifications]


def _version_view(state, version):
    view = _public(version)
    view["evaluations"] = [_public(state.essay_evaluations[eid]) for eid in version["evaluation_ids"]]
    view["notes"] = [_public(state.essay_notes[nid]) for nid in version["note_ids"]]
    view["classifications"] = _classes(state, version)
    view["can_retry"] = version["status"] == "ocr_failed"
    view["evaluation_pending"] = version["status"] == "confirmed" and not version["evaluation_ids"]
    view["image_urls"] = [f"/api/essay/image?version_id={version['id']}&image={image}"
                          for image in version["images"]]
    return view


def _attempt_view(state, attempt, *, versions=True):
    view = _public(attempt)
    view["version_count"] = len(attempt["version_ids"])
    view["modification_count"] = max(0, view["version_count"] - 1)
    view["current_version_id"] = attempt["version_ids"][-1] if attempt["version_ids"] else None
    view["notes"] = [_public(state.essay_notes[nid]) for nid in attempt["note_ids"]]
    view["classifications"] = _classes(state, attempt)
    if versions:
        view["versions"] = [_version_view(state, state.essay_versions[vid]) for vid in attempt["version_ids"]]
    return view


def _prompt_view(state, prompt, *, attempts=True):
    view = _public(prompt)
    view["attempt_count"] = len(prompt["attempt_ids"])
    view["last_attempt_at"] = (state.essay_attempts[prompt["attempt_ids"][-1]]["created_at"]
                               if prompt["attempt_ids"] else "")
    view["classifications"] = _classes(state, prompt)
    if attempts:
        view["attempts"] = [_attempt_view(state, state.essay_attempts[aid], versions=False)
                            for aid in reversed(prompt["attempt_ids"])]
    return view


def create_prompt(vault, title, text, requirements="", *, source="web", metadata=None):
    values = {"title": _text(title, "标题", required=True, maximum=200).strip(),
              "text": _text(text, "作文题正文", required=True),
              "requirements": _text(requirements, "写作要求"), "source": _source(source),
              "metadata": _metadata(metadata), "practice_type": "complete", "max_score": 60}

    def build(tx):
        prompt_id = tx.next_id("EP")
        tx.append(values["source"], "essay.prompt.create", "创建作文题「" + values["title"] + "」",
                  {"prompt": dict(values, id=prompt_id)})
        return {"prompt_id": prompt_id}
    result, _ = ledger.transact(vault, build)
    return prompt_detail(vault, result["prompt_id"])


def list_prompts(vault, q="", classification_id="", offset=0, limit=60):
    state = get_state(vault)
    query = str(q or "").strip().casefold()
    try:
        offset, limit = max(0, int(offset)), min(200, max(1, int(limit)))
    except (TypeError, ValueError):
        raise ValueError("分页参数无效") from None
    records = []
    for prompt in state.essay_prompts.values():
        if classification_id and classification_id not in prompt["classification_ids"]:
            continue
        labels = " ".join(c["name"] for c in _classes(state, prompt))
        haystack = " ".join(str(prompt.get(k) or "") for k in ("title", "text", "requirements", "source")) + labels
        if query and query not in haystack.casefold():
            continue
        records.append(prompt)
    records.sort(key=lambda p: (p["updated_at"], p["last_seq"]), reverse=True)
    return {"prompts": [_prompt_view(state, p, attempts=False) for p in records[offset:offset + limit]],
            "total": len(records), "offset": offset, "limit": limit,
            "classifications": list_classifications(vault)}


def prompt_detail(vault, prompt_id):
    state = get_state(vault)
    return _prompt_view(state, _get(state, "essay_prompts", prompt_id, "作文题"))


def create_attempt(vault, prompt_id, title="", *, source="web", metadata=None):
    title, source, metadata = _text(title, "练习标题", maximum=200).strip(), _source(source), _metadata(metadata)

    def build(tx):
        prompt = _get(get_state(vault), "essay_prompts", prompt_id, "作文题")
        attempt_id = tx.next_id("EA")
        tx.append(source, "essay.attempt.create", "开始作文练习「" + prompt["title"] + "」",
                  {"attempt": {"id": attempt_id, "prompt_id": prompt_id, "title": title,
                               "source": source, "metadata": metadata}})
        return {"attempt_id": attempt_id}
    result, _ = ledger.transact(vault, build)
    return attempt_detail(vault, result["attempt_id"])


def attempt_detail(vault, attempt_id):
    state = get_state(vault)
    attempt = _get(state, "essay_attempts", attempt_id, "作文练习")
    result = _attempt_view(state, attempt)
    result["prompt"] = _prompt_view(state, state.essay_prompts[attempt["prompt_id"]], attempts=False)
    return result


def create_version(vault, attempt_id, images, *, source="web", metadata=None):
    if not isinstance(images, list) or not images or len(images) > 30:
        raise ValueError("一版作文需要 1–30 张原图，多页请一次提交")
    source, metadata = _source(source), _metadata(metadata)
    _get(get_state(vault), "essay_attempts", attempt_id, "作文练习")
    # 文件写入/解码在 Ledger 事务外；孤立内容文件不构成学习事实。
    image_ids = [drafts.receive_image(vault, {"image": image} if isinstance(image, str) else image)
                 for image in images]

    def build(tx):
        attempt = _get(get_state(vault), "essay_attempts", attempt_id, "作文练习")
        version_id = tx.next_id("EV")
        number = len(attempt["version_ids"]) + 1
        tx.append(source, "essay.version.create", f"上传作文第 {number} 稿（{len(image_ids)} 页）",
                  {"version": {"id": version_id, "attempt_id": attempt_id, "prompt_id": attempt["prompt_id"],
                               "number": number, "images": image_ids, "source": source, "metadata": metadata}})
        return {"version_id": version_id}
    result, _ = ledger.transact(vault, build)
    return version_detail(vault, result["version_id"])


def version_detail(vault, version_id):
    state = get_state(vault)
    version = _get(state, "essay_versions", version_id, "作文稿件")
    result = _version_view(state, version)
    result["prompt"] = _prompt_view(state, state.essay_prompts[version["prompt_id"]], attempts=False)
    return result


def version_image_path(vault, version_id, image):
    version = _get(get_state(vault), "essay_versions", version_id, "作文稿件")
    if image not in version["images"]:
        raise ValueError("图片不属于指定作文版本")
    path = drafts.image_path(vault, image)
    if not os.path.isfile(path):
        raise KeyError("作文原图不存在")
    return path


def correct_version(vault, version_id, text, revision=None, *, source="web"):
    text, source = _text(text, "校对文本"), _source(source)

    def build(tx):
        version = _get(get_state(vault), "essay_versions", version_id, "作文稿件")
        _revision(version, revision)
        if version["status"] not in ("proofreading", "uploaded", "ocr_failed"):
            raise ValueError("只能校对未确认且没有正在识别的稿件，正式正文请创建下一版本")
        if version["corrected_text"] != text or version["status"] != "proofreading":
            tx.append(source, "essay.version.correct", "校对作文转写（不增加版本）",
                      {"version_id": version_id, "text": text})
        return {"version_id": version_id}
    ledger.transact(vault, build)
    return version_detail(vault, version_id)


def confirm_version(vault, version_id, text=None, revision=None, *, source="web"):
    source = _source(source)
    if text is not None:
        text = _text(text, "正式文本", required=True)

    def build(tx):
        version = _get(get_state(vault), "essay_versions", version_id, "作文稿件")
        if version["status"] == "confirmed":
            if text is None or text == version["text"]:
                return {"version_id": version_id}
            raise ValueError("已确认正文不可覆盖，请创建下一稿")
        _revision(version, revision)
        if version["status"] != "proofreading":
            raise ValueError("请先完成 OCR 或手工校对，再确认正式转写")
        final_text = _text(version["corrected_text"] if text is None else text, "正式文本", required=True)
        tx.append(source, "essay.version.confirm", "确认作文正式转写，等待评价",
                  {"version_id": version_id, "text": final_text})
        return {"version_id": version_id}
    ledger.transact(vault, build)
    return version_detail(vault, version_id)


def _string_list(value, label):
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError(label + "必须是文本数组（最多 100 项）")
    return [_text(v, label, maximum=10000) for v in value]


def add_evaluation(vault, version_id, total_score, summary="", strengths=None, issues=None,
                   suggestions=None, dimensions=None, *, evaluator="human", source="web", model="", metadata=None):
    if isinstance(total_score, bool) or not isinstance(total_score, (int, float)) or not math.isfinite(total_score):
        raise ValueError("作文总分必须是 0–60 的数字")
    if not 0 <= total_score <= 60:
        raise ValueError("作文总分必须在 0–60 范围内")
    if dimensions is not None:
        try:
            dimensions = json.loads(json.dumps(dimensions, ensure_ascii=False, allow_nan=False))
        except (TypeError, ValueError):
            raise ValueError("dimensions 必须是有效 JSON") from None
        if len(json.dumps(dimensions, ensure_ascii=False)) > 20000:
            raise ValueError("dimensions 过长")
    values = {"total_score": total_score, "max_score": 60, "summary": _text(summary, "评价摘要"),
              "strengths": _string_list(strengths, "优点"), "issues": _string_list(issues, "问题"),
              "suggestions": _string_list(suggestions, "建议"), "dimensions": dimensions,
              "evaluator": _text(evaluator, "评价者", maximum=200), "source": _source(source),
              "model": _text(model, "模型", maximum=200), "metadata": _metadata(metadata)}

    def build(tx):
        version = _get(get_state(vault), "essay_versions", version_id, "作文稿件")
        if version["status"] != "confirmed":
            raise ValueError("请先确认正式转写，再保存评价")
        evaluation_id = tx.next_id("EE")
        tx.append(values["source"], "essay.evaluation.add", f"追加作文评价 {total_score}/60",
                  {"evaluation": dict(values, id=evaluation_id, version_id=version_id,
                                      attempt_id=version["attempt_id"], prompt_id=version["prompt_id"])})
        return {"evaluation_id": evaluation_id}
    result, _ = ledger.transact(vault, build)
    return evaluation_detail(vault, result["evaluation_id"])


def evaluation_detail(vault, evaluation_id):
    return _public(_get(get_state(vault), "essay_evaluations", evaluation_id, "作文评价"))


def adopt_evaluation(vault, version_id, evaluation_id, *, source="web"):
    source = _source(source)

    def build(tx):
        state = get_state(vault)
        version = _get(state, "essay_versions", version_id, "作文稿件")
        evaluation = _get(state, "essay_evaluations", evaluation_id, "作文评价")
        if evaluation["version_id"] != version_id:
            raise ValueError("评价不属于指定版本")
        if version["adopted_evaluation_id"] != evaluation_id:
            tx.append(source, "essay.evaluation.adopt", "选择当前采用的作文评价",
                      {"version_id": version_id, "evaluation_id": evaluation_id})
        return {"version_id": version_id}
    ledger.transact(vault, build)
    return version_detail(vault, version_id)


def add_note(vault, attempt_id, text, version_id=None, *, source="web", metadata=None):
    text, source, metadata = _text(text, "讨论笔记", required=True), _source(source), _metadata(metadata)

    def build(tx):
        state = get_state(vault)
        attempt = _get(state, "essay_attempts", attempt_id, "作文练习")
        if version_id and _get(state, "essay_versions", version_id, "作文稿件")["attempt_id"] != attempt_id:
            raise ValueError("版本不属于指定练习")
        note_id = tx.next_id("EN")
        tx.append(source, "essay.note.add", "追加作文讨论笔记",
                  {"note": {"id": note_id, "attempt_id": attempt_id, "prompt_id": attempt["prompt_id"],
                            "version_id": version_id or None, "text": text, "source": source, "metadata": metadata}})
        return {"note_id": note_id}
    result, _ = ledger.transact(vault, build)
    return note_detail(vault, result["note_id"])


def note_detail(vault, note_id):
    return _public(_get(get_state(vault), "essay_notes", note_id, "作文笔记"))


def list_classifications(vault):
    state = get_state(vault)
    return [_public(c) for c in sorted(state.essay_classifications.values(), key=lambda c: c["name"])]


def _classification(values, name, group, source, metadata, tx):
    name = _text(name, "分类名称", required=True, maximum=100).strip()
    group = _text(group, "分类组", maximum=100).strip()
    existing = next((c for c in values if c["name"] == name and c.get("group", "") == group), None)
    if existing:
        return existing
    record = {"id": tx.next_id("EC"), "name": name, "group": group, "source": source, "metadata": metadata}
    tx.append(source, "essay.classification.create", "创建作文分类「" + name + "」", {"classification": record})
    values.append(record)
    return record


def create_classification(vault, name, group="", *, source="web", metadata=None):
    source, metadata = _source(source), _metadata(metadata)

    def build(tx):
        values = list(get_state(vault).essay_classifications.values())
        record = _classification(values, name, group, source, metadata, tx)
        return {"classification_id": record["id"]}
    result, _ = ledger.transact(vault, build)
    return _public(get_state(vault).essay_classifications[result["classification_id"]])


def classify(vault, target_type, target_id, classification_ids=None, names=None, *, source="web", metadata=None):
    if not isinstance(target_type, str) or target_type not in TARGETS:
        raise ValueError("分类目标只支持 prompt / attempt / version")
    classification_ids, names = classification_ids or [], names or []
    if not isinstance(classification_ids, list) or not isinstance(names, list) or len(classification_ids) + len(names) > 100:
        raise ValueError("分类参数必须是数组且总数不超过 100")
    source, metadata = _source(source), _metadata(metadata)

    def build(tx):
        state = get_state(vault)
        target = _get(state, TARGETS[target_type], target_id, "分类目标")
        ids = [_get(state, "essay_classifications", cid, "作文分类")["id"] for cid in classification_ids]
        values = list(state.essay_classifications.values())
        for name in names:
            fields = name if isinstance(name, dict) else {"name": name}
            ids.append(_classification(values, fields.get("name"), fields.get("group", ""), source, metadata, tx)["id"])
        ids = [cid for cid in dict.fromkeys(ids) if cid not in target["classification_ids"]]
        if ids:
            tx.append(source, "essay.classification.assign", "添加作文自由分类",
                      {"target_type": target_type, "target_id": target_id, "classification_ids": ids,
                       "metadata": metadata})
        return {"target_type": target_type, "target_id": target_id}
    ledger.transact(vault, build)
    return {"target_type": target_type, "target_id": target_id,
            "classifications": _classes(get_state(vault), getattr(get_state(vault), TARGETS[target_type])[target_id])}


def compare_versions(vault, before_id, after_id):
    state = get_state(vault)
    before = _get(state, "essay_versions", before_id, "旧作文稿件")
    after = _get(state, "essay_versions", after_id, "新作文稿件")
    if before["attempt_id"] != after["attempt_id"]:
        raise ValueError("只能比较同一次练习的两个版本")
    if before["status"] != "confirmed" or after["status"] != "confirmed":
        raise ValueError("只能比较已确认的正式文本")
    # 普通完整作文逐字比较；极长正文改按段落比较，避免重复字符造成二次方开销。
    old, new = before["text"], after["text"]
    if len(old) + len(new) > 20000:
        old = old.splitlines(keepends=True)
        new = new.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=True)
    join = lambda value: "".join(value) if isinstance(value, list) else value
    changes = [{"kind": kind, "before": join(old[i:j]), "after": join(new[k:l])}
               for kind, i, j, k, l in matcher.get_opcodes()]
    return {"before_id": before_id, "after_id": after_id, "changes": changes}
