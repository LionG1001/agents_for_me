#!/usr/bin/env python3
"""Check configured SiYuan stdio or Streamable HTTP without changing notes."""

import argparse
from contextlib import asynccontextmanager
import json
import os
import sys
from pathlib import Path
import tomllib

import anyio
import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client


@asynccontextmanager
async def transport(server):
    if server.get('url'):
        headers = dict(server.get('http_headers', {}))
        for header, name in server.get('env_http_headers', {}).items():
            headers[header] = os.environ[name]
        async with httpx.AsyncClient(headers=headers, trust_env=False, follow_redirects=False,
                                     timeout=httpx.Timeout(30, read=45)) as client:
            async with streamable_http_client(server['url'], http_client=client) as (read, write, _):
                yield read, write
    else:
        env = dict(server.get('env', {}))
        for entry in server.get('env_vars', []):
            if isinstance(entry, str):
                name = entry
            elif entry.get('source', 'local') == 'local':
                name = entry['name']
            else:
                raise ValueError('This local check does not resolve remote environment variables.')
            if name in os.environ:
                env[name] = os.environ[name]
        parameters = StdioServerParameters(command=server['command'], args=server.get('args', []),
                                           env=env, cwd=server.get('cwd'))
        async with stdio_client(parameters) as streams:
            yield streams


async def check(config_path, document_id):
    config = tomllib.loads(config_path.read_text(encoding='utf-8-sig'))
    server = config['mcp_servers']['siyuan']
    with anyio.fail_after(45):
        async with transport(server) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                catalog = await session.list_tools()
                names = {tool.name for tool in catalog.tools}
                if not {'document', 'block', 'sql', 'system'} <= names:
                    raise RuntimeError('Expected SiYuan tools are missing.')

                async def query(tool, arguments):
                    result = await session.call_tool(tool, arguments)
                    if result.isError:
                        raise RuntimeError(f'Read-only {tool} call failed.')

                async with anyio.create_task_group() as tasks:
                    tasks.start_soon(query, 'system', {'action': 'version'})
                    tasks.start_soon(query, 'system', {'action': 'current_time'})
                if document_id:
                    await query('document', {'action': 'info', 'id': document_id})
                print(json.dumps({
                    'server': initialized.serverInfo.name,
                    'version': initialized.serverInfo.version,
                    'protocol': initialized.protocolVersion,
                    'tools': len(names),
                    'parallel_read_calls': 'passed',
                    'document_read': 'passed' if document_id else 'not requested',
                }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'config.toml')
    parser.add_argument('--document-id', help='Optional document to verify with a read-only info call.')
    arguments = parser.parse_args()
    try:
        anyio.run(check, arguments.config, arguments.document_id)
    except Exception as error:
        # Do not leak headers, URLs containing credentials, or upstream response bodies.
        print(f'SiYuan check failed ({type(error).__name__}).', file=sys.stderr)
        raise SystemExit(1)
