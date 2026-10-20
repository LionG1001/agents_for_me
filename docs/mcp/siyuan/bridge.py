#!/usr/bin/env python3
"""Forward local MCP stdio to the authenticated remote SiYuan MCP endpoint.

SiYuan 3.8.0 rejects non-loopback Host headers. Set that header only on the
outbound connection, and avoid HTTP proxies that route using the overridden
Host. MCP messages and tool schemas pass through without alteration.
"""

import logging
import os
import sys

import anyio
import httpx
from mcp.client.streamable_http import streamable_http_client
from mcp.server.stdio import stdio_server


async def forward(source, destination, cancel_scope):
    async for message in source:
        if isinstance(message, Exception):
            raise message
        await destination.send(message)
    cancel_scope.cancel()


async def main():
    authorization = os.environ.get('SIYUAN_MCP_AUTHORIZATION', '').strip()
    if not authorization:
        print('SiYuan MCP: SIYUAN_MCP_AUTHORIZATION is not set.', file=sys.stderr)
        return 1
    url = os.environ['SIYUAN_MCP_URL']
    headers = {'Authorization': authorization}
    host = os.environ.get('SIYUAN_MCP_HOST_HEADER', '').strip()
    if host:
        headers['Host'] = host
    async with httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(60, read=300),
        follow_redirects=False,
        trust_env=False,
    ) as client:
        async with stdio_server() as (local_read, local_write):
            try:
                async with streamable_http_client(
                    url, http_client=client, terminate_on_close=True
                ) as (remote_read, remote_write, _session_id):
                    async with anyio.create_task_group() as tasks:
                        tasks.start_soon(forward, local_read, remote_write, tasks.cancel_scope)
                        tasks.start_soon(forward, remote_read, local_write, tasks.cancel_scope)
            finally:
                await local_write.aclose()
    return 0


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    try:
        sys.exit(anyio.run(main))
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as error:
        # Never dump request headers, credentials, tool arguments or note content.
        print(f'SiYuan MCP transport failed ({type(error).__name__}).', file=sys.stderr)
        sys.exit(1)
