#!/usr/bin/env python3
"""Deterministic external-client simulation: deliver images, then save pending proposals.

This never calls an AI model or approves an operation. Credentials are read only
from CLMS_MCP_TOKEN and are never printed or put into a URL.
"""
import argparse
import asyncio
import base64
import hashlib
import json
import os
import sys
import uuid
from io import BytesIO
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from PIL import Image


class SimulationError(Exception):
    pass


def structured(result):
    if result.isError:
        error = (result.structuredContent or {}).get("error")
        if error:
            raise SimulationError(f"{error.get('code')}: {error.get('message')}")
        raise SimulationError("MCP 工具拒绝请求：" + str(getattr(result.content[0], "text", ""))[:500])
    return result.structuredContent or json.loads(result.content[0].text)


def decode_delivered_pages(result, expected_ids):
    metadata = structured(result)
    mappings = metadata.get("pages", [])
    images = [block for block in result.content if block.type == "image"]
    if len(images) != len(expected_ids) or {p["page_id"] for p in mappings} != set(expected_ids):
        raise SimulationError("图像数量或页映射与请求不一致")
    verified = []
    for mapping, image_content in zip(mappings, images, strict=True):
        if image_content.mimeType != "image/jpeg":
            raise SimulationError("返回图像格式与约定不符")
        data = base64.b64decode(image_content.data, validate=True)
        with Image.open(BytesIO(data)) as image:
            image.load()
            if image.size != (mapping["image_width"], mapping["image_height"]):
                raise SimulationError("实际图像尺寸与映射不符")
            if min(image.size) < 1:
                raise SimulationError("返回图像为空")
        verified.append({"page_id": mapping["page_id"], "asset_id": mapping["asset_id"],
                         "source_page": mapping["source_page"], "order": mapping["order"],
                         "rotation": mapping["rotation"], "image_width": mapping["image_width"],
                         "image_height": mapping["image_height"],
                         "delivered_sha256": hashlib.sha256(data).hexdigest()})
    return verified


