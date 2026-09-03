"""MCP server：server 名 reqmesh；stdio（默认）与 streamable-HTTP 双 transport。

- stdio：启动时以 whoami 校验持久化会话（失效则重登一次），失败仅告警不阻断
  （逐次调用仍有 401 重登兜底）；
- streamable-HTTP：stateless（每个请求作用域构建客户端会话，会话文件共享，
  无服务端长驻项目上下文——project context 属 P5 memory 范围）；
- host/port 经 REQMESH_HARNESS_HOST/REQMESH_HARNESS_PORT 配置（正式端口默认 127.0.0.1:8081；P6 收编，spec p6 决策②）。
"""

from __future__ import annotations

import argparse
import logging

from mcp.server.fastmcp import FastMCP

from .config import Settings, get_settings
from .tools import build_registry
from .tools.runtime import Runtime, get_runtime, set_runtime

logger = logging.getLogger("reqmesh_harness.server")

SERVER_NAME = "reqmesh"

# CLI 参数值 → FastMCP.transport 取值（"http" 是用户友好的别名）
MCP_TRANSPORT = {"stdio": "stdio", "http": "streamable-http"}


def create_server(settings: Settings | None = None) -> FastMCP:
    """构建 FastMCP server（stateless HTTP：每个请求作用域一个会话）。"""
    settings = settings or get_settings()
    mcp = FastMCP(
        SERVER_NAME,
        host=settings.harness_host,
        port=settings.harness_port,
        stateless_http=True,
    )
    build_registry().install(mcp)
    return mcp


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="reqmesh-harness", description="reqmesh MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="transports: stdio（默认）| http（streamable-HTTP）",
    )
    parser.add_argument("--host", default=None, help="HTTP transport 监听地址")
    parser.add_argument("--port", type=int, default=None, help="HTTP transport 端口")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    settings = get_settings()
    if args.host is not None:
        settings = settings.model_copy(update={"harness_host": args.host})
    if args.port is not None:
        settings = settings.model_copy(update={"harness_port": args.port})

    set_runtime(Runtime(settings))
    if args.transport == "stdio":
        # 启动校验：加载持久化会话并以 whoami 校验（失效则重新登录）；失败不阻断启动
        try:
            get_runtime().validate()
            logger.info("启动会话校验通过（whoami）")
        except Exception as exc:  # noqa: BLE001 - 启动健壮性：调用期仍有 401 重登兜底
            logger.warning("启动会话校验失败（将按需求逐次重试）: %s", exc)

    mcp = create_server(settings)
    mcp.run(transport=MCP_TRANSPORT[args.transport])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
