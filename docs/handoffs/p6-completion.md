# P6 开发会话完成报告：交付收尾（evals + 部署 + DSH 集成 + 文档/版本）

> 产出时间：2026-09-03（开发会话收口）；依据 design §5 流程：本地提交（a1030a6 feat + 6dcb421 fix），**未推送**（推送/打 tag/发 Release 是方向层唯一职责）。

## 1. 入口与范围

- Epic：#6；Tickets：#45–#51（状态见 §6 与 ticket comments）
- Spec：[docs/specs/p6-delivery.md](../specs/p6-delivery.md)；交接：[docs/handoffs/p6-delivery.md](p6-delivery.md)
- 硬约束核对：未 push；P1–P5 资产零 diff（见 §3）；未修改 DSH checkout 与运行中 DSH 宿主配置（DSH 注册 = 操作员维护窗口，开发会话只产出幂等脚本 + 步骤文档，**未执行 --apply**）；未动 reqmesh/ 目录（上游文档不改）；凭据零落盘（脚本/文档/审计无凭据字面量，仅环境变量名）。

## 2. 交付物

| 产物 | 路径 |
|---|---|
| evals 任务定义（#45） | `reqmesh-harness/evals/tasks.py`（G1–G5 = 数据：ExpectedCall + 参数匹配器 + 最终状态断言 + AuditRow） |
| evals 离线 runner（#45） | `reqmesh-harness/evals/run_offline.py`（respx + FakeProvider 零网络；退出码 0 即全绿；--selftest 失配报错路径自证） |
| evals live runner（#46） | `reqmesh-harness/evals/run_live.py`（network-tagged；DSH 委托路线 G1–G4；记录落盘 docs/smoke/P6-cessna-172.md） |
| 端口 8081 收编（#47） | `config.py`（默认值 8123→8081）、`server.py` docstring、`tests/test_skeleton.py:20` 断言（白名单内；其余 P1–P5 零 diff） |
| 免 root 部署脚本（#47） | `reqmesh-harness/scripts/run_server.sh`（start|stop|status|logs；pidfile/日志 XDG state；host 参数化端口探测；占用预检 + 僵尸判定） |
| systemd 模板（#47） | `reqmesh-harness/deploy/systemd/reqmesh-harness.service`（User/WorkingDirectory/ExecStart/EnvironmentFile 占位符 + sudo 安装说明；systemd-analyze verify exit 0） |
| DSH 注册脚本（#49） | `reqmesh-harness/scripts/dsh_register.sh`（--check/--dry-run 默认/--apply；幂等 + 备份 + 条目与 spec 决策③逐字一致；应用/重启不属脚本职责） |
| 版本 0.2.0（#50） | `pyproject.toml`（唯一事实源）+ `__init__.__version__` 同步 + `uv.lock` 版本同步；`reqmesh-harness/CHANGELOG.md`（[0.2.0] P1–P6 分节 + [Unreleased]）；`reqmesh-harness/RELEASING.md`（uv build 双产物/dist 不入库/tag vX.Y.Z/GitHub Release 资产=方向层职责/不发 PyPI） |
| README 文档集（#51） | 根 `README.md`（新建：项目地图/布局/phase 状态表/文档索引/快速开始三行）；`reqmesh-harness/README.md` 扩充（安装→认证→审批门与审计→approvals/run CLI→MCP 双 transport→evals→冒烟→部署 pointer） |
| 部署文档（#48） | `docs/deployment.md`（拓扑/配置/免 root/systemd/LAN 安全口径/RT_ALLOWED_HOSTS 上游边界/DSH 注册责任边界 + 备份回滚 + 验证三步） |
| evals live 记录 | `docs/smoke/P6-cessna-172.md`（前置未满足：待前置后执行；含时间戳/实例/DSH URL/每步/残渣/前置状态/实测偏差） |

## 3. P1–P5 资产零 diff 核对（验收 12）

`git diff 36bbf63 HEAD --name-only` = 20 文件：13 个 P6 新增（README.md、docs/deployment.md、docs/smoke/P6-cessna-172.md、CHANGELOG/RELEASING、deploy/systemd/、evals/×3、scripts/×2）+ 7 个授权修改（config.py 端口默认、server.py docstring、test_skeleton 端口断言、README、pyproject/`__init__`/uv.lock 版本同步——`__init__.__version__` 与 pyproject 同步是 test_package_is_installed 断言的必要项，属版本 ticket 显式范围）。
P1–P5 受保护路径（tools/client/guardrails/ears/lint/report/runtime/src 其余/server 逻辑/docs/specs/p1–p5/docs/smoke/P1–P5/handoffs/p1–p5）**零改动**；`reqmesh/` 与 DSH checkout 零改动。

## 4. 测试结果

