# P5 cessna-172 冒烟记录

- 时间：2026-09-02T10:24:27.103251+00:00
- 实例：http://172.16.100.2:8000
- DSH 宿主：http://127.0.0.1:8080（loopback RPC + WS events.mux）
- 结果：**通过**

## 步骤与关键计数

| 实例 | ok | http://172.16.100.2:8000 · DSH http://127.0.0.1:8080 · project cessna-172 |
| A 段：纯回答任务 | ok | session.subscribed ✓、assistant/chunk×55、turn/end ✓、session.list running=false；final=P5-A 冒烟正常 |
| A 段：慢任务 cancel | ok | session.cancel accepted=true + 归闲 |
| A 段 零副作用 | ok | 对 reqmesh 零请求 + 审计 0 行 |
| B 段 部署前置 | 待前置后执行 | B 段未执行：DSH 部署前置未满足（/home/user/.dsh/profiles/web/cordis.patch.yml 无 mcp-reqmesh 条目——本 phase 硬约束：不得修改运行中 DSH 宿主配置；属 P6 部署输入）。前置应用后以 REQMESH_P5_SMOKE_B=1 重跑本脚本执行 B 段（SMOKE-P5-001）。 |

## 帧计数（WS events.mux）

| session/event | 68 |
| session/projection | 22 |
| session/subscribed | 1 |

## 事件计数（session/event）

| assistant/chunk | 55 |
| assistant/message | 1 |
| request/context | 1 |
| request/header | 1 |
| session/title | 2 |
| session/title-llm-request | 1 |
| step/end | 1 |
| step/start | 1 |
| turn/end | 1 |
| user/message | 4 |

## 零副作用与部署前置

- A 段：对 reqmesh 请求：无；审计日志 0 行（临时目录，不触及操作员真实 XDG 文件）；临时 session 由宿主管理。
- B 段：B 段未执行：DSH 部署前置未满足（/home/user/.dsh/profiles/web/cordis.patch.yml 无 mcp-reqmesh 条目——本 phase 硬约束：不得修改运行中 DSH 宿主配置；属 P6 部署输入）。前置应用后以 REQMESH_P5_SMOKE_B=1 重跑本脚本执行 B 段（SMOKE-P5-001）。

## 残渣清单

- 本记录 A 段在 DSH 宿主留下两个临时 DSH session（纯回答任务 + cancel 任务），无副作用数据。
- P5 B 段残渣约定：SMOKE-P5-001（B 段执行后 total==62；P4 记录 61 仅作历史快照）。

## 实测偏差（待需求会话确认）

- A 段实测观察（非偏差，与 spec 事实 4 一致）：events.mux 是**全局多路复用流**——每个连接
  打开时宿主回放全部 running 会话的 session/subscribed（与 projection 帧），随后持续广播
  各会话的 session/event；适配器与冒烟断言均按 sessionId 过滤（本记录帧/事件计数只含
  A 段会话）。附注：本机宿主当前共有 30+ 个 DSH 会话（含方向层工作会话），冒烟未对其做
  任何写操作（A 段对其零暴露——只读订阅 + 自建会话）。

## 开发会话注记

- B 段部署前置未满足（cordis.patch.yml 无 mcp-reqmesh 条目）→ 本 phase 仅记录步骤（spec「DSH 部署步骤」），
  部署属 P6；前置应用后以 `REQMESH_P5_SMOKE_B=1 python scripts/smoke_p5.py` 执行 B 段全量。
