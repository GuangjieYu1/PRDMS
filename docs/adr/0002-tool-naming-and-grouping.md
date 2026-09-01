# 工具命名与分组：verb_entity，无权限前缀

P1 需求会话对开放问题「工具命名前缀与分组方式」做出决策：MCP server 名定为 `reqmesh`（ADR-0001 已示 `mcp__reqmesh__<tool>`），工具名统一为 `<verb>_<entity>` snake_case，**不在工具名中携带权限层级前缀**；权限层级记录在工具注册表（唯一事实源）、MCP `annotations.readOnlyHint` 与工具 description（READ 层工具一律以 `READ-ONLY` 开头），P2 的审批门从注册表映射层级而非解析名字。分组按实体域（认证/项目、需求、追踪/覆盖、风险/决策、验证/分析/规格/定义、组件/基线/变更请求、报告）进行，在 MCP `tags` 与 spec 分节中呈现。

## Considered Options

- **权限前缀（`read_`/`mutate_`…）**：拒绝。与 MCP server 前缀叠加后冗长（`mcp__reqmesh__read_list_requirements`），且名字与层级双轨记录容易漂移；层级是护栏的属性，应单点维护在注册表。
- **纯动词前缀、每端点一工具**：拒绝。158 条路径会产生 80+ 工具，超出模型可操作范围；改为语义合并（见下）。

## Consequences

- verb 词汇表固定并按层级扩展：READ = `list` / `get` / `search`；P2 起新增 `create` / `update` / `delete` 等写动词。
- 合并模式：次要实体的 list 工具接受可选 `<entity>_id` 参数（省略返回集合，给出返回单条）；计算型报告合并为一个工具 + `report` 枚举参数。
- 护栏（P2）不得依赖名字推断权限层级，必须查注册表。
- 工具 description 使用中文书写（与仓库文档语言一致），标识符保持英文。
