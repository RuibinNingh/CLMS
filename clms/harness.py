"""Agent harness（对标 Pi agent-core 的 agent-loop，只用标准库）。

一次 run = 若干轮（turn）：把上下文发给模型 → 模型回复文字和 / 或工具调用 → 逐个执行工具 → 工具结果回到上下文
→ 下一轮；模型不再调用工具时结束。和 Pi 一样：

- 事件流：agent_start / message_start / delta（思考、正文逐字）/ toolcall_delta（工具参数逐字）/ message_end /
  tool_start / tool_update / tool_end / sub（子代理的事件，原样包一层）/ turn_end / steer / agent_end，
  由 on_event 回调接走（drafts.py 把它们变成对话里的块，经 live.py + SSE 实时推给前端）。
- 思考：模型回复里的 thinking 只展示，不回传给模型。
- 插话（steering）：run 进行中用户又发了话，下一次请求模型之前插进上下文；模型本来要停时也会再看一遍队列。
- 停止（abort）：每次请求模型前、每个工具执行前检查；停止后不再写任何东西。
- 输出被截断（finish_reason=length）时，这一轮的工具调用一律不执行，改回一条错误结果，让模型重发完整参数。
- 工具返回 terminate=True 且整批都如此时，不再追问模型。
- 图片：消息里只存引用（{"page": n} 或 {"image": id}），发送前由 render_images 转成 data URL；
  只有「本次 run」的图片会真的发出去，更早的换成一句占位说明（省 token），需要时让模型调用 view_pages 再看。
- 上下文过长时保留第一条用户消息 + 最近的若干条（从一条 assistant 消息开始，不拆开工具调用与结果）。

消息格式（内部，接近 OpenAI）：
  {"role": "user", "content": str, "images": [ref...], "run": run_id}
  {"role": "assistant", "content": str, "tool_calls": [{"id", "name", "arguments"(str)}]}
  {"role": "tool", "tool_call_id", "name", "content": str}
"""

import json
import threading
import time

MAX_TOOL_CHARS = 12000
KEEP_MESSAGES = 48


class ToolError(Exception):
    """工具执行失败：消息原样回给模型（中文，告诉它怎么改）。"""


class Aborted(Exception):
    pass


class ToolResult:
    def __init__(self, content, details=None, is_error=False, images=None, terminate=False):
        self.content = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        self.details = details or {}
        self.is_error = is_error
        self.images = images or []
        self.terminate = terminate


class Tool:
    """name / description / parameters(JSON Schema) / execute(args, ctx) → ToolResult | dict | str。
    label(args) 给界面看的一句话（「第 7 题 · 改答案」）。"""

    def __init__(self, name, description, parameters, execute, label=None):
        self.name, self.description, self.parameters = name, description, parameters
        self.execute, self._label = execute, label

    def label(self, args) -> str:
        try:
            return self._label(args) if self._label else self.name
        except Exception:  # noqa: BLE001 - 标签只是展示
            return self.name

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}


class ToolContext:
    """工具执行时拿到的上下文：update(details) 推送进度（Pi 的 tool_execution_update）；
    sub_events(task) 给子代理用的事件出口（把子代理的整条事件流挂在这次工具调用下面）。"""

    def __init__(self, agent, call):
        self.agent, self.call = agent, call

    def update(self, details: dict):
        self.agent.emit({"type": "tool_update", "id": self.call["id"], "name": self.call["name"], "details": details})

    def sub_events(self, task):
        return lambda event: self.agent.emit({"type": "sub", "parent": self.call["id"], "task": task, "event": event})

    @property
    def aborted(self) -> bool:
        return self.agent.aborted()


def _schema_check(schema: dict, args: dict) -> str:
    """最小的参数校验：必填项、类型。返回错误说明，空串表示通过。"""
    if not isinstance(args, dict):
        return "参数必须是 JSON 对象"
    props = schema.get("properties") or {}
    missing = [k for k in schema.get("required") or [] if args.get(k) in (None, "")]
    if missing:
        return "缺少必填参数：" + "、".join(missing)
    kinds = {"string": str, "integer": int, "number": (int, float), "array": list, "object": dict, "boolean": bool}
    for key, value in args.items():
        spec = props.get(key)
        if not spec or value is None:
            continue
        want = spec.get("type")
        types = want if isinstance(want, list) else [want]
        ok = any(t in kinds and isinstance(value, kinds[t]) and not (t in ("integer", "number") and isinstance(value, bool))
                 for t in types if t)
        if want and not ok:
            if "integer" in types and isinstance(value, str) and value.strip().lstrip("-").isdigit():
                args[key] = int(value)
                continue
            if "number" in types and isinstance(value, str):
                try:
                    args[key] = float(value)
                    continue
                except ValueError:
                    pass
            return f"参数 {key} 应为 {'/'.join(t for t in types if t)}"
    return ""


