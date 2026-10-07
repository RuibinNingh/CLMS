"""Optional official SDK transport; catalog and domain authority stay shared with CLMS."""
import asyncio
import importlib.util
import json
import math
import os
import socket
import threading
import time
import urllib.parse
import uuid
from types import SimpleNamespace

from . import keys
from .authorization import install
from .http import MCPRequestGuard
from .. import runtime_history

_SERVICES = {}
_ERRORS = {"forbidden": "MCP 密钥已失效或没有此工具的权限", "unknown_tool": "没有开放此工具",
           "invalid_arguments": "参数不符合工具 schema", "invalid_request": "输入内容无法用于此操作",
           "not_found": "找不到请求的领域对象", "request_conflict": "同一 request_id 的内容不同",
           "content_conflict": "领域对象已经改变，请重新读取并提出操作", "revision_conflict": "版本已经改变",
           "state_conflict": "领域对象的当前状态不允许此操作", "expired": "操作已经到期",
           "internal_error": "CLMS 执行失败，请稍后重试"}


def _catalog(vault, actor=None):
    from ..tool_catalog import build_tools
    return {tool.name: tool for tool in build_tools(vault, source="mcp", actor=actor or {})}


def _required(tool):
    scopes = set(getattr(tool, "scopes", ()) or ())
    if not scopes or not scopes.issubset(keys.SCOPES) or getattr(tool, "permission", None) not in {"read", "auto", "confirm"}:
        raise ValueError("MCP 工具缺少服务端权限定义")
    return scopes


def _arguments(schema, args, permission):
    from jsonschema import Draft202012Validator
    if not isinstance(args, dict) or set(args) - set(schema.get("properties", {})):
        raise ValueError("invalid_arguments")
    types = Draft202012Validator.TYPE_CHECKER.redefine_many({
        "integer": lambda checker, value: type(value) is int,
        "number": lambda checker, value: type(value) in (int, float) and math.isfinite(value),
    })
    from jsonschema import validators
    Strict = validators.extend(Draft202012Validator, type_checker=types)
    if next(Strict(schema).iter_errors(args), None) is not None:
        raise ValueError("invalid_arguments")
    try:
        encoded = json.dumps(args, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise ValueError("invalid_arguments") from None
    if len(encoded) > 1_000_000:
        raise ValueError("invalid_arguments")
    if permission != "read":
        request_id = args.get("request_id")
        if (not isinstance(request_id, str) or not 1 <= len(request_id.strip()) <= 128
                or any(ord(ch) < 32 or ch in "?#/\\" for ch in request_id)):
            raise ValueError("invalid_arguments")


def _security(port, public_url):
    resource_url = f"http://127.0.0.1:{port}/mcp"
    hosts = [f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"]
    origins = [f"http://127.0.0.1:{port}", f"http://localhost:{port}"]
    if public_url:
        url = urllib.parse.urlsplit(public_url)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.path != "/mcp" or url.query or url.fragment):
            raise ValueError("MCP 公网地址必须是不带参数的 HTTPS /mcp 地址")
        resource_url = public_url; hosts.extend([url.netloc, url.hostname + ":443"])
        origins.append("https://" + url.netloc)
    return resource_url, hosts, origins


def build_server(vault, host="127.0.0.1", port=18473, public_url=None, web_url=None):
    if host != "127.0.0.1":
        raise ValueError("MCP 只允许监听 127.0.0.1")
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token
        from mcp.server.auth.provider import AccessToken
        from mcp.server.auth.settings import AuthSettings
        from mcp.server.fastmcp import FastMCP
        from mcp.server.transport_security import TransportSecuritySettings
        from mcp.types import Tool as SDKTool, ToolAnnotations, CallToolResult, TextContent, ImageContent
    except ImportError:
        raise ValueError("启用 MCP 前请安装 requirements-mcp.txt") from None
    install()
    resource_url, hosts, origins = _security(port, public_url)

    class TokenVerifier:
        async def verify_token(self, token):
            row = await asyncio.to_thread(keys.verify_key, vault, token)
            return AccessToken(token=token, client_id=row["key_id"], scopes=row["scopes"], subject=row["key_id"]) if row else None

    class RestrictedMCP(FastMCP):
        def current_key(self):
            token = get_access_token()
            row = keys.verify_key(vault, token.token) if token else None
            if not row:
                raise PermissionError("forbidden")
            return row

        async def list_tools(self):
            key = await asyncio.to_thread(self.current_key)
            tools = await asyncio.to_thread(_catalog, vault, {"kind": "mcp", "key_id": key["key_id"]})
            return [SDKTool(name=tool.name, description=tool.description, inputSchema=dict(tool.parameters, additionalProperties=False),
                           annotations=ToolAnnotations(readOnlyHint=tool.permission == "read", destructiveHint=False,
                                                       idempotentHint=True, openWorldHint=False),
                           _meta={"clms": {"permission": tool.permission, "scopes": sorted(_required(tool))}})
                    for tool in tools.values() if _required(tool).issubset(key["scopes"])]

        async def call_tool(self, name, arguments):
            call_id = None; result = None; code = "internal_error"; status = "failure"
            try:
                key = await asyncio.to_thread(self.current_key)
                actor = {"kind": "mcp", "key_id": key["key_id"], "call_id": "mcp_call_" + uuid.uuid4().hex}
                tools = await asyncio.to_thread(_catalog, vault, actor)
                tool = tools.get(name)
                if not tool:
                    code = "unknown_tool"; raise ValueError(code)
                required = _required(tool)
                if not required.issubset(key["scopes"]):
                    code = "forbidden"; raise PermissionError(code)
                call_id = await asyncio.to_thread(runtime_history.safely, runtime_history.begin, vault, "mcp", name, arguments, actor)
                await asyncio.to_thread(_arguments, tool.parameters, arguments, tool.permission)

                def execute():
                    def check():
                        live = self.current_key()
                        if not required.issubset(live["scopes"]):
                            raise PermissionError("forbidden")
                        return live
                    check()
                    context = SimpleNamespace(authorize=check, actor=actor, aborted=False, update=lambda details: None)
                    out = tool.execute(arguments, context)
                    check()
                    return out

                result = await asyncio.to_thread(execute)
                if tool.permission != "read" and isinstance(result, dict) and result.get("status") in {"failed", "conflict", "expired", "interrupted"}:
                    rejected_code = result.get("error_code") or "invalid_request"
                    code = rejected_code if rejected_code in _ERRORS else "invalid_request"
                    status = result["status"] if result["status"] in {"conflict", "expired", "interrupted"} else "failure"
                    return CallToolResult(isError=True, content=[TextContent(type="text", text=f"{code}: {_ERRORS[code]}")],
                                          structuredContent={"operation_id": result.get("id"), "status": result["status"], "error_code": code})
                code = ""; status = "pending_confirmation" if isinstance(result, dict) and result.get("status") == "pending_confirmation" else "success"
                if name == "get_essay_image":
                    return CallToolResult(content=[ImageContent(type="image", data=result["data"], mimeType=result["mime_type"])])
                return result
            except asyncio.CancelledError:
                status = "interrupted"; code = "interrupted"; raise
            except Exception as error:
                candidate = getattr(error, "code", str(error) if isinstance(error, (ValueError, PermissionError)) else "")
                code = "forbidden" if isinstance(error, PermissionError) else candidate if candidate in _ERRORS else "invalid_request" if isinstance(error, (ValueError, KeyError, TypeError)) else "internal_error"
                return CallToolResult(isError=True, content=[TextContent(type="text", text=f"{code}: {_ERRORS[code]}")])
            finally:
                if call_id:
                    await asyncio.shield(asyncio.to_thread(runtime_history.safely, runtime_history.finish, vault, call_id,
                                                           result, code, status))

    return RestrictedMCP("CLMS", instructions="按授权查询语文学习与作文，使用正式转写讨论作文并保存60分评价、修改笔记与自由分类。"
                         "正式复习与题目/材料修改先提交统一审核，等待网页人工批准；禁止自行批准。每个写请求须稳定request_id，重试复用结果。"
                         "只在用户明确要求保存时追加评价或笔记，不保存整段聊天记录。原图只通过get_essay_image按权限读取。",
                         token_verifier=TokenVerifier(), auth=AuthSettings(issuer_url="https://clms.invalid", resource_server_url=resource_url),
                         transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins),
                         host=host, port=port, streamable_http_path="/mcp", json_response=True, stateless_http=True, log_level="WARNING")


