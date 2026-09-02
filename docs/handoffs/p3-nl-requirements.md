# 交接文本：P3 自然语言建需求（需求会话 → 开发会话）

> 派发时间：2026-09-01。开发会话以此文件为入口。

## 索引

- **Epic**：[#3](https://github.com/GuangjieYu1/PRDMS/issues/3) [P3] 复合技能①：自然语言建需求（EARS + quality lint 闭环）
- **Spec**：`docs/specs/p3-nl-requirements.md`
- **Design doc**：`docs/reqmesh-harness-design.md`（§3 D5/D6/D8、§5 流程、§7 验证基线）
- **相关 ADR**：[0001 MCP 核心协议](docs/adr/0001-mcp-core-tool-protocol.md) · [0002 工具命名与分组](docs/adr/0002-tool-naming-and-grouping.md)（P3 将回写 verb 词汇表扩展 `draft` 实现注记）
- **P1/P2 参考（勿重做）**：`docs/specs/p1-tool-layer-mvp.md` · `docs/specs/p2-write-path.md` · `docs/handoffs/p1-tool-layer-mvp.md` · `docs/handoffs/p2-write-path.md` · `reqmesh-harness/` 现有代码

## Tickets（阻塞边已声明，frontier 顺序）

| Ticket | 标题 | Blocked by |
|---|---|---|
| [#25](https://github.com/GuangjieYu1/PRDMS/issues/25) | lint 模块：本地 quality lint（规则镜像 + 项目 config + 确定性修正表） | — |
| [#26](https://github.com/GuangjieYu1/PRDMS/issues/26) | EARS 模板与 NL 解析：五句式 + 要点形式 + 字段映射 + next-uid 集成 | — |
| [#27](https://github.com/GuangjieYu1/PRDMS/issues/27) | draft_requirement 复合工具：NL→EARS→lint 循环→P2 写路径落库（审批门/审计/dry-run） | #25, #26 |
| [#28](https://github.com/GuangjieYu1/PRDMS/issues/28) | get_requirement_quality READ 工具 + 注册表/OpenAI 导出对账（39 工具） | — |
| [#29](https://github.com/GuangjieYu1/PRDMS/issues/29) | 离线测试套件：lint 循环/金样例/负例/对账 | #25, #26, #27, #28 |
| [#30](https://github.com/GuangjieYu1/PRDMS/issues/30) | cessna-172 冒烟：金样例 A 段零副作用 + B 段真实写闭环（SMOKE-P3） | #27, #28, #29 |

frontier 首步：#25、#26、#28（可并行）；随后 #27；再后 #29；#30 收尾（网络冒烟）。

## 本会话决策摘要（开发会话必须遵守）

1. **工具命名与形态（开放问题①）**：单个复合工具 `draft_requirement`（verb `draft`，注册表 level=DRAFT、domain=复合技能）+ 单个 READ 工具 `get_requirement_quality`（domain=需求）；注册表 37 → **39 行**，OpenAI 导出 1:1 对账。编排全部在工具内部同步完成（P5 前无 agent 运行时，D5）；**不拆分**多步工具。ADR-0002 关系：`draft` 是 verb 词汇表扩展（P2 同款机制，开发会话完成后回写实现注记）；`draft_` 前缀与 DRAFT 层级同形歧义已显式声明（动词非层级前缀 + 审批门绝不解析名字 → 扩展而非冲突）。
2. **EARS 句式子集与字段映射（②）**：完整五句式（ubiquitous/event/unwanted/state/optional），受控自然语言（标记句 When/If/While/Where + shall 或要点 key: value 行）；**仅英文槽位**（中文输入 InputParseError，翻译是 P5 职责；中文会因英文 regex 假性满分，违背 quality 闭环目的）；不编造内容。字段映射：description=EARS 句子、name=response 派生（首字母大写截 80）、status 固定 proposed、rationale 溯源 NL 原文、verification_* 不可写；id 缺省内部 GET `/requirements/next-uid`（409 重取一次，不新增公开工具）。
3. **lint 入口与过线标准（③）**：**本地镜像**规则集（reqmesh 公开规则契约 20 条独立重写，**不复制 GPL 源码**——P1 许可证边界同款决策；rule id/severity/weight 对齐上游，finding message 中文）。每次调用 GET /quality 取项目 config（失败回落默认 config 标注 config_source）。过线 = 零 error 级 finding（placeholder）+ score ≥ `REQMESH_LINT_MIN_SCORE`（默认 90）。EARS 结构检查为二进制 gate 不进打分（保「本地分 == 服务端分」可对账）。新增 `get_requirement_quality` 供落库后服务端分对账（/quality 过滤，无独立需求级端点——上游写入时零 quality 校验，已核实）。
4. **迭代策略（④）**：工具内确定性修正循环 ≤ `REQMESH_LINT_MAX_ROUNDS`=3 轮（收敛检测）；修正表 6 类（weak_words 情态替换/superfluous_infinitive/escape_clauses/oblique/abbreviation/parentheses），其余残余；残余白名单 unwanted→{negation}（EARS 与 INCOSE R16 固有张力，不允许反转语义）；placeholder 立即拒绝、`require_measurable=true`（默认）拒绝无单位文本（绝不编造数字，`false` 显式豁免）；未过线 → persisted=false + 报告 + hint（不落库、不记审计）。
5. **与审批门关系（⑤）**：draft_requirement 走 P2 审批门，白名单条目按工具名独立裁决（DRAFT 层：tool 必填、project 可省略通配；**审批它不等于审批 create_requirement**）；落库复用 `_write_common.write_request`（tool="draft_requirement"，**零修改 P2 文件**，仅 import provided/create_checks/write_request/UNSET 与生成模型 RequirementCreate）；dry-run 语义完整继承 P2（照跑审批门、不发写请求、不产生 git 提交）；审计每次到达写路径一行，params_summary 附加 lint_score/lint_rounds 标量；InputParseError/lint 未过线不记审计（写尝试边界，供审核子代理核对）。
6. **验收金样例（⑥）**：5 条金样例覆盖五句式（G1 ubiquitous 1185 km / G2 event 302 km/h / G3 state 2.5 m/s / G4 optional 15 m / G5 unwanted 1 s），本地分 == 服务端分 == 100（G4 默认 config 98：passive_voice info 权重 2——cessna-172 config 已关 passive_voice）。冒烟 A 段全量 dry_run（零副作用：total 不变 58、无写请求、git 条件断言）+ B 段 G1/G2/G5 真实写（SMOKE-P3-001..003，回读文本相等、unreviewed 可见、服务端分对账 100、审计计数、total==61）；负例（弱词修正/placeholder/measurable/N 轮/中文）离线单测覆盖。B 段不调用 review_item（新需求保持未评审是设计语义）。

## 本会话核实的事实（spec「事实核实」节，开发会话以此为准，勿重新猜测）

1. P1 无 quality 工具；`get_project_report(report="quality")` 已覆盖项目级 GET /quality（响应 {average, total, config, per_requirement[]}，cessna-172 实测 average=89）；需求级无独立端点；上游**写入时零 quality 校验**。
2. create_requirement：id 必填（safe_id + 宽松命名校验，冲突 409）；description 纯文本 sanitize 存储（纯文本原样回读）；verification_method 不可写、无验证用例回落 "test"（untestable 规则因此默认生效）；PUT 部分更新 exclude_unset（P2 已实现）。
3. quality 规则集：上游 README 称「INCOSE/EARS/ISO 29148」，**代码级只有 INCOSE 逐条引用**（R01/R07/R08/R10/R11/R16/R17/R19/R20/R21/R24/R26/R35/R38），**无 EARS 实现、无 ISO 29148 专属规则**；20 条规则明细与权重见 spec 表；config 键复数差异（vague_quantifiers/placeholders）。
4. next-uid 实测返回 {"prefix": "REQ", "next_id": "REQ0001"}（P1/P2 延后端点，P3 内部启用）。

## P1/P2 复用点（勿重做，勿破坏）

- `tools/registry.py`：ToolSpec/ToolRegistry/`annotations_for`（DRAFT → readOnlyHint=False 已有）——P3 只加 2 行注册（build_registry），不动既有 37 行。
- `tools/groups/_write_common.py`：`write_request`/`provided`/`create_checks`/`UNSET`——draft_requirement 落库直接复用（零修改）。
- `client/generated/models.py`：`RequirementCreate`/枚举（RequirementType/Priority）——请求体组装复用，禁手改生成产物。
- `client/session.py`/`reader.py`：认证会话 + 只读视图——next-uid 与 /quality config 经 reader 直连。
- `guardrails/`：审批门（fail-closed、DRAFT 通配规则）、审计 JSONL、approvals CLI——全部按 P2 现状复用，仅白名单新增 `draft_requirement` 条目。
- `config.py` Settings：新增 `REQMESH_LINT_MIN_SCORE`（默认 90）、`REQMESH_LINT_MAX_ROUNDS`（默认 3）两个环境变量，其余不动。
- `tools/export.py`：OpenAI 导出同源（39 工具对账）；`server.py` 双 transport 装配不动。
- `tests/mapping.py`/`tests/support/`、`scripts/smoke_p1.py`/p2 模式：P3 增 2 行 ToolMap + `scripts/smoke_p3.py`。
- 冒烟前置沿用 P2：reqmesh-harness（maintainer）服务账号；git 断言条件化（is_repo=false 降级，P2 实测偏差 2 同款）。

## 验收标准（epic → spec → tickets）

- 五句式渲染与金样例表逐字符一致（#26、#29）
- 本地 lint：G1–G5 == 100、修正/拒绝/残余各有用例（#25、#29）
- 服务端分对账 == 本地分 == 100（#30 B 段）
- 审批门 fail-closed + dry_run 零副作用 + 审计字段（#27、#30）
- 注册表 39 行 + OpenAI 导出 1:1 对账（#28）
- 冒烟记录落盘 `docs/smoke/P3-cessna-172.md`（#30）

## 回流规则（design §5）

开发会话完成后自动启动审核子代理与测试子代理；每轮循环结论摘要记入对应 ticket comment；超过 5 轮仍失败 → 回到需求会话重新对齐（入口本文件）。

## 硬约束

- **本地提交，禁止 git push**（推送是方向层唯一职责，design §5）。
- 术语遵循 `CONTEXT.md`（审批门/权限层级/dry-run/审计/工作会话等）；与 ADR 冲突须显式指出（本会话：ADR-0002 verb 词汇表扩展 + draft/DRAFT 同形歧义，见 spec ①，非冲突）。
- 不动 `reqmesh/` 目录（上游部署克隆，只读参考）；不动已关闭的 P1/P2 资产（`writes.py`/`_write_common.py`/审批门/审计零修改，仅 import 复用；注册表仅加行）。
- 许可证边界：本地 lint 独立重写规则（不复制 reqmesh GPL 源码），等价性靠冒烟「本地分 == 服务端分」对账。

## 需求会话回流确认（2026-09-02，开发会话完成报告核实后）

完成报告已实测核验（本会话复核，非仅读报告）：

1. **git**：本地 main 领先 origin/main **5 commits**（b612909→4a593c9→020056e→a776f3f→f99932d，未 push）；P1/P2 核心资产零修改（writes.py / _write_common.py / guardrails/ / client/ / server.py / export.py / registry.py 无 diff）；reqmesh/ 上游目录未动。
2. **测试**：离线复跑 **329 passed / 2 skipped / 2 deselected**（13.4s）；MCP stdio/http 测试断言 39 工具；OpenAI 导出 golden 同步。
3. **冒烟**：docs/smoke/P3-cessna-172.md 完整（A 段零副作用 + B 段 SMOKE-P3-001..003 + 审计 9 行）；**A 段已由本会话按最终脚本语义 live 复验**（G1–G5 dry_run：ears 逐字符/name 派生/type 按表/score=100/rounds=1/config_source=project，total 61→61，审计 6 行——零副作用再确认）；**B 段残渣已回读核验**（description/name/status=proposed/unreviewed 可见/服务端分=100）。
4. **issues**：#25–#30 全部 CLOSED（回流结论评论齐全）；epic #3 OPEN（含开发会话收口摘要）。
5. **4 项实测偏差全部确认接受**并回写 spec「实测偏差与决策」节（P2 同款流程）：
   - ① 打分取整 **98→97（floor）**：上游 int(clamped*100//max_penalty)，实现取上游一致（本地分==服务端分对全部分数成立）；spec 判例已改。
   - ② G5「is unlatched」同触发 passive_voice（默认 config 97，与 G4 同）——spec ⑥ G5 说明已补。
   - ③ ⑥ type 列口径 = **冒烟调用参数**（工具默认 functional）；首轮残渣 type=functional 为历史事实，接受记录（P2 残渣同款；重跑需 ADMIN 清理后按表落库）。
   - ④ 服务账号 maintainer：P2 已确认，README 已同步，无新增动作。
6. 许可证边界已核实：lint/rules.py 独立重写有推导依据注记 + 结构差异声明（15/17 与上游不同形；oblique/non_atomic 为 spec 自身描述的最小形式）——审核子代理 P0 项已闭环。

确认摘要记 #29/#30 comment。方向层可执行：推送 origin（aa6b76f..HEAD）→ 关闭 epic #3。