async def simulate(arguments, token):
    parsed_url = urlsplit(arguments.endpoint)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc or parsed_url.username or parsed_url.password:
        raise SimulationError("endpoint须为不含凭据的HTTP(S) MCP地址")
    if parsed_url.query or parsed_url.fragment:
        raise SimulationError("endpoint不能包含查询参数或片段")
    endpoint = arguments.endpoint.rstrip("/") + "/"
    async with httpx.AsyncClient(headers={"Authorization": "Bearer " + token}, timeout=60) as http:
        async with streamable_http_client(endpoint, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as client:
                initialized = await client.initialize()
                tools = await client.list_tools()
                expected = {"get_version", "get_attempt", "read_asset_pages", "propose_evaluation"}
                if not expected <= {tool.name for tool in tools.tools}:
                    raise SimulationError("目标服务缺少模拟所需工具")
                capabilities = structured(await client.call_tool("get_capabilities", {}))
                version = structured(await client.call_tool("get_version", {"version_id": arguments.version_id}))
                attempt = structured(await client.call_tool("get_attempt", {"attempt_id": version["attempt_id"]}))
                if attempt["snapshot_hash"] != version["prompt_snapshot_hash"]:
                    raise SimulationError("题目快照哈希不一致")
                batch_size = min(2, capabilities["limits"]["mcp_max_pages"])
                if batch_size < 1:
                    raise SimulationError("服务器没有可用的读图页限额")
                pages = version["manifest"]
                manuscript_delivery = []
                for offset in range(0, len(pages), batch_size):
                    requested = [p["page_id"] for p in pages[offset:offset + batch_size]]
                    response = await client.call_tool("read_asset_pages", {
                        "version_id": version["id"], "page_ids": requested, "quality": "normal"})
                    mappings = structured(response)["pages"]
                    if any(m["version_id"] != version["id"] or m["manifest_hash"] != version["manifest_hash"]
                           or m["prompt_snapshot_hash"] != version["prompt_snapshot_hash"] for m in mappings):
                        raise SimulationError("稿件页映射的身份/哈希不一致")
                    manuscript_delivery.extend(decode_delivered_pages(response, requested))
                material_delivery = []
                for material in attempt["prompt_snapshot"].get("materials", []):
                    requested = [material["page_id"]]
                    response = await client.call_tool("read_asset_pages", {"asset_id": material["asset_id"],
                        "page_ids": requested, "rotation": material["rotation"], "quality": "normal"})
                    material_delivery.extend(decode_delivered_pages(response, requested))
                payload = {"schema_version": 1, "version_id": version["id"],
                    "expected_manifest_hash": version["manifest_hash"],
                    "expected_prompt_snapshot_hash": version["prompt_snapshot_hash"],
                    "coverage": {"scope": "full", "reviewed_page_ids": [p["page_id"] for p in pages],
                        "limitations": ["自动化模拟仅验证图片交付、解码和审核协议；未使用AI模型理解作文内容。"]},
                    "summary": "【脚本模拟】已校验原稿页面交付与映射；这不是AI作文批改。",
                    "strengths": [], "score": None, "issues": [],
                    "next_actions": ["人工核对原稿；如需真实评价，请交由实际外部AI阅读后另提交提案。"],
                    "commentary_markdown": "此提案用于联调审核链路，不包含对作文质量的判断。",
                    "declared_model": "deterministic-client-simulation (no AI model)"}
                receipt = structured(await client.call_tool("propose_evaluation", {
                    "payload": payload, "request_id": arguments.request_id or "simulation-" + uuid.uuid4().hex}))
                if receipt["status"] != "pending" or not receipt["requires_human_review"]:
                    raise SimulationError("模拟提案应为等待网页人工审核")
                category_receipt = None
                if arguments.category:
                    category_receipt = structured(await client.call_tool("propose_category_change", {
                        "request_id": "simulation-category-" + uuid.uuid4().hex,
                        "payload": {"action": "create", "name": arguments.category,
                            "language_scope": arguments.category_language,
                            "description": "由官方SDK脚本模拟提交，等待网页人工审核。"}}))
                operation_id = receipt.get("operation_id", receipt.get("id"))
                print(json.dumps({"simulation": True, "ai_model_used": False, "approval_performed": False,
                    "server": initialized.serverInfo.name, "version_id": version["id"],
                    "prompt_snapshot_hash": version["prompt_snapshot_hash"],
                    "manuscript_delivery": manuscript_delivery, "material_delivery": material_delivery,
                    "evaluation_receipt": receipt, "category_receipt": category_receipt,
                    "review_url": f"{parsed_url.scheme}://{parsed_url.netloc}" + receipt.get("review_path", f"/#/reviews?id={operation_id}")},
                    ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="通过官方MCP SDK真实读图并提交明确标注模拟的待审评价；不调用模型、不批准。")
    parser.add_argument("--endpoint", required=True, help="例如 http://127.0.0.1:18474/mcp/")
    parser.add_argument("--version-id", required=True, help="已入档的精确稿件版本ID")
    parser.add_argument("--request-id", help="可复用以验证幂等的请求ID")
    parser.add_argument("--category", help="可选：同时提交此自定义分类的创建提案")
    parser.add_argument("--category-language", choices=("zh", "en", "all"), default="all")
    arguments = parser.parse_args()
    token = os.environ.get("CLMS_MCP_TOKEN", "").strip()
    if not token:
        parser.error("请在环境变量CLMS_MCP_TOKEN中提供MCP凭据，不要放到命令行或URL里")
    try:
        asyncio.run(simulate(arguments, token))
    except (SimulationError, httpx.HTTPError, ValueError, ExceptionGroup) as error:
        # ExceptionGroup's repr may contain nested transport implementation details.
        print(f"模拟失败：{type(error).__name__}；" + (str(error)[:500] if not isinstance(error, ExceptionGroup)
              else "MCP传输被拒绝或中断，请检查endpoint、凭据和scope。"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