def build_app(vault, host="127.0.0.1", port=18473, public_url=None, web_url=None):
    return MCPRequestGuard(build_server(vault, host, port, public_url, web_url).streamable_http_app(), vault)


class MCPService:
    def __init__(self, server, thread, port):
        self.server, self.thread, self.port = server, thread, port
        self.url = f"http://127.0.0.1:{port}/mcp"

    @property
    def running(self):
        return self.thread.is_alive() and self.server.started and not self.server.should_exit

    def stop(self):
        self.server.should_exit = True; self.thread.join(timeout=5)


def start_background(vault, port=18473, public_url=None, web_url=None):
    try:
        import uvicorn
    except ImportError:
        raise ValueError("启用 MCP 前请安装 requirements-mcp.txt") from None
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("MCP 端口不合法")
    sock = socket.socket(); sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", port)); selected = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(build_app(vault, port=selected, public_url=public_url, web_url=web_url),
                                host="127.0.0.1", port=selected, log_level="error", access_log=False))
        thread = threading.Thread(target=lambda: server.run(sockets=[sock]), name="clms-mcp", daemon=True)
        thread.start(); deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.02)
        if not server.started:
            server.should_exit = True; thread.join(timeout=2)
            raise ValueError("MCP 服务启动失败")
        service = MCPService(server, thread, selected); _SERVICES[os.path.abspath(vault)] = service
        return service
    except BaseException:
        sock.close(); raise


def status(vault):
    service = _SERVICES.get(os.path.abspath(vault))
    return {"enabled": bool(service), "running": bool(service and service.running),
            "url": service.url if service else None, "sdk_installed": importlib.util.find_spec("mcp") is not None}
