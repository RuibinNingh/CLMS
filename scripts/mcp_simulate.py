#!/usr/bin/env python3
"""A deterministic external evaluator using the real official MCP transport.

No model is invoked. The script checks image transport and proposes test feedback.
Secrets are accepted only from the environment and are never written as evidence.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def structured(result):
    if result.isError:
        raise RuntimeError('MCP tool error: ' + str(result.structuredContent or result.content))
    if result.structuredContent:
        return result.structuredContent
    for part in result.content:
        if part.type == 'text':
            return json.loads(part.text)
    raise RuntimeError('tool did not return a structured result')


async def main():
    origin = os.environ['CLMS_TEST_BASE_URL']
    secret = os.environ['CLMS_TEST_MCP_SECRET']
    async with httpx.AsyncClient(headers={'Authorization': 'Bearer ' + secret}, trust_env=False) as http:
        async with streamable_http_client(origin + '/mcp/', http_client=http) as (reader, writer, _):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                tools = await client.list_tools()
                assert not {'approve', 'review_approve', 'execute', 'sql'} & {t.name for t in tools.tools}
                kind = os.environ.get('CLMS_TEST_MCP_KIND', 'evaluation')
                if kind in ('upload', 'upload-pdf'):
                    path = Path(os.environ['CLMS_TEST_PDF' if kind == 'upload-pdf' else 'CLMS_TEST_IMAGE'])
                    result = await client.call_tool('upload_asset', {
                        'filename': path.name, 'content_base64': base64.b64encode(path.read_bytes()).decode()})
                    print(json.dumps(structured(result), ensure_ascii=False))
                    return
                supplied_payload = os.environ.get('CLMS_TEST_MCP_PAYLOAD')
                if supplied_payload:
                    tool = {'prompt': 'propose_prompt_change', 'category': 'propose_category_change',
                            'submission': 'propose_submission', 'revision': 'propose_revision',
                            'reflection': 'propose_reflection'}[kind]
                    proposal = await client.call_tool(tool, {'request_id': os.environ['CLMS_TEST_MCP_REQUEST_ID'],
                        'payload': json.loads(supplied_payload)})
                elif kind == 'category':
                    proposal = await client.call_tool('propose_category_change', {'request_id': 'browser-category-proposal',
                        'payload': {'action': 'create', 'name': 'MCP 模拟分类', 'language_scope': 'all'}})
                else:
                    version = structured(await client.call_tool('get_version', {'version_id': os.environ['CLMS_TEST_VERSION_ID']}))
                    page_ids = [p['page_id'] for p in version['manifest']]
                    for page_id in page_ids:
                        images = await client.call_tool('read_asset_pages', {'version_id': version['id'], 'page_ids': [page_id]})
                        assert not images.isError and any(p.type == 'image' and len(p.data) > 100 for p in images.content)
                    payload = {'schema_version': 1, 'version_id': version['id'], 'expected_manifest_hash': version['manifest_hash'],
                        'expected_prompt_snapshot_hash': version['prompt_snapshot_hash'],
                        'coverage': {'reviewed_page_ids': page_ids, 'scope': 'full', 'limitations': []},
                        'summary': '模拟外部评价：原稿图像已通过协议交付。', 'strengths': ['用于验证完整审核流程'],
                        'score': None, 'issues': [{'kind': 'improvement', 'dimension': '表达',
                          'location': {'page_id': page_ids[0], 'description': '第一页面中部', 'bbox': None},
                          'quote': None, 'reason': '这是确定性测试建议，不是模型识图判断。', 'suggestion': '核对后保留针对原稿的具体反馈。'}],
                        'next_actions': ['优先核对第一处反馈'], 'commentary_markdown': '<img src=x onerror=window.__xss=1>',
                        'declared_model': 'deterministic-simulation'}
                    proposal = await client.call_tool('propose_evaluation', {'request_id': 'browser-evaluation-' + version['id'], 'payload': payload})
                print(json.dumps(structured(proposal), ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
