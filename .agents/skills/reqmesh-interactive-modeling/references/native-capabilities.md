# 原生能力与当前 MCP 边界

核实环境：PRDMS 的 reqmesh 0.5.0 与本地 reqmesh-harness；工具可能被宿主加命名空间。以下不是对未来部署的硬编码契约，使用前检查实际 schema。

| 内容 | 原生承载及边界 |
|---|---|
| 需求义务 | Requirement；subject 可引用其约束的组件。parent 只承载层级，不替代任意语义关系 |
| 系统组成 | Component；按实际支持的类型建模。业务数据概念不天然等于 software |
| 数值/计算 | Parameter 的 value、expr、unit；支持 calc_def/bindings 时可复用计算定义 |
| 条件约束 | Constraint 的 expr、assume，或 constraint_def/bindings；缺值与前提不成立不能一概报违反 |
| 可复用定义 | Definition 的 calc / constraint；不是通用领域词典 |
| 关系 | relations、traces、分配等各有用途；relation.type 字符串可存储不等于自动具备类型/基数推理 |
| 来源 | source、references 的 path、sha256、lines 等按实际写入 schema 使用 |

## 可用工具的核实基准

- 读取：list_projects、list_requirements、get_requirement、search_requirements、list_components、list_definitions、get_traces；集合读取注意分页。
- 报告：get_project_report 的 report 包括 validation / evaluation / quality 等；检查当前枚举。quality 是文本质量检查，不等于语义一致性证明。
- 写入：create_requirement / update_requirement、create_component / update_component 支持的参数按实时 schema 构造；set_relations 和 set_allocation 的整体替换语义须先读取确认。
- 当前 Definitions 和 AnalysisCases 主要暴露读取，不假定 create_definition / create_analysis_case 存在。原生能力存在和 MCP 可写是两回事。
- draft_requirement 是可落库的复合工具，名称中的 draft 不意味着仅本地草拟。它也不代替多对象交互式建模流程。
- 写工具默认 dry_run=false；必须显式设置。dry-run 同样经过工具审批门。白名单授权不等于用户认可业务含义。

## DSH 实测补充（2026-09-15）

- 原生表达式基于 Python AST；直接的 ENTITY.parameter 引用要求 ENTITY 是合法标识符。能通过对象命名检查的连字符 ID 不一定可用于表达式。calc_def/bindings 可提供另一条引用路径，但必须确有定义及对应工具能力。
- Parameter 的 unit 标签不自动换算数值：30 配 unit="%" 仍以30参与算术；百分数参与乘法时必须明确数学换算。
- rollup 聚合组件子树参数可承载某些变长场景；这不自动批准将业务对象映射为组件。
- Requirement.relations 的 derives 与项目 get_traces 矩阵是不同存储表面。回读关系应查需求对象；矩阵为空不证明关系丢失，不自动补做全量 set_relations。
- 实测非规范教学场景 normative=false 的参数和约束仍被 evaluation 评价。按具体报告检查覆盖，不凭 normative 标志推断跳过。
- 本次发现冻结基线 name 被通用检查误当作缺 id 的损坏文件，已修复本地后端。其他未打补丁部署仍可能报告该问题；核对证据，不改基线数据以消除误报。

## 不能从现有设施推定的保证

`tools/groups/_write_common.py` 的 checks 只在 dry-run 中运行且仅为提示，真实写入路径不以这些 checks 阻断。没有完整候选图校验、多对象事务或绑定候选摘要的用户批准机制；本 Skill 提供执行纪律，不把它描述为服务端强制保证。

Parameter 使用浮点值；精确金额、舍入与容差不能自行补充。原生求值器能评价特定参数场景，不等于证明任意自然语言需求整体可满足。

## 判断示例

原文规则为“比例合计 100%”，示例为 30% / 30% / 10%：报告该场景合计 70%，附原文和影响对象，询问修正规则还是示例。不自行改为 30% / 30% / 40%。若用户只批准教学假设，正式候选仍保留待裁决。

输入精度与存储精度不同：报告边界差异和潜在溢出范围；不能自行决定扩字段、截断或舍入。

新旧规则使用不同单位或适用不同期间：先核实可比性，不能仅因数值不同断言冲突。
