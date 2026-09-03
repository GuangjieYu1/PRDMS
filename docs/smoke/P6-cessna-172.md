# P6 cessna-172 冒烟/evals live 记录

- 时间：2026-09-03T02:33:38.445229+00:00
- 实例：http://172.16.100.2:8000
- DSH 宿主：http://127.0.0.1:8080（loopback RPC + WS events.mux）
- 项目：cessna-172
- 结果：详见「步骤」

## 步骤

| 实例 | ok | http://172.16.100.2:8000 · DSH http://127.0.0.1:8080 |
| live 前置（DSH 注册） | 待前置后执行 | /home/user/.dsh/profiles/web/cordis.patch.yml 无 mcp-reqmesh 条目（注册属操作员维护窗口，spec 决策③；脚本 scripts/dsh_register.sh） |
| evals live G1–G4 | 待前置后执行 | 前置应用后执行：uv run python evals/run_live.py |

## 帧计数（WS events.mux）

| （无帧） | 0 |

## 事件计数（session/event）

| （无事件） | 0 |

## 残渣清单

- live 残渣约定（spec 验收 3）：G1 需求 id SMOKE-EVAL-P6-G1、G3 追踪链接 target SMOKE-EVAL-P6-G3
  （SMOKE-EVAL-P6-* 统一前缀）；G2 全 READ 零残渣；G4 denied 落库零行无残渣；
  P5 B 段残渣 SMOKE-P5-001（total 62）与 P4 记录 total 61 均按历史快照口径（spec 验收口径⑥）。

## 部署前置状态

- /home/user/.dsh/profiles/web/cordis.patch.yml：无 mcp-reqmesh 条目（待操作员维护窗口注册）

## 实测偏差（待需求会话确认）

- **G5 run.jsonl 的 question 事件**：spec P6 验收 2 写「run 事件日志 kind 顺序
  （task→tool_call→tool_result→question→…→done）」，但 P5 实现的 LoggingSink.on_question
  只转发不落盘（run.jsonl 无 question kind——离线 G5 按实际形态断言：
  task→text→tool_call→tool_result×3→turn_end→done，并在 sink 层断言 question 事件位于
  两次 review_item 调用之间）。属 P5 实现与 P5 spec ⑤ 记录形态的偏差，P6 不改 runtime。
- **G4 fix_hint 形态**：spec 验收 2 写「fix_hint（approvals add 命令）」——DRAFT 层
  create_requirement 的修复建议为 reqmesh-harness approvals add create_requirement
  （无 --project；gate.py _deny 按 DRAFT project 可省略=通配），G4 按此断言。

## 注记

- 离线 evals 全绿命令：uv run python evals/run_offline.py（零网络；5/5）。
- live 前置由操作员按 docs/deployment.md「DSH 注册」维护窗口执行后，以
  uv run python evals/run_live.py 执行（REQMESH_SMOKE_OUT 可覆盖记录路径）。
