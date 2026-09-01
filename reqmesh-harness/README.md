# reqmesh-harness

reqmesh 需求管理工具的 Agentic 编排运行时（见 `docs/reqmesh-harness-design.md`；P1 范围见 `docs/specs/p1-tool-layer-mvp.md`）。
本目录实现 P1 工具层 MVP：认证客户端 + 25 个 READ 工具 + MCP 双 transport（stdio / streamable-HTTP）+ OpenAI function JSON 导出。

## 目录与管线职责

| 路径 | 职责 |
|---|---|
| `openapi/reqmesh-0.5.0.json` | vendored /openapi.json 快照（契约输入，勿手改；升级时重新抓取） |
| `scripts/gen_models.py` | 确定性模型生成管线：快照 → `client/generated/models.py` |
| `src/reqmesh_harness/client/` | 薄 HTTP 客户端：认证会话（cookie/CSRF）、只读视图（仅 `get()`） |
| `src/reqmesh_harness/client/generated/` | 生成产物（提交入库，**禁止手改**） |
| `src/reqmesh_harness/tools/` | 工具注册表（唯一事实源）+ 25 个 READ 工具 |
| `src/reqmesh_harness/server.py` | FastMCP server（stdio + streamable-HTTP） |
| `scripts/smoke_p1.py` | cessna-172 冒烟（network-tagged，不进默认 pytest 集合） |
| `tests/` | 离线单测（respx 打桩 + fixture），见 spec「Testing Decisions」 |

## 常用命令

```bash
uv sync                       # 安装依赖（uv.lock 锁定）
uv run python scripts/gen_models.py   # 重生成模型（重跑后 git diff 应为空）
uv run pytest                 # 全部离线单测
uv run pytest -m network      # 网络冒烟（需 REQMESH_USERNAME/REQMESH_PASSWORD）
uv run python -m reqmesh_harness.server                       # stdio transport
uv run python -m reqmesh_harness.server --transport http      # streamable-HTTP transport
# （可加 --host/--port 覆盖监听地址/端口；默认见 REQMESH_HARNESS_HOST/PORT）
```

## 认证

凭据仅经环境变量注入：`REQMESH_USERNAME` / `REQMESH_PASSWORD`（或 Bearer 兜底 `REQMESH_TOKEN`）。
会话（cookie + csrf_token）持久化到 XDG state 目录（`~/.local/state/reqmesh-harness/session.json`，0600），重启免重登。
