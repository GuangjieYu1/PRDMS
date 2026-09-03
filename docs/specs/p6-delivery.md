# P6 spec：交付收尾（evals + 部署 + 文档/版本）

> 状态：需求会话产出，待开发会话实施。
> 入口：design [docs/reqmesh-harness-design.md](../reqmesh-harness-design.md)（§3 D5/D6/D7/D10、§4 P6 行、§5 流程、§6 P6 预置开放问题、§7 验证基线） · epic [#6](https://github.com/GuangjieYu1/PRDMS/issues/6) · 术语 [CONTEXT.md](../../CONTEXT.md) · 协议 [ADR-0001](../adr/0001-mcp-core-tool-protocol.md) · 命名 [ADR-0002](../adr/0002-tool-naming-and-grouping.md) · P1–P5 specs（[p1](p1-tool-layer-mvp.md)/[p2](p2-write-path.md)/[p3](p3-nl-requirements.md)/[p4](p4-traceability-report.md)/[p5](p5-runtime.md)）
> 交接：见 [docs/handoffs/p6-delivery.md](../handoffs/p6-delivery.md)

## Problem Statement

P1–P5 交付了 40 个工具（27 READ + 7 DRAFT + 6 MUTATE）、四级审批门、审计、双 transport MCP server 与内置运行时（533 离线用例全绿、P1–P5 冒烟记录齐备）。P6 是 design §4 的收尾 phase：把累积资产转成**可验收、可部署、可发布的交付物**三件套——① 黄金任务集 evals（可断言工具序列与最终库状态，给「旗舰能力没有退化」一个可重复执行的验收面）；② 部署形态（172.16.100.2 暴露方式、端口、systemd、DSH 宿主 mcp-reqmesh 注册）；③ 文档与打包（README、部署/发布说明、版本 0.1.0→0.2.0）。

P6 同时必须承接两项 **P5 遗留**（已冻结在 spec/handoff/冒烟记录，属 P6 部署输入）：① DSH 宿主注册 mcp-reqmesh（cordis.patch.yml 需 insert dsh-mcp-client 条目——P5 硬约束未动运行中 DSH；本 phase 产出步骤文档与幂等脚本，**实际应用时机与责任人由本 spec 界定**）；② B 段冒烟重跑（前置应用后以 `REQMESH_P5_SMOKE_B=1` 重跑 `scripts/smoke_p5.py` 执行 SMOKE-P5-001，残渣约定 total 61→62；P4 记录的 61 仅作历史快照）。

design §6 的 P6 预置开放问题（部署端口与是否独立 systemd 单元、eval 集形态）连同本会话自拟的 DSH transport 选型、版本方案、文档清单、验收口径，一并在本 spec「Implementation Decisions」①–⑥ 落定。

## 事实核实（本会话，证据留档，不拍脑袋）

### 部署环境（本机 172.16.100.2，2026-09-03 实测）

1. **端口占用**（`ss -tlnp`）：`0.0.0.0:3080` node（`dsh web --no-open`）、`0.0.0.0:8080` node（`dsh --profile web --no-open --port 8080`，即本工作 GUI 所在宿主）、`0.0.0.0:8000` python uvicorn（reqmesh，**由 DSH 进程 19838 派生**）；8081/9001/5173 无 LISTEN（空闲）。
2. **systemd 现实**：`/usr/bin/systemctl` 存在，但 `systemctl --user` 报 `Failed to connect to bus: No medium found`——**本机无用户级 systemd**；`/etc/systemd/system/` 无任何自定义 `*.service`（只有 target 默认件）；当前 uid=1000，root 级单元安装需 sudo。现网三个服务全是裸进程（ppid=1）。
3. **DSH web profile 现状**：`/home/user/.dsh/profiles/web/cordis.patch.yml` 仅 1 条（webserver：host 0.0.0.0、port `!!js ctx.webStartup.port ?? 3080`）——**无 mcp 条目**（P5 事实 8 复核成立）。
4. **dsh-mcp-client 配置 schema**（DSH checkout `node_modules/@deepseek-ai/dsh-mcp-client/lib/index.js`，本会话复核）：
   - stdio：`{transport:"stdio", serverName（必填，`/^[A-Za-z0-9_-]{1,32}$/`）, command（必填）, args[] 默认空, env{} 默认空, cwd 默认空, toolCallTimeoutMs 默认 60000, failOnStartupError 默认 false, reconnect{enabled 默认开}}`；
   - streamable-http：`{transport:"streamable-http", serverName, url（必填）, headers{} 默认空, 同上可选}`。
   - 工具注册名 `mcp__<serverName>__<rawName>`；重复 serverName 是加载错误；HMR 热替换会 dispose 旧实例重建（同 serverName 复现同工具名）。
   - harness stdio 入口 console script 存在：`reqmesh-harness/.venv/bin/reqmesh-harness`（可执行）。

### harness 打包与监听现状（源码复核 + 实测）

5. **uv build 产物形态**（本会话实测）：`cd reqmesh-harness && uv build` → `dist/reqmesh_harness-0.1.0.tar.gz`（sdist）+ `dist/reqmesh_harness-0.1.0-py3-none-any.whl`；build-backend=hatchling；`dist/` 被根 `.gitignore`（`dist/` 模式）忽略——**构建产物不入库**。
6. **streamable-HTTP 监听参数**（`server.py`/`config.py`）：`REQMESH_HARNESS_HOST`/`REQMESH_HARNESS_PORT`（代码默认 `127.0.0.1:8123`），CLI `--host/--port` 覆盖；FastMCP `stateless_http=True`，端点路径 `/mcp`。P1 spec 配置节原文：默认 `127.0.0.1:8123`；**「正式部署端口是 P6 开放问题」**——8123 是 P1 期临时开发默认，P6 落定正式端口（决策 ②）。测试对 8123 的引用仅 `tests/test_skeleton.py:20` 一处断言（P6 变更白名单，见验收 12）。
7. **冒烟 network-tagged 惯例**（P1–P5 实测）：`scripts/smoke_p*.py` 是**独立脚本**（docstring 注明 network-tagged，不进默认 pytest 集合——pytest `addopts="-m 'not network'"`）；P1/P2 另有 pytest 包装（`tests/test_smoke.py`/`test_smoke_p2.py`，`@pytest.mark.network`），P3–P5 只有裸脚本；记录经 `REQMESH_SMOKE_OUT` 落盘 `docs/smoke/P*-cessna-172.md`（时间戳、实例、每步结果、关键计数、残渣清单）。evals live 对齐此惯例（决策 ①）。
8. **测试基线**（本会话复跑收集）：默认集合收集 536/538（2 deselected）= P5 记录口径 533 passed / 3 skipped / 2 deselected。
9. **uv.lock 漂移（P5 遗留，本会话实测）**：HEAD 的 `reqmesh-harness/uv.lock` 缺 `websockets`（P5 提交改 pyproject 未同步 lock）；工作树 lock 已由环境 `uv sync` 补齐且 `uv lock --check` 通过——**P6 打包范围含 lock 同步提交**（否则新会话 `uv sync` 会重写 lock，污染工作树）。
10. **上游 Host 允许清单边界**（reqmesh 只读调查）：`RT_ALLOWED_HOSTS` 是 reqmesh 上游自己的 Host-header 校验（代码默认 `["*"]` 关闭校验；Docker 默认收窄 loopback）——属上游部署面；harness 侧无等价设置，暴露面只由绑定地址决定（决策 ②）。
11. **gh 可用性**：`gh auth status` = GuangjieYu1（repo/project scope 齐备）；epic #6 OPEN（无评论）；全库 open issue 仅 #6；ticket 编号自 #45 起。

### P5 遗留事实（承接复核）

12. **B 段冒烟门控**（`smoke_p5.py` 头部复核）：B 段（SMOKE-P5-001）以 `REQMESH_P5_SMOKE_B=1` 显式启用；前置 = web profile 已注册 mcp__reqmesh__* 40 工具；断言含 total 61→62、审计**基线差 Δ2 行**（共享 XDG 文件口径，P5 实测偏差 3）、无 approval/requested 帧。P5 冒烟记录现状：A 段通过、B 段「待前置后执行」。
13. **P5 spec「DSH 部署步骤」**（P6 输入）：stdio 条目（serverName=reqmesh、command=venv console script、args `--transport stdio`、cwd=`reqmesh-harness/` 使 `.env` 生效、env 转发 `REQMESH_USERNAME/PASSWORD`）→ 重启 web 宿主（HMR 是否拾取 patch 未验证）→ 验证 40 工具可见。P6 按此落定并补责任边界与验证步骤（决策 ③）。

## Solution

不新增任何 reqmesh 工具、不改任何护栏裁决语义。P6 交付四块（对应 tickets #45–#51）：

1. **evals 黄金任务集**（`reqmesh-harness/evals/` 新目录，#45/#46）：5 个黄金任务（G1–G5，覆盖 P2–P5 旗舰能力 + 审批拒绝路径 + P5 run 任务），任务定义 = 数据（工具序列 + 参数匹配器 + 最终状态断言 + 审计期望）；离线 runner（FakeProvider 工具循环 + respx，零网络）与 live runner（DSH 委托路线，network-tagged）共享同一任务定义。
2. **部署形态**（#47/#48）：正式端口 8081（代码默认收编）；免 root 启动脚本 `scripts/run_server.sh`（本机唯一可执行路径——无用户级 systemd）；root 级 systemd 单元模板 `deploy/systemd/reqmesh-harness.service`（可装 systemd 的主机用，sudo 安装步骤属操作员责任边界）；LAN 暴露安全口径写入部署文档。
3. **DSH 集成部署**（#49）：mcp-reqmesh 注册走 **stdio**（决策 ③）；幂等插入脚本 `scripts/dsh_register.sh`（只产出，不执行）；执行责任人 = 操作员（本机用户/方向层），维护窗口执行；验证 = B 段冒烟 + evals live。
4. **文档与打包**（#50/#51）：版本 0.1.0→0.2.0、CHANGELOG/RELEASING、uv build 产物约定、根 README 新建 + harness README 扩充、部署文档 `docs/deployment.md`。

## User Stories

1. As an evaluator, I want a golden task set with offline and live runners that assert tool call sequences and final library state per flagship capability, so that capability regressions are caught by one repeatable command.
2. As an operator, I want a documented, reproducible deployment on 172.16.100.2 (port 8081, no-root startup script + systemd unit template), so that the streamable-HTTP server runs the same way on this box and on systemd hosts.
3. As the DSH host owner, I want a reviewed, idempotent registration procedure for mcp-reqmesh (stdio) with a defined responsible party and verification steps, so that enabling `mcp__reqmesh__*` tools is a deliberate maintenance-window action, not an ad-hoc edit.
4. As a developer, I want version 0.2.0 with a CHANGELOG, a RELEASING doc and a reproducible `uv build`, so that a release is a documented, auditable artifact.
5. As a newcomer, I want repo-root and package READMEs plus docs/deployment.md that get me from clone to a working server and a green test run without tribal knowledge.
6. As the direction layer, I want P6 acceptance criteria that are each testable on this box, so that the final epic close is evidence-based.

## Implementation Decisions

### 开放问题①：eval 集形态与范围（已决策）

**决策：独立 `reqmesh-harness/evals/` 目录 + 自有 runner 脚本，不并入 pytest；5 个黄金任务 G1–G5；断言形式 = 离线单测式 + network-tagged live 脚本双层。**

- **目录与文件**：`evals/tasks.py`（GoldenTask 定义：id、capability、FakeProvider 脚本步骤、期望工具序列 `ExpectedCall(name, arg_matchers)`、最终状态断言（离线 = 写负载形状 + 审计行 + 读回 stub 响应；live = 真实 GET 回读）、审计期望）；`evals/run_offline.py`（离线 runner，零网络）；`evals/run_live.py`（network-tagged，DSH 委托路线）。
- **不并入 pytest 的理由**：① evals 断言端到端行为（工具序列 + 最终状态），与 533 个单测（单元行为）语义不同；并入会让「离线基线」随 eval 增改漂移，破坏 P1–P5 的「基线不回退」验收口径；② evals 是验收资产，任务定义数据化后要长期稳定（未来 phase 改工具行为时先跑 evals 看退化），独立 runner 使「evals 全绿」成为单一命令的发布门；③ live 侧沿用 P3–P5 冒烟惯例（独立 network-tagged 脚本 + `docs/smoke/` 记录），pytest 只保留 P1/P2 的既有冒烟包装，不为 evals 新加。
- **5 个黄金任务（≥1 每旗舰能力 + 审批拒绝路径 + P5 run 任务）**：

| 任务 | 能力 | 工具序列（期望） | 最终状态断言 | 离线 | live |
|---|---|---|---|---|---|
| G1 NL 建需求 | P3 旗舰① | `draft_requirement` → `get_requirement_quality` → `get_requirement` | 落库实体 description 与 EARS 文本相等、status=proposed、quality score≥lint 线；审计 1 行 approved | respx | ✓（id `SMOKE-EVAL-P6-G1`，残渣） |
| G2 追踪/覆盖缺口报告 | P4 旗舰② | `get_traceability_gap_report`（单步） | 报告结构：summary/gaps 非空、已知基线缺口点检（SMOKE-P2-001 / AFRM0000 口径沿用 P4 golden） | respx + report_golden.json 复用 | ✓（全 READ，零副作用零残渣） |
| G3 追踪维护 | P2 追踪域 | `get_traces` → `set_relations`（MUTATE，经审批）→ `get_traces` | 新链接回读可见、旧链接保留；审计 approved 1 行 | respx | ✓（link id 前缀 `SMOKE-EVAL-P6-G3`，残渣） |
| G4 审批拒绝路径 | P2 审批门 | `create_requirement`（空白名单）→ 断言拒绝 | 工具错误文本含 `ApprovalDeniedError` + `fix_hint`（`approvals add` 命令）；审计 denied 1 行；**库状态零变化**（回读 total 不变）；白名单文件未被修改 | respx + 临时白名单文件 | ✓（denied 落库零行，无残渣；审计行数用基线差口径） |
| G5 P5 run 任务 | P5 内置运行时 | run（tool-loop）：`get_traceability_gap_report` → `review_item`（denied→确认中继→approved 重试） | 工具调用序列与 FakeProvider 脚本一致；审计 denied+approved 双行；run 事件日志 kind 顺序（task→tool_call→tool_result→question→…→done） | respx + FakeProvider | ✗（P5 live 已由 smoke_p5 B 段覆盖，不重复） |

- **与既有 533 测试的关系**：evals 复用同一 registry/gate/audit/FakeProvider/run_task 机制，**零复制裁决逻辑**；evals 目录不进 pytest testpaths；533 基线、P1–P5 冒烟记录均不回退。evals 自身新增的离线用例落在 evals/ 内（runner 退出码即全绿判定），不改变 pytest 计数。
- **live 前置**：G1–G4 live 与 smoke_p5 B 段同前置（DSH web profile 已注册 mcp__reqmesh__*，决策 ③）；前置未满足时 live runner 与 B 段同口径记录「待前置后执行」。

### 开放问题②：部署形态（已决策）

**决策：正式端口 8081（代码默认收编，替换 P1 期 8123）；绑定默认 127.0.0.1，LAN 暴露显式开启；systemd 用「root 级单元模板 + sudo 安装步骤文档（操作员责任）」+「免 root 启动脚本（本机默认路径）」双轨。**

- **端口 8081（8081/9001 候选落定）**：理由：① 与 DSH web（8080）同属「本机 agentic 工具带」，紧邻便于心智定位（9001 无邻接语义）；② 本会话实测空闲且不撞 8000（reqmesh 数据层）/8080（DSH 宿主）/3080（webserver 插件）；③ 8123 仅剩 P1 期开发默认语义（P1 spec 明言「正式部署端口是 P6 开放问题」），P6 收编为 8081 消除双默认。**变更白名单**：`config.py` 默认值、`server.py` docstring、`tests/test_skeleton.py:20` 断言、README 端口行——工具/护栏/客户端零 diff。
- **systemd 双轨（本机现实：无用户级 systemd，uid=1000，root 单元需 sudo）**：
  1. **免 root 启动脚本 `scripts/run_server.sh`（本机默认路径，本 phase 可实测验证）**：`start|stop|status|logs` 子命令，nohup + pidfile（XDG state `reqmesh-harness/server.pid`）+ stdout/stderr 日志文件（XDG state）；环境经 shell 环境/`.env` 注入（凭据不进脚本）；与现网裸进程运维方式（ppid=1）一致。**责任边界：本机 172.16.100.2 的实际拉起由操作员按部署文档执行（开发会话只验证脚本行为后停掉）**。
  2. **root 级单元模板 `deploy/systemd/reqmesh-harness.service`（可装 systemd 主机用）**：`User=user`、`WorkingDirectory=<repo>/reqmesh-harness`、`EnvironmentFile=-%h/.config/reqmesh-harness/env`（0600，凭据不进单元文件）、`ExecStart=<repo>/reqmesh-harness/.venv/bin/reqmesh-harness --transport http --host 127.0.0.1 --port 8081`（占位符 + 安装说明）、`Restart=on-failure`。**开发会话仅 `systemd-analyze verify` 语法校验（用户可执行）；`install`/`enable`/`start` 需 sudo，属操作员责任边界，步骤写入部署文档**。现网（无用户 bus、无 root 服务习惯）以脚本路径为准，单元文件作为通用部署形态交付。
- **LAN 暴露安全口径（写入部署文档）**：默认 `127.0.0.1` 仅本机可达；`REQMESH_HARNESS_HOST=0.0.0.0` 或 `--host 0.0.0.0` 才向 LAN 暴露 8081——必须显式操作员决策。暴露后的风险与控制：① streamable-HTTP 端点本身无鉴权（MCP 无认证层），READ 工具数据对 LAN 可达客户端可见；② 写工具受审批门（每次调用重读白名单、fail-closed）+ 审计（一行一次写尝试）保护，但白名单/审计文件是**服务器进程所在主机的本地文件**——LAN 客户端不能绕过裁决，也不能伪造白名单，只会拿到 denied + fix_hint；③ reqmesh 认证会话（服务账号 cookie）在 harness 进程内，LAN 客户端不接触凭据；④ Host-header 允许清单（上游 `RT_ALLOWED_HOSTS`）是 reqmesh 上游部署面（code 默认 `["*"]` 关闭校验），不属 harness——部署文档注明边界，不代管上游设置；⑤ 建议：LAN 暴露场景绑定 `0.0.0.0` 前确认网络信任域，或前置反向代理（文档给 nginx/Caddy 示例占位，不强制）。现网对照：8000（reqmesh）/8080（DSH web）均已 0.0.0.0 暴露，8081 的暴露与现网姿态一致，但仍默认不开。

### 开放问题③：DSH 集成部署（已决策）

**决策：mcp-reqmesh 用 stdio transport（对照插件 schema，本会话复核）；cordis.patch.yml 修改的执行责任人 = 操作员（本机用户/方向层），维护窗口执行，开发会话只产出幂等脚本 + 步骤文档；验证 = B 段冒烟 + evals live。**

- **stdio 选型理由**：① 零端口、零新增 LAN 暴露面——MCP server 进程由 DSH spawn，通道只有 stdin/stdout，streamable-HTTP 的「无鉴权 HTTP 面」在本集成中不存在（ADR-0001 双 transport 能力保留给其他消费方）；② 进程生命周期由 DSH 管理（宿主重启自动重拉；插件自动重连默认开、failOnStartupError 默认 false 不拖垮宿主启动）；③ 凭据经 `env` 转发（`!!js process.env.…`），不进 patch 文件；④ 与 P5 spec「DSH 部署步骤」记录形态一致（B 段冒烟前置即该形态，不引入第二种前置）。反例考虑：streamable-http 可避免「每 DSH 实例一个子进程」，但本机仅一个 DSH 宿主，且它把 harness 的生命周期与 systemd/脚本服务解耦成一个额外常驻进程——stdio 更简。**DSH 外的客户端（Claude Desktop/自建 chat）仍走 8081 streamable-HTTP（决策 ②），两 transport 并存是 P1 既有能力。**
- **注册条目（P5 步骤复核后定稿；幂等脚本 `scripts/dsh_register.sh` 产出此片段）**：

  ```yaml
  - id: mcp-reqmesh
    name: '@deepseek-ai/dsh-mcp-client'
    config:
      serverName: reqmesh
      transport: stdio
      command: /home/user/DeepseekHarnessProjects/PRDMS/reqmesh-harness/.venv/bin/reqmesh-harness
      args: ['--transport', 'stdio']
      cwd: /home/user/DeepseekHarnessProjects/PRDMS/reqmesh-harness
      env:
        REQMESH_USERNAME: !!js process.env.REQMESH_USERNAME
        REQMESH_PASSWORD: !!js process.env.REQMESH_PASSWORD
  ```

- **执行责任人与时机（本 spec 界定）**：**责任 = 操作员（本机用户/方向层）**；时机 = P6 开发会话完成后、B 段冒烟/evals live 前，选维护窗口执行。理由：① 重启 8080 宿主会中断方向层自身运行中的工作 GUI（本会话所在宿主），只有宿主使用者能择机执行；② 硬约束链（P5：不得修改运行中宿主配置）在 P6 由 spec 解除为「有责任人的受控变更」，脚本化 + 备份 + 幂等是控制手段；③ 推送/发布职责同理在方向层（design §5），环境配置变更与其同侧。**开发会话不得自行应用注册**（只产出脚本/文档/验证路径）；若开发会话期间操作员已应用，则按 B 段/evals live 前置满足态执行并落盘记录。
- **验证步骤（操作员执行后）**：① DSH 新会话内可见 `mcp__reqmesh__*` 40 工具（list 长度 40、`whoami` 返回 reqmesh-harness/maintainer）；② `REQMESH_P5_SMOKE_B=1 uv run python scripts/smoke_p5.py` → SMOKE-P5-001 落库回读、total 61→62、审计基线差 Δ2 行（P5 实测偏差 3 口径）；③ `uv run python evals/run_live.py` → G1–G4 全绿（残渣 `SMOKE-EVAL-P6-*` 入残渣清单）。

### 开放问题④：版本与发布（已决策）

**决策：版本 0.1.0 → 0.2.0（P1–P6 里程碑合入首个可发布版本）；CHANGELOG/RELEASING 落在 `reqmesh-harness/`（包级，pyproject 是版本唯一事实源）；uv build 产物 = sdist + wheel 入 GitHub Release 资产，dist/ 不入库。**

- **0.2.0 理由**：0.1.0 是 P1 起未发布的开发版本号；P1–P6 完成后首次形成可发布交付，按语义化版本升 minor（0.2.0）。**不取 1.0.0**：harness 仍将演进（ADMIN 层、bulk/rename 族在 P2 延后清单；evals/部署是本 phase 首次落地，未经一次真实发布检验）；1.0 是稳定公开契约承诺，时机未到。里程碑对应：0.2.0 = P1 工具层 + P2 写路径/审批/审计 + P3/P4 复合技能 + P5 运行时 + P6 交付。
- **CHANGELOG 位置**：`reqmesh-harness/CHANGELOG.md`（Keep a Changelog 格式；`[0.2.0]` 段按 P1–P6 分节，`[Unreleased]` 置顶）。放包目录而非仓库根的理据：发布物是 reqmesh-harness 包，版本号事实源（pyproject）与其同目录，changelog 随包一起发布。
- **RELEASING 位置与边界**：`reqmesh-harness/RELEASING.md`（发布流程：版本号变更点、`uv build`、产物约定、tag 约定 `vX.Y.Z`、GitHub Release 资产挂载、推送/打 tag/发 Release 属方向层职责）。**显式边界**：`reqmesh/RELEASING.md`/`reqmesh/DEPLOYMENT.md` 是上游克隆自带文档（reqmesh/ 目录 gitignored，**不得修改**）——本仓发布流程只覆盖 harness；reqmesh 实例的安装/升级引用上游文档为前置，不复制其内容。
- **uv build 产物约定**：`cd reqmesh-harness && uv build` → `dist/reqmesh_harness-0.2.0.tar.gz` + `reqmesh_harness-0.2.0-py3-none-any.whl`（本会话实测 0.1.0 形态）；dist/ 已被根 .gitignore 忽略（不入库）；发布时把两产物挂到 GitHub Release（方向层动作）。**不发布 PyPI**（内部工具；无鉴权保障的公开包面没有需求）。
- **uv.lock 同步**：P5 遗留漂移（事实 9）随本 phase 打包 ticket 提交修复（`uv lock --check` 通过是验收断言）。

### 开放问题⑤：文档清单（已决策）

**决策：根 README.md（新建）+ reqmesh-harness/README.md（扩充）+ 独立 docs/deployment.md；部署文档不并入 README。**

- **根 `README.md`（新建）**：项目地图——PRDMS 是什么（reqmesh 数据层 + harness 编排运行时）、仓库布局、P1–P6 phase 状态表（epic 链接）、文档索引（design/specs/smoke/deployment）、快速开始三行（clone → `cd reqmesh-harness && uv sync && uv run pytest` → 按 reqmesh-harness/README.md 继续）。
- **`reqmesh-harness/README.md`（扩充，结构契约）**：安装（uv sync / wheel 安装 / `uv tool install`）→ 认证（env 凭据、XDG 会话文件、服务账号前置）→ 审批门与审计 → `approvals` CLI 与 `run` CLI（P5，含 provider/--yes/--resume 摘要）→ MCP 双 transport（stdio 供 DSH；streamable-HTTP 默认 127.0.0.1:8081，`/mcp`）→ evals（run_offline/run_live）→ 冒烟（network-tagged 惯例）→ 部署 pointer（`docs/deployment.md`）。
- **部署文档落点：`docs/deployment.md`（仓库 docs/，独立成文）**。理由：部署是操作员长文档（端口/systemd/sudo 边界/LAN 口径/DSH 注册责任边界/验证步骤/回滚），并入 README 会淹没快速开始主线；独立成文可与 spec 同层版本化跟踪，且 P5 spec「DSH 部署步骤」的「完整步骤落入 P6 部署文档」约定即指此。
- **与上游 `reqmesh/DEPLOYMENT.md` 的边界**：本仓部署文档只覆盖 harness（8081 服务、systemd/脚本、DSH 注册、LAN 口径）；reqmesh 实例安装/升级是**前置条件**，文档引用上游（`reqmesh/DEPLOYMENT.md` 与 `install.sh`），不复制、不修改上游内容。

### 开放问题⑥：验收口径（已决策）

**决策：P6 验收标准 12 条（下节）逐条可测试；evals 离线全绿 + live（按部署前置状态）记录落盘；部署文档可复现（免 root 路径本机实测 + systemd 路径语法校验/文档化）；新会话按 README 独立跑通；DSH 注册后 B 段冒烟通过。**

- 每条的「测试者 + 测试法 + 判据」写入验收标准表（归属 ticket），不留口头验收。
- **历史快照口径沿用**：P4 记录的 total=61 自此仅作历史快照（P5 残渣约定：B 段后 total==62；P6 evals live 的 G1/G3 再落残渣 `SMOKE-EVAL-P6-*`，记录注明新基线）。
- **P1–P5 资产保护口径**：533 基线不回退 + 变更白名单（config.py 端口默认值、server.py docstring、test_skeleton 端口断言、README）之外的 P1–P5 资产零 diff（tools/client/server 逻辑/guardrails 裁决路径/ears/lint/report/runtime 行为）。

## P5 遗留承接（显式）

| # | 遗留 | P6 承接 |
|---|---|---|
| 1 | DSH 宿主注册 mcp-reqmesh（cordis.patch.yml 无 mcp 条目） | 决策 ③ + #49：步骤文档 + 幂等脚本 `scripts/dsh_register.sh`；**执行责任人 = 操作员（维护窗口）**，开发会话不执行；验证 = B 段冒烟 + evals live |
| 2 | B 段冒烟重跑（SMOKE-P5-001） | 前置应用后 `REQMESH_P5_SMOKE_B=1 uv run python scripts/smoke_p5.py`；total 61→62、审计基线差 Δ2 行；残渣清单落盘口径不变；未满足前置时记录「待前置后执行」（与 P5 记录同款） |

## 工具层与 ADR 关系（显式声明）

- **ADR-0001 无冲突**：P6 无新工具、无 schema 变更；stdio/streamable-HTTP 双 transport 维持（DSH 用 stdio、其他客户端用 8081 HTTP）；evals 复用 registry/export/guardrails 零复制。
- **ADR-0002 无影响**：无新工具、无动词扩展、无命名变更——无需回写。
- **P2/P3 不变式**：审批门 fail-closed/白名单唯一裁决源/每次重读/审计「一行一次写尝试、denied 也记」/dry-run 不绕审批——P6 全部原样继承；evals G4 拒绝路径即按此断言。唯一裁决语义相关变更 = 无。
- **P1 配置默认值的收编（非冲突，显式标注）**：8123 → 8081 是 P1 spec 明言留给 P6 的开放问题（「正式部署端口是 P6 开放问题」），P6 落定；P1 spec 原文保留为历史记录，不回写（与 smoke total 历史快照同款惯例）。

## 配置项（变更与新增）

- **变更（P6 白名单）**：`harness_port` 默认 8123 → **8081**（`harness_host` 默认 127.0.0.1 不变）；`server.py` docstring、`tests/test_skeleton.py:20` 断言、README 端口行同步。
- **无新增 Settings 字段**：部署参数全部经既有 `REQMESH_HARNESS_HOST/PORT` + CLI `--host/--port` 表达；systemd 单元与 run_server.sh 只组合既有变量，不新增配置面（evals 无需新配置——离线零网络、live 复用 `REQMESH_*` 与 P5 DSH 配置）。
- 其余全部沿用 P1–P5（凭据/审批/审计/run/DSH provider 配置不变）。

## 验收标准（逐条可测试；括号为归属 ticket）

1. `evals/tasks.py` 定义 G1–G5 五任务：每任务含期望工具序列（`ExpectedCall` + 参数匹配器）、最终状态断言、审计期望（离线/live 形态各异处注明）；G1–G4 标注 live 可用、G5 仅离线（#45）。
2. `evals/run_offline.py` 零网络执行 5/5：退出码 0 即全绿；断言点覆盖——G1 落库实体字段相等 + 审计 1 行 approved；G2 报告结构 + P4 golden 基线点检；G3 新链接回读可见 + 审计 1 行；G4 拒绝错误文本含 `ApprovalDeniedError`/`fix_hint` + 审计 1 行 denied + 库状态零变化 + 白名单文件未变；G5 工具序列与脚本一致 + 审计双行 + run 日志 kind 顺序（#45）。
3. `evals/run_live.py` network-tagged（默认不进 pytest 集合）：部署前置满足时 G1–G4 全绿（DSH 事件流工具序列断言 + 真实 GET 回读最终状态；G1/G3 残渣 id `SMOKE-EVAL-P6-G1/G3-*` 入残渣清单）；前置未满足时记录「待前置后执行」；记录落盘 `docs/smoke/P6-cessna-172.md`（时间戳/实例/DSH URL/每步结果/残渣/前置状态）（#46）。
4. 端口收编：`Settings().harness_port == 8081`（默认构造，无 env）；`test_skeleton` 端口断言同步；`--port` 与 `REQMESH_HARNESS_PORT` 覆盖行为不变（#47）。
5. `scripts/run_server.sh start|stop|status|logs` 免 root 可用：start 拉起 8081 streamable-HTTP（127.0.0.1）→ `status` 显示 pid/健康 → MCP 客户端对 `/mcp` 可 list 40 工具 → stop 后端口释放、pidfile 清理；脚本不包含任何凭据字面量（#47）。
6. `deploy/systemd/reqmesh-harness.service` 模板：`systemd-analyze verify` 通过（用户可执行）；占位符（User/WorkingDirectory/ExecStart/EnvironmentFile）与安装说明（sudo install/enable/start）齐备且责任边界（root 操作属操作员）标注（#47）。
7. `docs/deployment.md` 可复现：新会话照文档免 root 路径在本机拉起 8081 服务并验证 40 工具；systemd 路径步骤逐条可执行（sudo 标注）；LAN 安全口径含默认 127.0.0.1/显式 0.0.0.0 开启/READ 暴露与写面护栏说明/RT_ALLOWED_HOSTS 上游边界；与 reqmesh/DEPLOYMENT.md 边界声明（#48）。
8. `scripts/dsh_register.sh` 幂等：对 cordis.patch.yml 的 mcp-reqmesh 条目 insert 重复执行不产生重复条目（dry-run 输出 diff）；条目与决策 ③ 片段逐字一致（serverName=reqmesh/stdio/venv console script/cwd/env 转发）；实际应用与重启**不在脚本职责内**（脚本仅产出/预览，执行责任 = 操作员）（#49）。
9. DSH 注册步骤文档（deployment.md 内）：操作员责任 + 维护窗口 + 备份/回滚 + 重启 + 验证三步（40 工具可见 → B 段冒烟 → evals live）逐条可执行（#49、#48）。
10. 版本与发布：`pyproject.toml version == "0.2.0"`；`reqmesh-harness/CHANGELOG.md` 含 [0.2.0]（P1–P6 分节）与 [Unreleased]；`reqmesh-harness/RELEASING.md` 含 uv build 产物约定（sdist + wheel、dist/ 不入库）、tag `vX.Y.Z`、GitHub Release 资产与方向层职责；`uv lock --check` 通过且 lock 已提交（#50）。
11. README：根 README.md 新建（项目地图 + phase 状态表 + 文档索引）；reqmesh-harness/README.md 按决策 ⑤ 结构扩充（安装/认证/审计/审批/run CLI/MCP 双 transport/evals/冒烟/部署 pointer）；新会话按 README 可独立跑通「uv sync → uv run pytest（533 基线）→ P1 冒烟命令可执行」三步（#51）。
12. 回归与资产保护：离线测试 533 passed / 3 skipped / 2 deselected 不回退（evals 不进 pytest 计数）；对 P1–P5 资产零 diff 断言（tools/ client/ server 逻辑/ guardrails 裁决路径/ ears/ lint/ report/ runtime/ docs/specs/p1–p5/ docs/smoke/P1–P5/ handoffs/p1–p5 均不动；白名单 = config.py 端口默认、server.py docstring、test_skeleton 端口断言、README）；reqmesh/ 目录与 DSH checkout 零改动（#45–#51 共同）。

## Testing Decisions

- evals 自身验收 = 验收标准 1–3：离线 runner 退出码 0 且 5/5 全绿；live runner 按部署前置状态执行并落盘记录。evals 任务定义与 runner 的**单元级**质量由开发会话在 evals/ 内以最小夹具自证（runner 参数化/顺序失配报错路径），不扩充 pytest 主套件。
- 离线 runner 断言只测外部行为：工具调用序列（executor 实际执行的调用 == 期望序列）、写负载形状、审计行、读回响应——不测内部实现（P1–P5 同款口径）。
- live runner 沿用 smoke 惯例：network-tagged 独立脚本、`REQMESH_SMOKE_OUT` 可覆盖记录路径、对 reqmesh 的请求日志断言（写必经审计可查）、残渣清单落盘。
- 冒烟关系：P1–P5 冒烟记录不动；P6 新增记录 `docs/smoke/P6-cessna-172.md`（evals live）。
- 生成模型不重跑（无新请求体）；evals/run_server/unit 文件全部手写纯文本（无生成代码）。

## Out of Scope

- PyPI 发布、容器化部署（上游 reqmesh 有 Docker，harness 免依赖不上容器；无需求）、CI 管线。
- DSH 宿主配置的**自动**管理（注册脚本只产出/预览，应用与重启恒为操作员动作）；多 DSH 实例/多客户端并发的 MCP 会话模型。
- ADMIN 层、bulk/rename 族、新 reqmesh 工具——维持 P2 延后清单与 40 工具注册表不变。
- evals 的持续回归调度（无 CI 前提下，evals 是手动发布门；调度属未来工程化范围）。
- 上游 reqmesh 的安装/升级/Host 允许清单设置（引用上游文档为前置，不代管）。

## Further Notes

- 术语一律按 CONTEXT.md：审批门、权限层级、dry-run、审计、project context、认证会话；harness 侧运行时会话称「run」，DSH 宿主侧一律「DSH session」；「工作会话」指工程对话。
- 与 ADR 的关系：ADR-0001/0002 均无冲突（见「工具层与 ADR 关系」）；P2/P3 不变式原样继承。
- 硬约束遵守：不动 reqmesh/ 目录与 DSH checkout；**不修改运行中 DSH 宿主配置**（注册应用由操作员按决策 ③ 执行，开发会话不执行）；不破坏 P1–P5 资产（验收 12 零 diff 断言）；本地提交、禁止 git push（推送/发布/tag 是方向层唯一职责，design §5）。
- 开发会话按 design §5：实施后自动启动审核子代理与测试子代理；每轮循环结论记对应 ticket comment；超 5 轮仍失败回到需求会话（入口 = 交接文本）。
- 实测偏差回写惯例：开发会话对部署/live evals/DSH 注册的实测偏差记入 `docs/smoke/P6-cessna-172.md`「实测偏差」节，需求会话确认后回写本 spec「实测偏差与决策」节（P1–P5 同款流程）。
