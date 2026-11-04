"""MCP server：server 名 reqmesh；stdio（默认）与 HTTP（streamable + 可选 SSE）双 transport。

- stdio：启动时以 whoami 校验持久化会话（失效则重登一次），失败仅告警不阻断
  （逐次调用仍有 401 重登兜底）；
- HTTP：stateless（每个请求作用域构建客户端会话，会话文件共享，
  无服务端长驻项目上下文——project context 属 P5 memory 范围）；
- host/port 经 REQMESH_HARNESS_HOST/REQMESH_HARNESS_PORT 配置（正式端口默认 127.0.0.1:8081；P6 收编，spec p6 决策②）。
- **可选鉴权**（见 mcp_auth）：设置 REQMESH_MCP_TOKEN 后要求
  `Authorization: Bearer <token>`；设置 REQMESH_MCP_PATH_TOKEN 后额外暴露
  `GET /mcp/<path-token>/sse`（给只能填服务地址、无自定义 header 的客户端，
  实测如通义灵码 / Qoder CN）。两者都未设置 = 不鉴权，保持本机开发与 stdio
  用法零变化。MCP 协议无认证层，且 READ 工具不受审批门保护——端点一旦
  暴露到本机之外就必须设置其中之一。
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


def _transport_security(settings: Settings):
    """按 `REQMESH_MCP_ALLOWED_HOSTS` 构造传输安全设置。

    未配置时返回 `None` → 完全沿用 MCP SDK 的默认（localhost 形态），本机用法零变化。

    为什么需要：SDK 的 DNS 重绑定保护在 host 为 localhost 时**硬编码**只放行
    `127.0.0.1:*` / `localhost:*` / `[::1]:*`。经反向代理或隧道暴露后，请求带的
    Host 是公网域名 → 被判定为 `Invalid Host header`，返回 **421**（实测：Cloudflare
    Tunnel 场景）。因此暴露时必须显式放行该域名。

    localhost 形态**始终保留**，避免放过公网域名后本机健康检查反而被拒。
    """
    raw = (settings.mcp_allowed_hosts or "").strip()
    if not raw:
        return None

    from mcp.server.transport_security import TransportSecuritySettings

    names = [item.strip() for item in raw.split(",") if item.strip()]
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    for name in names:
        hosts.append(name)
        hosts.append(f"{name}:*")  # 非 443 端口（如直连 :8082）也要放行
    origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    origins += [f"https://{name}" for name in names]

    logger.info("MCP Host 白名单已启用：%s", ", ".join(names))
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


def create_server(settings: Settings | None = None) -> FastMCP:
    """构建 FastMCP server（stateless HTTP：每个请求作用域一个会话）。"""
    settings = settings or get_settings()
    mcp = FastMCP(
        SERVER_NAME,
        host=settings.harness_host,
        port=settings.harness_port,
        stateless_http=True,
        transport_security=_transport_security(settings),
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


def _build_http_app(mcp: FastMCP, path_token: str):
    """组合 HTTP 端点：`/mcp`（streamable-HTTP）+ 可选 `/mcp/<path-token>/sse`（SSE）。

    SSE 端点为什么挂在 **token 子路径**下：通义灵码 / Qoder CN 的 SSE 配置只有
    "名称 + 服务地址"两个字段，**没有自定义 header**，凭据只能随路径传递
    （详见 mcp_auth 模块文档）。

    两个容易踩的坑（均已实测确认，改动时别退回去）：

    1. **`sse_app()` 不能传 `mount_path`**。`SseServerTransport` 自己会拼
       `scope["root_path"] + endpoint`（见 mcp/server/sse.py）；外层 `Mount` 已经把
       前缀写进 root_path，若再把同一个前缀传给 mount_path，宣告出来的 message 路径
       就会**重复一次**（实测：`/mcp/<t>/mcp/<t>/messages/`），客户端 POST 必然 404。

    2. **外层 Starlette 必须显式接管 streamable app 的 lifespan**。Starlette 的
       `Mount` 不向子 app 传播 lifespan，而 streamable 的 SessionManager 依赖 lifespan
       启动内部 task group；不接管就会在首个请求上抛
       `RuntimeError: Task group is not initialized. Make sure to use run()`。
    """
    streamable = mcp.streamable_http_app()

    if not path_token:
        return streamable

    from starlette.applications import Starlette
    from starlette.routing import Mount

    prefix = f"/mcp/{path_token}"
    sse = mcp.sse_app()  # 坑 1：不传 mount_path，前缀由外层 Mount 的 root_path 提供
    # 顺序要紧：先匹配更具体的 token 子路径，再落到 streamable 的根挂载
    return Starlette(
        routes=[Mount(prefix, app=sse), Mount("/", app=streamable)],
        lifespan=streamable.router.lifespan_context,  # 坑 2：接管 session manager 的启动
    )


def _run_http_with_auth(mcp: FastMCP, token: str, path_token: str = "") -> None:
    """HTTP transport + 鉴权：自行托管 uvicorn，以便在 ASGI app 外层包中间件。

    镜像 `FastMCP.run_streamable_http_async` 的 uvicorn 配置（host/port/log_level），
    只在 app 外层多包一层准入控制——不改变 MCP 协议行为。
    """
    import uvicorn

    from .mcp_auth import wrap_with_bearer_auth

    app = wrap_with_bearer_auth(_build_http_app(mcp, path_token), token, path_token)
    if token:
        logger.info("MCP 端点已启用 Bearer 鉴权（REQMESH_MCP_TOKEN 已设置）")
    if path_token:
        logger.info(
            "MCP 端点已启用 SSE（路径 token）：/mcp/<REQMESH_MCP_PATH_TOKEN>/sse"
        )
    config = uvicorn.Config(
        app,
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
    )
    uvicorn.Server(config).run()


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

    # 端点暴露到本机之外时用 REQMESH_MCP_TOKEN（Bearer 头）或
    # REQMESH_MCP_PATH_TOKEN（URL 路径，给只能填服务地址的客户端）开启鉴权。
    # 两者都未设置 = 不鉴权（默认关闭，见 mcp_auth）。
    token = settings.mcp_token.get_secret_value()
    path_token = settings.mcp_path_token.get_secret_value()
    if args.transport == "http" and (token or path_token):
        _run_http_with_auth(mcp, token, path_token)
        return

    mcp.run(transport=MCP_TRANSPORT[args.transport])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
