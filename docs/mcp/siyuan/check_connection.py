#!/usr/bin/env python3
"""Check the configured SiYuan stdio transport without changing notes."""

import argparse
import json
import os
from pathlib import Path
import tomllib

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check(config_path, document_id):
    config = tomllib.loads(config_path.read_text())
    server = config['mcp_servers']['siyuan']
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
    parameters = StdioServerParameters(
        command=server['command'], args=server.get('args', []),
        env=env, cwd=server.get('cwd'),
    )
    with anyio.fail_after(45):
        async with stdio_client(parameters) as (read, write):
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
    parser.add_argument('--config', type=Path, default=Path.home() / '.codex/config.toml')
    parser.add_argument('--document-id', help='Optional document to verify with a read-only info call.')
    arguments = parser.parse_args()
    anyio.run(check, arguments.config, arguments.document_id)