class Agent:
    """llm(messages_openai, tool_schemas, on_delta) → {content, thinking, tool_calls:[{id,name,arguments}], finish_reason}。
    on_delta(kind, data)：kind = thinking / text / toolcall（data = {index, name, delta}）。"""

    def __init__(self, *, llm, tools, system_prompt, render_images, run_id, max_turns=30,
                 on_event=None, steering=None, abort=None, name="main"):
        self.llm, self.tools, self.system_prompt = llm, list(tools), system_prompt
        self.render_images, self.run_id, self.max_turns = render_images, run_id, max_turns
        self.on_event, self.steering, self.abort_event, self.name = on_event, steering, abort, name
        self.turns = 0
        self.tool_calls = 0
        self._lock = threading.Lock()

    # ── 事件 ────────────────────────────────────────────
    def emit(self, event: dict):
        if self.on_event and not self.aborted():
            event.setdefault("agent", self.name)
            with self._lock:
                self.on_event(event)

    def aborted(self) -> bool:
        return bool(self.abort_event is not None and self.abort_event.is_set())

    def _check_abort(self):
        if self.aborted():
            raise Aborted()

    # ── 上下文 → OpenAI 消息 ────────────────────────────
    def _trim(self, messages: list) -> list:
        if len(messages) <= KEEP_MESSAGES:
            return messages
        start = len(messages) - KEEP_MESSAGES
        while start < len(messages) and messages[start]["role"] != "assistant":
            start += 1
        if start >= len(messages):
            return messages
        note = {"role": "user", "content": "（更早的对话已省略；草稿的当前状态以 draft_view 为准。）"}
        return [messages[0], note] + messages[start:]

    def to_llm(self, messages: list) -> list:
        out = []
        trimmed = self._trim(messages)
        if self.system_prompt and (not trimmed or trimmed[0]["role"] != "user"):
            out.append({"role": "user", "content": self.system_prompt})
        for n, msg in enumerate(trimmed):
            role = msg["role"]
            if role == "user":
                text = msg.get("content") or ""
                if n == 0 and self.system_prompt:       # 不用 system 角色：兼容不建议设 system 的视觉模型
                    text = self.system_prompt + "\n\n---\n\n" + text
                refs = msg.get("images") or []
                if refs and msg.get("run") == self.run_id:
                    parts = [{"type": "image_url", "image_url": {"url": url}} for url in self.render_images(refs)]
                    parts.append({"type": "text", "text": text or "（见图）"})
                    out.append({"role": "user", "content": parts})
                    continue
                if refs:
                    text += f"\n（这里附过 {len(refs)} 张图，本轮不再重发；需要再看请调用 view_pages。）"
                out.append({"role": "user", "content": text})
            elif role == "assistant":
                item = {"role": "assistant", "content": msg.get("content") or ""}
                if msg.get("tool_calls"):
                    item["tool_calls"] = [{"id": c["id"], "type": "function",
                                           "function": {"name": c["name"], "arguments": c["arguments"]}}
                                          for c in msg["tool_calls"]]
                out.append(item)
            elif role == "tool":
                out.append({"role": "tool", "tool_call_id": msg["tool_call_id"], "content": msg["content"]})
        return out

    # ── 工具执行 ────────────────────────────────────────
    def _run_tool(self, call: dict, truncated: bool) -> ToolResult:
        tool = next((t for t in self.tools if t.name == call["name"]), None)
        if truncated:
            return ToolResult(f"工具 {call['name']} 没有执行：这次回复超出了输出上限，参数可能被截断。"
                              "请把内容拆小（例如每次少加几道题）后重新调用。", is_error=True)
        if tool is None:
            names = "、".join(t.name for t in self.tools)
            return ToolResult(f"没有工具 {call['name']}。可用的工具：{names}", is_error=True)
        try:
            args = json.loads(call["arguments"] or "{}")
        except ValueError:
            return ToolResult("参数不是有效的 JSON，请检查引号与转义后重新调用", is_error=True)
        problem = _schema_check(tool.parameters, args)
        if problem:
            return ToolResult(problem, is_error=True)
        call["args"] = args
        try:
            result = tool.execute(args, ToolContext(self, call))
        except Aborted:
            raise
        except ToolError as exc:
            return ToolResult(str(exc), is_error=True)
        except (ValueError, KeyError) as exc:
            return ToolResult(str(exc.args[0] if exc.args else exc), is_error=True)
        if not isinstance(result, ToolResult):
            result = ToolResult(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False))
        if len(result.content) > MAX_TOOL_CHARS:
            result.content = result.content[:MAX_TOOL_CHARS] + "\n…（结果太长已截断，请缩小范围再查）"
        return result

    # ── 主循环 ──────────────────────────────────────────
    def run(self, messages: list, prompts: list) -> list:
        """在 messages（会被原地追加）后面接上 prompts 跑一次；返回本次新增的消息。"""
        start = len(messages)
        for prompt in prompts:
            messages.append(dict(prompt, run=self.run_id))
        self.emit({"type": "agent_start"})
        schemas = [t.schema() for t in self.tools]
        stop_reason = "done"
        while True:
            self._check_abort()
            if self.turns >= self.max_turns:
                stop_reason = "max_turns"
                break
            self.turns += 1
            self.emit({"type": "turn_start", "turn": self.turns})
            self.emit({"type": "message_start", "turn": self.turns})
            started = time.time()
            reply = self.llm(self.to_llm(messages), schemas, self._on_delta)
            self._check_abort()
            calls = [dict(c) for c in reply.get("tool_calls") or []]
            message = {"role": "assistant", "content": (reply.get("content") or "").strip(), "tool_calls": calls}
            if reply.get("thinking"):
                message["thinking"] = reply["thinking"]
            messages.append(message)
            self.emit({"type": "message_end", "message": message, "seconds": round(time.time() - started, 1),
                       "finish_reason": reply.get("finish_reason", ""), "usage": reply.get("usage") or {},
                       "timing": reply.get("timing") or {}})
            if not calls:
                self.emit({"type": "turn_end", "turn": self.turns})
                if reply.get("finish_reason") == "length":
                    stop_reason = "length"
                    break
                queued = self._steer(messages)
                if queued:
                    continue
                break
            truncated = reply.get("finish_reason") == "length"
            images, results = [], []
            for call in calls:
                self._check_abort()
                self.tool_calls += 1
                tool = next((t for t in self.tools if t.name == call["name"]), None)
                try:
                    preview = json.loads(call["arguments"] or "{}")
                except ValueError:
                    preview = {}
                self.emit({"type": "tool_start", "id": call["id"], "name": call["name"], "index": calls.index(call),
                           "label": tool.label(preview) if tool else call["name"], "args": preview})
                result = self._run_tool(call, truncated)
                results.append(result)
                messages.append({"role": "tool", "tool_call_id": call["id"], "name": call["name"],
                                 "content": result.content})
                images += result.images
                self.emit({"type": "tool_end", "id": call["id"], "name": call["name"], "error": result.is_error,
                           "summary": result.details.get("summary") or result.content[:160],
                           "details": result.details, "content": result.content})
            if images:
                messages.append({"role": "user", "content": "（这是 view_pages 请求的页面。）", "images": images,
                                 "run": self.run_id, "synthetic": True})
            self.emit({"type": "turn_end", "turn": self.turns})
            if results and all(r.terminate for r in results):
                break
            self._steer(messages)
        self.emit({"type": "agent_end", "reason": stop_reason})
        return messages[start:]

    def _on_delta(self, kind, data):
        if self.aborted():
            raise Aborted()
        if kind == "toolcall":
            self.emit({"type": "toolcall_delta", "index": data.get("index", 0), "name": data.get("name", ""),
                       "delta": data.get("delta", "")})
        else:
            self.emit({"type": "delta", "kind": kind, "text": data})

    def _steer(self, messages: list) -> list:
        queued = (self.steering() if self.steering else None) or []
        for msg in queued:
            messages.append(dict(msg, run=self.run_id))
            self.emit({"type": "steer", "message": msg})
        return queued


def final_text(new_messages: list) -> str:
    """本次 run 最后一条非空的 assistant 文字。"""
    for msg in reversed(new_messages):
        if msg["role"] == "assistant" and (msg.get("content") or "").strip():
            return msg["content"].strip()
    return ""
