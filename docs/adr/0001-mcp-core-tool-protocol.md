# MCP 为核、OpenAI function 导出为辅的工具协议

reqmesh-harness 的工具层以 Model Context Protocol 为核心对外暴露（stdio + streamable-HTTP 双 transport），同一批工具定义再导出 OpenAI function-calling JSON 供自建运行时使用。决定依据：MCP 已被 DSH 原生消费（`mcp__<server>__<tool>` 注册机制），且工具协议与内置 agent 运行时的 LLM provider 完全解耦。

## Considered Options

- **仅 OpenAI function calling**：拒绝。DSH 无 OpenAI 兼容端点，且该格式只覆盖函数调用，不覆盖资源/流式语义。
- **仅 MCP**：可行但放弃自建运行时的零成本复用；双导出只是 schema 层的第二份序列化。
- **MCP 为核 + OpenAI 导出**（选定）：一次定义、两处消费。

## Consequences

- harness 可作为 MCP server 被 DSH/Claude 等宿主直接嵌套，工具名形如 `mcp__reqmesh__list_requirements`。
- P5 的 agent loop 与 provider（DeepSeek API 或本地 DSH 的 loopback RPC）可独立演进，不触碰工具定义。
