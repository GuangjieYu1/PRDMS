# 交接文本：P6 交付收尾（需求会话 → 开发会话）

> 派发时间：2026-09-03。开发会话以此文件为入口。

## 索引

- **Epic**：[#6](https://github.com/GuangjieYu1/PRDMS/issues/6) [P6] 交付：evals + 部署 + 文档
- **Spec**：`docs/specs/p6-delivery.md`
- **Design doc**：`docs/reqmesh-harness-design.md`（§3 D5/D6/D7/D10、§4 P6 行、§5 流程、§6 P6 预置开放问题、§7 验证基线）
- **相关 ADR**：[0001 MCP 核心协议](docs/adr/0001-mcp-core-tool-protocol.md)（双 transport 维持：DSH 用 stdio、其他客户端用 8081 streamable-HTTP；无冲突）· [0002 工具命名与分组](docs/adr/0002-tool-naming-and-grouping.md)（P6 无新工具/无动词扩展，**无需回写**）
- **P1–P5 参考（勿重做）**：`docs/specs/p1-tool-layer-mvp.md` · `p2-write-path.md` · `p3-nl-requirements.md` · `p4-traceability-report.md` · `p5-runtime.md` · `docs/handoffs/p1–p5` · `docs/smoke/P1–P5-cessna-172.md` · `reqmesh-harness/` 现有代码

## Tickets（阻塞边已声明，frontier 顺序）

| Ticket | 标题 | Blocked by |
|---|---|---|
| [#45](https://github.com/GuangjieYu1/PRDMS/issues/45) | evals 黄金任务集（离线）：任务定义 + run_offline.py + G1–G5 断言 | — |
| [#46](https://github.com/GuangjieYu1/PRDMS/issues/46) | evals live（network-tagged）：DSH 委托路线 G1–G4 + 记录落盘 | #45 |
| [#47](https://github.com/GuangjieYu1/PRDMS/issues/47) | 部署形态：默认端口 8081 + run_server.sh（免 root）+ systemd 单元模板 | — |
| [#48](https://github.com/GuangjieYu1/PRDMS/issues/48) | 部署文档 docs/deployment.md：暴露方式/systemd/LAN 安全口径/上游边界 | #47 |
| [#49](https://github.com/GuangjieYu1/PRDMS/issues/49) | DSH 集成部署：mcp-reqmesh stdio 注册（幂等脚本 + 责任边界 + B 段冒烟验证） | — |
| [#50](https://github.com/GuangjieYu1/PRDMS/issues/50) | 版本与发布：0.2.0 + CHANGELOG/RELEASING + uv build 产物约定 | — |
| [#51](https://github.com/GuangjieYu1/PRDMS/issues/51) | README 文档集：根 README 新建 + reqmesh-harness/README 扩充 | — |

frontier 首步：#45、#47、#49、#50、#51（可并行）；随后 #46（待 #45）、#48（待 #47，与 #49 的注册步骤文档合稿）。

## 本会话决策摘要（开发会话必须遵守）

1. **eval 集形态与范围（①，design §6 预置问题落定）**：独立 `reqmesh-harness/evals/` 目录 + 自有 runner（**不并入 pytest**，533 基线计数不变）；5 个黄金任务 G1–G5——G1 NL 建需求（P3 旗舰①）/ G2 缺口报告（P4 旗舰②，全 READ）/ G3 追踪维护（P2 set_relations）/ G4 审批拒绝路径（denied + fix_hint + 审计 denied 行 + 库零变化 + 白名单未动）/ G5 P5 run 任务（FakeProvider 工具循环：缺口报告→review_item denied→确认→approved，审计双行）；任务定义 = 数据（期望工具序列 + 参数匹配器 + 最终状态断言 + 审计期望），`run_offline.py`（respx + FakeProvider，零网络）与 `run_live.py`（DSH 委托路线，network-tagged）共享。live 前置 = DSH 已注册 mcp__reqmesh__*（与 smoke_p5 B 段同前置）；G1/G3 残渣 id `SMOKE-EVAL-P6-*`。
2. **部署形态（②）**：正式端口 **8081**（8123 是 P1 期开发默认，P1 spec 明言「正式部署端口是 P6 开放问题」；收编为 8081，与 DSH web 8080 同属本机 agentic 工具带）；绑定默认 127.0.0.1，LAN 暴露（`--host 0.0.0.0`）为显式操作员决策。systemd 双轨：**免 root 脚本 `scripts/run_server.sh`（start|stop|status|logs，本机默认路径——本机无用户级 systemd、uid=1000）** + root 级单元模板 `deploy/systemd/reqmesh-harness.service`（可装 systemd 主机；sudo 安装属操作员，开发会话仅 `systemd-analyze verify`）。LAN 安全口径：READ 数据对 LAN 客户端可见、写面受审批门/审计保护（白名单/审计是服务器本机文件，LAN 客户端不可绕过）、凭据在 harness 进程内不外泄、上游 `RT_ALLOWED_HOSTS` 属 reqmesh 部署面不代管。
3. **DSH 集成（③）**：mcp-reqmesh 注册走 **stdio**（零端口零 LAN 面、生命周期随 DSH、env 转发凭据、与 P5 记录形态一致；streamable-HTTP 8081 留给 DSH 外客户端，两 transport 并存是 P1 既有能力）；条目 = P5 spec「DSH 部署步骤」复核后定稿（serverName=reqmesh、venv console script、cwd 使 `.env` 生效）。**cordis.patch.yml 修改的执行责任人 = 操作员（本机用户/方向层），维护窗口执行**（重启 8080 宿主会中断方向层自身 GUI，只有宿主使用者能择机执行）；开发会话只产出幂等脚本 `scripts/dsh_register.sh` + 步骤文档，**不得自行应用**。验证三步：40 工具可见 → B 段冒烟 → evals live。
4. **版本与发布（④）**：`0.1.0 → 0.2.0`（P1–P6 合入首个可发布版本；不取 1.0.0——ADMIN 层/延后工具未交付）；`reqmesh-harness/CHANGELOG.md`（Keep a Changelog）+ `reqmesh-harness/RELEASING.md`（uv build 产物 = sdist + wheel 入 GitHub Release 资产、tag `vX.Y.Z`、推送/发布属方向层；不发布 PyPI）；**不碰 `reqmesh/RELEASING.md`/`DEPLOYMENT.md`（上游克隆自带，gitignored）**；uv.lock 漂移（P5 遗留：HEAD lock 缺 websockets）随 #50 同步提交。
5. **文档清单（⑤）**：根 `README.md` **新建**（当前仓库根无 README）+ `reqmesh-harness/README.md` 扩充（安装/认证/审计/审批/run CLI/MCP 双 transport/evals/冒烟/部署 pointer）+ 独立 `docs/deployment.md`（操作员长文档，不并入 README；只覆盖 harness，reqmesh 实例安装引用上游为前置）。
6. **验收口径（⑥）**：spec 验收标准 12 条逐条可测试（evals 离线 5/5 + live 按前置状态、部署免 root 路径本机可复现、systemd 语法校验 + sudo 步骤文档化、新会话按 README 独立跑通三步、DSH 注册后 B 段冒烟通过、0.2.0 打包齐备、533 基线不回退 + P1–P5 资产零 diff）。total 历史快照口径：B 段后 62，P4 记录 61 仅作历史快照；evals live G1/G3 再落残渣。

## 本会话核实的事实（spec「事实核实」节 13 条，开发会话以此为准，勿重新猜测）

1. **端口**：8080=DSH web（`dsh --profile web --no-open --port 8080`）、8000=reqmesh（uvicorn，由 DSH 进程派生）、3080=webserver 插件；8081/9001/5173 空闲。
2. **systemd**：`/usr/bin/systemctl` 存在但**无用户级 systemd**（`systemctl --user` → No medium found）；`/etc/systemd/system/` 无自定义 service；uid=1000；现网服务全是裸进程（ppid=1）。
3. **cordis.patch.yml**：仅 webserver 条目，**无 mcp 条目**（P5 事实复核成立）。
4. **dsh-mcp-client schema**（本会话复核）：stdio `{transport,serverName(必填,[A-Za-z0-9_-]{1,32}),command(必填),args,env,cwd,toolCallTimeoutMs(60000),failOnStartupError(false),reconnect(默认开)}`；streamable-http `{transport,serverName,url(必填),headers,…}`；工具名 `mcp__<serverName>__<rawName>`；重复 serverName 是加载错误。
5. **uv build 形态**（实测）：sdist + `py3-none-any.whl`；hatchling；`dist/` 被根 .gitignore 忽略（产物不入库）。
6. **streamable-HTTP 监听**：`REQMESH_HARNESS_HOST/PORT`（代码默认 127.0.0.1:8123）+ CLI `--host/--port`；端点 `/mcp`；stateless。
7. **冒烟惯例**：`scripts/smoke_p*.py` 独立 network-tagged 脚本（P3–P5 无 pytest 包装）；`REQMESH_SMOKE_OUT` 落盘 `docs/smoke/P*-cessna-172.md`；pytest 默认排除 network。
8. **测试基线**：536 收集 / 2 deselected = 533 passed / 3 skipped（P5 记录口径）。
9. **uv.lock 漂移**：HEAD lock 缺 websockets；工作树已补齐且 `uv lock --check` 通过（随 P6 提交）。
10. **RT_ALLOWED_HOSTS**：reqmesh 上游 Host-header 校验（code 默认 `["*"]` 关闭）——上游部署面，harness 不代管。
11. **gh**：已认证 GuangjieYu1；open issue 仅 epic #6（本会话新增 #45–#51 后共 8 个 open）。
12. **B 段冒烟门控**：`REQMESH_P5_SMOKE_B=1`；断言 total 61→62、审计**基线差 Δ2 行**（共享 XDG 文件口径）、无 approval/requested 帧。
13. **venv console script**：`reqmesh-harness/.venv/bin/reqmesh-harness` 存在（stdio 条目 command）。

## P1–P4/P5 复用点（勿重做，勿破坏）

- `tools/registry.py` / `tools/__init__.py`：40 工具注册表是 evals 与部署验证的唯一工具面（evals 复用 `registry.call`/run_task/executor）；**零修改**。
- `tools/export.py`、`guardrails/`（gate/whitelist/audit/approvals_cli）：evals 只 import，**零复制裁决逻辑**（G4 拒绝路径按 P2 不变式断言）。
- `runtime/`（P5）：run CLI 的 DSH 委托路线即 evals live 的驱动；FakeProvider/ConfirmedToolExecutor 即离线 runner 的执行器；**行为零修改**。
- `client/session.py`/`config.py`：XDG 惯例、`resolved_*` 模式沿用（run_server.sh 的 pidfile/日志、systemd EnvironmentFile 均按此）；P6 变更白名单仅 `harness_port` 默认值 8123→8081 + server.py docstring + `tests/test_skeleton.py:20` 断言 + README 端口行。
- 冒烟/记录惯例：network-tagged 独立脚本 + `docs/smoke/` 落盘 + 残渣清单 + 历史快照口径（P1–P5 模式）；P6 新增 `docs/smoke/P6-cessna-172.md`。
- `.env` 凭据不落盘；审计字段契约 version=1 零改动。

## DSH 部署步骤归属（P5 遗留承接，本 spec 界定）

- **注册条目**（stdio，决策 ③ 定稿）：见 #49 body（与 P5 spec「DSH 部署步骤」逐字一致）。
- **执行责任人 = 操作员（本机用户/方向层）**；**时机 = P6 开发会话完成后、B 段冒烟/evals live 前，维护窗口执行**。理由：重启 8080 宿主中断方向层自身工作 GUI；硬约束「不得修改运行中宿主配置」由 spec 解除为「有责任人的受控变更」。
- **开发会话职责**：产出 `scripts/dsh_register.sh`（幂等 + dry-run + 备份）+ 部署文档步骤（备份/回滚/重启/验证三步）；**不执行应用、不重启宿主**。若开发会话期间操作员已应用，则按前置满足态跑 B 段与 evals live 并落盘。
- **验证（操作员执行）**：① DSH 新会话可见 40 个 `mcp__reqmesh__*` 工具（whoami=reqmesh-harness）→ ② `REQMESH_P5_SMOKE_B=1 uv run python scripts/smoke_p5.py`（SMOKE-P5-001、total 61→62、审计基线差 Δ2 行）→ ③ `uv run python evals/run_live.py`（G1–G4）。

## 验收标准（epic → spec → tickets）

- evals 离线 5/5 全绿（G1–G5 断言见 #45）；evals live G1–G4 + 记录落盘（#46）
- 端口 8081 收编 + run_server.sh 免 root 可用 + systemd 单元模板 verify 通过（#47）
- docs/deployment.md 可复现 + LAN 安全口径 + 上游边界 + 注册步骤合稿（#48）
- dsh_register.sh 幂等 + 责任边界 + B 段冒烟验证路径（#49）
- 0.2.0 + CHANGELOG/RELEASING + uv build 产物约定 + uv.lock 同步（#50）
- 根 README 新建 + 包 README 八节扩充 + 新会话三步可跑通（#51）
- 回归：533 基线不回退 + P1–P5 资产零 diff（白名单：config.py 端口默认/server.py docstring/test_skeleton 端口断言/README）（#45–#51 共同）

## 回流规则（design §5）

开发会话完成后自动启动审核子代理与测试子代理；每轮循环结论摘要记入对应 ticket comment；超过 5 轮仍失败 → 回到需求会话重新对齐（入口本文件）。

## 硬约束

- **本地提交，禁止 git push**（推送是方向层唯一职责，design §5；打 tag/发 GitHub Release 同属方向层）。
- 术语遵循 `CONTEXT.md`（审批门/权限层级/dry-run/审计/工作会话/认证会话；harness 侧运行时会话称 run，DSH 侧一律 DSH session）；与 ADR 冲突须显式指出（本会话：与 ADR-0001/0002 均无冲突；8123→8081 是 P1 spec 明言留给 P6 的开放问题，非冲突）。
- 不动 `reqmesh/` 目录（含上游 DEPLOYMENT/RELEASING）；**不修改 DSH checkout 与运行中 DSH 宿主配置**（注册由操作员按决策 ③ 执行）；不破坏 P1–P5 资产（验收 12 零 diff 断言 + docs/smoke/P1–P5 记录不动）。
- 凭据边界：凭据只经环境变量/`.env` 注入；不进脚本/单元文件/文档/日志/审计。

## 开发会话开场（可直接作为新工作会话的首条消息）

你是 P6 的「开发会话」——PRDMS 工程流程模型（docs/reqmesh-harness-design.md §5）中 P6 phase（最后一个）的实施工作会话。只做实现与验证，不做需求决策；需求已由需求会话定案，规格即契约。

### 入口（先读，按顺序）
1. `docs/handoffs/p6-delivery.md` —— 本会话唯一交接索引：epic #6、tickets #45–#51 阻塞边与 frontier、决策摘要①–⑥、核实事实 13 条、P1–P5 复用点、DSH 部署步骤归属、硬约束。
2. `docs/specs/p6-delivery.md` —— 实施契约：事实核实 13 条、Implementation Decisions①–⑥、12 条验收标准（逐条挂 ticket）、Testing Decisions、Out of Scope。
3. `docs/reqmesh-harness-design.md`（§3、§4 P6 行、§5 流程、§7 验证基线）、`CONTEXT.md`（术语，用词必须遵循）、`docs/adr/0001-mcp-core-tool-protocol.md`、`docs/adr/0002-tool-naming-and-grouping.md`。
4. P1–P5 specs/handoffs 与 `reqmesh-harness/` 现有代码（复用，不要重做）；DSH checkout 只读（禁止修改）：`/home/user/.npm-global/lib/node_modules/@deepseek-ai/dsh`；运行中宿主 `http://127.0.0.1:8080` 只读。

### Tickets（frontier 顺序，阻塞边见上文表）
#45、#47、#49、#50、#51 可并行 → #46（待 #45）→ #48（待 #47，与 #49 注册步骤合稿）。

### 必须遵守的需求会话决策与事实（不要重议，spec 为准）
- evals：独立 `evals/` 目录 + 自有 runner，不并入 pytest；G1–G5 任务定义 = 数据（期望序列/最终状态/审计期望）；离线零网络、live 走 DSH 委托路线且与 smoke_p5 B 段同部署前置。
- 部署：正式端口 8081（代码默认收编；白名单变更 = config.py/server.py docstring/test_skeleton 端口断言/README）；本机无用户级 systemd → 免 root `run_server.sh` 是本机默认路径，systemd 单元模板供通用主机且仅 `systemd-analyze verify` 校验（sudo 安装属操作员）。
- DSH 集成：mcp-reqmesh 用 stdio；**开发会话不得应用 cordis.patch.yml 注册、不得重启 8080 宿主**（执行责任人 = 操作员，维护窗口）；只产出 dsh_register.sh + 部署文档步骤。
- 版本：0.2.0（pyproject 唯一事实源）；CHANGELOG/RELEASING 在 reqmesh-harness/；uv build 产物不入库；不碰 reqmesh/ 上游文档；uv.lock 同步提交。
- 术语 CONTEXT.md：harness 侧运行时会话称 run，DSH 宿主侧一律「DSH session」；审批门、权限层级、dry-run、审计、工作会话照词表。

### 流程（design §5）
- 用 tdd 技能实施（red-green-refactor，先测试后实现）；evals 离线 runner 零网络；live 脚本 network-tagged。
- 实施完成后自动启动审核子代理与测试子代理；每轮循环结论摘要记入对应 ticket comment；超过 5 轮仍失败 → 回到需求会话（入口 = 本交接文本）。
- 测试通过后：关 tickets #45–#51 → 产出完成报告（git 历史、测试结果、evals/冒烟记录路径、issue 状态、待需求会话确认的实测偏差清单）→ 实测偏差按惯例回写 spec「实测偏差与决策」节 → 本地提交，禁止 git push。

### 硬约束
- 本地提交，禁止 git push（推送/发布/tag 是方向层唯一职责，design §5）。
- 不动 `reqmesh/` 目录；不修改 DSH checkout 与运行中宿主配置；不破坏 P1–P5 资产（离线基线 533 passed / 3 skipped / 2 deselected 不回退；对 P1–P5 资产零 diff，白名单见上文）。
- 凭据不进日志/审计/脚本/单元文件；`.env` 不落盘。
- evals live 记录落盘 `docs/smoke/P6-cessna-172.md`（时间戳、实例、DSH URL、每步结果、残渣清单、部署前置状态）。

### 完成标准（epic #6 底线）
- evals 离线 5/5 全绿 + live（按部署前置状态）记录落盘；部署文档可复现（免 root 路径本机实测）；0.2.0 打包齐备（uv build 双产物 + CHANGELOG/RELEASING）；README 可让新会话独立跑通三步。
- DSH 注册后（操作员执行）：B 段冒烟通过（SMOKE-P5-001、total 61→62、审计基线差 Δ2 行）——P5 遗留闭环。
- spec 验收标准 1–12 全部满足、无未决项；P1–P5 基线 533 不回退。

## 需求会话回流确认（2026-09-03，开发会话完成报告核实后）

完成报告已实测核验（本会话独立复核，非仅读报告；入口 `docs/handoffs/p6-completion.md`）：

1. **git**：本地 main 领先 origin/main **5 commits**（a29a042→36bbf63→a1030a6→6dcb421→fbb2854，未 push）；工作树干净；`git diff 36bbf63 HEAD` = **19 文件（12 新增 + 7 授权修改）**——12 新增 = 根 README、docs/deployment.md、docs/handoffs/p6-completion.md、docs/smoke/P6-cessna-172.md、CHANGELOG/RELEASING、deploy/systemd/ 单元、evals/×3、scripts/×2；7 授权修改 = pyproject/`__init__`/uv.lock 版本同步 + config.py 端口默认 + server.py docstring + test_skeleton 端口断言 + harness README。P1–P5 受保护路径（tools/client/guardrails/ears/lint/report/runtime/其余 server 逻辑/docs/specs/p1–p5/docs/smoke/P1–P5/handoffs/p1–p5）**零改动**；reqmesh/ 目录与 DSH checkout 零改动；完成报告 §3 的「20 文件/13 新增」计数差 1，已在本会话确认中修正（记录口径）。
2. **测试**：离线复跑 **533 passed / 3 skipped / 2 deselected**（16.95s，P5 基线零回退）；evals 离线 **5/5 全绿**（exit 0）+ `--selftest` 通过；evals 不进 pytest 集合。
3. **部署实测**：run_server.sh 生命周期本会话实跑通过（start→status（127.0.0.1:8081 LISTEN）→stop→端口释放/pidfile 清理→status 未运行）；`systemd-analyze verify` exit 0（唯一输出为系统自带 dbus.socket 提示）；`uv lock --check` exit 0；`uv build` 产出 dist/reqmesh_harness-0.2.0.{tar.gz,whl}（gitignored）。
4. **DSH 集成零改动核对**：真实 `/home/user/.dsh/profiles/web/cordis.patch.yml` 仍仅 webserver 条目（本会话 cat 复核）；`dsh_register.sh --check` 正确报告「缺失」（exit 1）——开发会话未执行 --apply，符合 spec 决策 ③ 责任边界。
5. **冒烟/live 状态**：`docs/smoke/P6-cessna-172.md` 完整——live G1–G4「待前置后执行」（部署前置未满足），残渣约定（SMOKE-EVAL-P6-G1/G3、G2 零残渣、G4 零落库）与 P5 B 段残渣（SMOKE-P5-001/total 62）均已注明；P1–P5 冒烟记录未动。
6. **issues**：#45–#51 全部 CLOSED（回流结论评论齐全）；epic #6 OPEN（按 design §5 由方向层推送后关闭）。
7. **2 项实测偏差全部确认接受**并回写 spec「实测偏差与决策」节（确认版）：
   - ① G5 run.jsonl 无 question 事件（P5 LoggingSink.on_question 只转发不落盘）——spec 验收 2 措辞与 G5 行按实际形态回写；P5 spec ⑤ 与实现的既有差距以记录口径接受，P6 不改 runtime（零 diff 硬约束），未来如需 run 日志完整性另行立项；
   - ② G4 fix_hint 无 --project（gate.py DRAFT 通配语义）——spec G4 行补注，措辞泛指原文与实际形态一致。

确认摘要记 #45/#46 comment。方向层可执行：推送 origin（36bbf63..HEAD）→ 打 tag v0.2.0 + 挂 dist/ 双产物（按 reqmesh-harness/RELEASING.md）→ 关闭 epic #6；操作员按 docs/deployment.md 维护窗口执行 DSH 注册后补跑 `REQMESH_P5_SMOKE_B=1 uv run python scripts/smoke_p5.py`（B 段闭环）与 `uv run python evals/run_live.py`（G1–G4）。
