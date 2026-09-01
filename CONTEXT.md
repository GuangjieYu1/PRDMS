# PRDMS

PRDMS 是需求管理工具链的主工作区：本地部署 reqmesh 作为数据层，自研 reqmesh-harness 作为外层 Agentic 编排运行时。

## Language

### 系统与代码

**PRDMS**:
本仓库（`GuangjieYu1/PRDMS`），项目主工作区。

**reqmesh**:
上游开源需求管理工具（v0.5.0），本地部署于 172.16.100.2，是 harness 的被编排数据层。
_Avoid_: 需求工具、被调方（用完整名字）

**reqmesh-harness**:
本仓库自研的外层编排运行时（Python 包 `reqmesh_harness`），把 reqmesh 的 API 封装为模型可调用的工具。
_Avoid_: 外层 harness、调度器

**harness**:
外层编排运行时；本仓库语境下即 reqmesh-harness。

### 运行时概念

**tool（工具）**:
模型可调用的单个封装操作（读/写实体、分析、导出等）。
_Avoid_: 技能（在 DSH 语境另有含义）

**approval gate（审批门）**:
按权限层级拦截写操作的确认机制。
_Avoid_: 授权闸、写保护

**权限层级**:
READ（只读）/ DRAFT（草稿）/ MUTATE（变更）/ ADMIN（管理）四级。

**project context（项目上下文）**:
运行时会话锚定的 reqmesh 项目。

**dry-run（预览）**:
计算并展示操作结果但不写库。
_Avoid_: 试运行、模拟执行

**session（运行时会话）**:
harness 的一次对话。**只**用于此义。
_Avoid_: 用它指工程对话（那是「工作会话」）

### 工程流程

**工作会话**:
需求/开发两类工程对话；审核与测试以子代理形式在开发工作会话内运行。
_Avoid_: session、轮次

**需求会话**:
单个 phase 的起始工作会话：产出 spec 与 tickets，完成后派发开发会话。

**开发会话**:
单个 phase 的实施工作会话：开发完成后自动启动审核子代理与测试子代理。

**子代理**:
开发会话内自动启动的审核/测试代理。

**phase（实施阶段）**:
harness 建设的阶段划分：P1 工具层 MVP、P2 写路径、P3 复合技能①（自然语言建需求）、P4 复合技能②（追踪/覆盖缺口报告）、P5 内置运行时、P6 交付。每个 phase 依次走需求会话与开发会话。

**epic**:
GitHub 上追踪单个 phase 的 issue，作为工作会话的交接索引。