- 全量离线：**533 passed / 3 skipped / 2 deselected**（两次复跑一致；P1–P5 基线零回退；evals 不在 pytest 集合——`pytest --collect-only | grep -c 'evals/'` == 0）。
- evals 离线：**5/5 全绿**（G1–G5；退出码 0）；--selftest 通过（顺序失配/参数失配/审计失配报错路径 + 匹配器语义）。
- 部署脚本实测：run_server.sh 生命周期（start→status→MCP `/mcp` list 40 工具→logs→stop→端口释放/pidfile 清理）全通过；start 幂等；8081 被占用时 start 明确失败（exit 1 + 错误消息 + pidfile 清理，不覆盖既有监听）。
- systemd 模板：`systemd-analyze verify` exit 0（唯一输出为系统自带 dbus.socket 提示，与本单元无关）。
- dsh_register.sh：副本幂等验证（apply×2 marker 恒 1、备份存在、dry-run diff 不写文件、check 两态）；真实 cordis.patch.yml md5 前后一致。
- 打包：`uv build` 产出 dist/reqmesh_harness-0.2.0.tar.gz + -py3-none-any.whl（dist/ 被 gitignore）；`uv lock --check` exit 0。
- README 三步（#51）：uv sync 幂等；uv run pytest 533；P1 冒烟命令隔离执行 exit 0（REQMESH_SMOKE_OUT/SESSION_FILE 隔离，docs/smoke/P1-cessna-172.md 未变）。

## 5. 冒烟/evals live 状态（#46 + P5 遗留）

- evals live G1–G4：**部署前置未满足**（`/home/user/.dsh/profiles/web/cordis.patch.yml` 无 mcp-reqmesh 条目；开发会话硬约束 = 不应用注册、不重启 8080 宿主）→ 记录 `docs/smoke/P6-cessna-172.md`「待前置后执行」。
- P5 B 段（SMOKE-P5-001）同前置：操作员按 `docs/deployment.md` §6 注册后，`REQMESH_P5_SMOKE_B=1 uv run python scripts/smoke_p5.py` 全量重跑（total 61→62、审计基线差 Δ2 行、无 approval/requested 帧）→ 随后 `uv run python evals/run_live.py`。

## 6. Issue 状态

- ✅ #45 evals 黄金任务集（离线） · ✅ #46 evals live（前置后执行） · ✅ #47 部署形态（8081/run_server/systemd） · ✅ #48 部署文档 · ✅ #49 DSH 集成脚本 · ✅ #50 版本与发布 · ✅ #51 README 文档集——全部 closed（结论见各 ticket comment）。
- Epic #6：保持 open（design §5：推送/关闭属方向层收口；epic 只在代码推送之后关闭）。

## 7. 回流记录（design §5）

- **第 1 轮（审核 + 测试子代理并行）**：
  - 测试子代理：验收 1–12 全部 PASS（逐项实测：533 基线、evals 5/5 + selftest、live 记录字段、run_server 生命周期、systemd verify、dsh_register 幂等、0.2.0 打包、README 三步、零 diff）。发现 2 项：① 8081 被占用时 run_server start 误报成功（端口探测命中占用进程）；② 断言口径字面误报（pytest collect 子串“evaluation”，意图成立）。
  - 审核子代理：规格轴 12 条全 PASS；Standards 1 high（H1：未提交修复）+ 1 medium（M1：class Any 遮蔽 typing.Any）+ 6 low。
  - 修复并复验：① H1/M1 → Wildcard 重命名（已提交）；② run_server.sh：端口占用预检（start 明确失败、不覆盖既有监听）+ pid_alive 僵尸态排除 + port_open HOST 参数化；③ run_live dsn_sessions→dsh_sessions 拼写；④ tasks.py json 导入统一；⑤ CHANGELOG lock 表述校正；⑥ RELEASING 术语（子代理）；⑦ live G1 断言兜底注释。复验：evals 5/5 + selftest 通过、run_server 全场景（占用失败/正常生命周期）、bash -n、AST 通过、533 全量通过。
- **第 2 轮（核验）**：修复后全量 533 passed 437 通过（16.61s）；evals 5/5；run_server 占用场景 exit 1 + 正常生命周期全通过；无新增 ISSUE，交付态定稿（HEAD = 6dcb421）。

## 8. 实测偏差（待需求会话确认——完成报告不代做决策）

1. **G5 run.jsonl 的 question 事件**：spec 验收 2 文字「run 事件日志 kind 顺序（task→tool_call→tool_result→question→…→done）」，但 P5 实现的 LoggingSink.on_question 只转发不落盘——run.jsonl 实际 kind 序列为 task→text→tool_call→tool_result×3→turn_end→done（无 question）。离线 G5 按实际形态断言 + 在 sink 层断言 question 位于两次 review_item 调用之间；已记 docs/smoke/P6-cessna-172.md「实测偏差」。P6 不改 runtime（P1–P5 资产零 diff 硬约束）。
2. **G4 fix_hint 形态**：DRAFT 层 create_requirement 的修复建议为 `reqmesh-harness approvals add create_requirement`（无 --project；gate.py _deny 按 DRAFT project 可省略=通配）；spec 验收 2 写「fix_hint（approvals add 命令）」——断言按实际形态（含 TOML 片段），已记「实测偏差」。

## 9. 后续演进提示（方向层/操作员）

- DSH 注册（操作员维护窗口）：`scripts/dsh_register.sh --apply` → 重启 web 宿主 → 验证 40 工具 → `REQMESH_P5_SMOKE_B=1 uv run python scripts/smoke_p5.py`（B 段 SMOKE-P5-001）→ `uv run python evals/run_live.py`（G1–G4）。
- 方向层：核验本报告 + HEAD（6dcb421，未推送）→ 推送 origin → 打 tag v0.2.0（按 RELEASING.md）→ 挂 dist/ 双产物 → 关闭 epic #6。
- OpenAI 兼容 provider 的 live 冒烟（无 key 环境，D5）——供 key 后复用 smoke 变体（P5 遗留）。
