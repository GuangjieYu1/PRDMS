# openapi 快照

- `reqmesh-0.5.0.json`：reqmesh v0.5.0 的 `/openapi.json` 快照，抓取自基线实例 `http://172.16.100.2:8000`（`RT_PROFILE=personal`），P1 需求会话入库（2025-09-01）。
- 用途：`scripts/gen_models.py` 的输入（见 P1 spec 开放问题①的决策），生成产物提交在 `client/generated/`，禁止手改。
- 更新：reqmesh 升级后重新抓取本文件，重跑生成脚本，并在 PR 说明 diff。
- 已知事实：响应体 schema 为 `{}`（未文档化），生成模型的价值在请求体与实体 schemas（79 个）。
