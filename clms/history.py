"""学习与变更历史：只读 Ledger，先筛选后分页，不推测运行事实。"""
import json

from .ledger import read_commits


def _source(commit):
    operation = (commit.get("payload") or {}).get("_operation") or {}
    return operation.get("source") or commit["source"]


def references(commit):
    payload = commit.get("payload") or {}
    links = []
    def add(page, field, value, label):
        if value and not any(x["id"] == value and x["page"] == page for x in links):
            links.append({"page": page, "field": field, "id": str(value), "label": label})
    # 作文提交会保留所属链；从评价/笔记直接定位被评价的原版本。
    for container in [payload, *[v for v in payload.values() if isinstance(v, dict)]]:
        for key, page, field, label in [
            ("version_id", "essays", "version", "打开作文版本"),
            ("attempt_id", "essays", "attempt", "打开写作练习"),
            ("prompt_id", "essays", "prompt", "打开作文题"),
            ("session_id", "review", "session", "打开复习"),
            ("item_id", "library", "item", "打开题目"),
            ("draft_id", "entry", "draft", "打开录入草稿"),
            ("operation_id", "audit", "id", "打开审核")]:
            add(page, field, container.get(key), label)
    kind = commit.get("commit_type", "")
    add("audit", "id", (payload.get("_operation") or {}).get("id"), "打开审核")
    if kind == "essay.classification.assign" and payload.get("target_type") in {"prompt", "attempt", "version"}:
        add("essays", payload["target_type"], payload.get("target_id"), "打开作文")
    if kind.startswith("session."):
        add("review", "session", payload.get("id"), "打开复习")
    for item in payload.get("items", [])[:20]:
        if isinstance(item, dict):
            add("library", "item", item.get("id"), "打开题目 " + str(item.get("id", "")))
    essay = {"essay.prompt.create": ("prompt", "prompt"),
             "essay.attempt.create": ("attempt", "attempt"),
             "essay.version.create": ("version", "version")}
    if kind in essay:
        field, nested = essay[kind]
        obj = payload.get(nested, payload)
        add("essays", field, obj.get("id"), "打开作文")
    return links


def list_learning(vault, options=None):
    options = options or {}
    query = str(options.get("q") or "").strip().casefold()
    source = str(options.get("source") or "")
    kind = str(options.get("type") or "")
    since, until = str(options.get("from") or ""), str(options.get("to") or "")
    offset = max(0, int(options.get("offset") or 0))
    limit = max(1, min(100, int(options.get("limit") or 50)))
    result = []
    all_rows = read_commits(vault)
    for commit in reversed(all_rows):
        date = commit["created_at"][:10]
        if source and _source(commit) != source or kind and not commit["commit_type"].startswith(kind):
            continue
        if since and date < since[:10] or until and date > until[:10]:
            continue
        if query and query not in json.dumps(commit, ensure_ascii=False).casefold():
            continue
        row = {k: commit[k] for k in ("seq", "commit_id", "created_at", "source", "commit_type", "message")}
        row["domain_source"], row["source"] = commit["source"], _source(commit)
        row["id"], row["links"] = row["commit_id"], references(commit)
        result.append(row)
    return {"items": result[offset:offset + limit], "total": len(result), "offset": offset,
            "has_more": offset + limit < len(result), "next_offset": offset + limit,
            "sources": sorted({_source(r) for r in all_rows}),
            "types": sorted({r["commit_type"] for r in all_rows})}


def detail(vault, commit_id):
    for commit in read_commits(vault):
        if commit["commit_id"] == commit_id:
            return {**commit, "domain_source": commit["source"], "source": _source(commit),
                    "id": commit_id, "links": references(commit)}
    raise KeyError("找不到这条学习记录")
