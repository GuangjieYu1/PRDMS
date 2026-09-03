# RELEASING（reqmesh-harness 发布流程）

> 边界声明：本文件只覆盖 **reqmesh-harness 包**（PRDMS 仓库内）。
> `reqmesh/RELEASING.md` / `reqmesh/DEPLOYMENT.md` 是上游克隆自带文档
> （reqmesh/ 目录 gitignored，**不得修改**）；reqmesh 实例的安装/升级引用上游文档为前置。
> 发布动作（推送、打 tag、发 GitHub Release）属**方向层唯一职责**（design §5）；
> 需求/开发/审核/测试任何会话不得 push、不得发 Release。

## 1. 交付物（每次版本发布）

| 产物 | 位置/形态 | 说明 |
|---|---|---|
| sdist | `dist/reqmesh_harness-<VERSION>.tar.gz` | `uv build` 产物；**dist/ 不入库**（根 .gitignore 忽略） |
| wheel | `dist/reqmesh_harness-<VERSION>-py3-none-any.whl` | 同上；纯 Python 平台无关 |
| 源码 tag | git tag `v<X.Y.Z>` | 指向该版本的发布提交 |
| CHANGELOG | `CHANGELOG.md`（Keep a Changelog） | `[Unreleased]` 置顶；`[<X.Y.Z>]` 段按 phase/主题分节 |

**不发布 PyPI**（内部工具；无鉴权保障的公开包面没有需求）。

## 2. 发布前检查（方向层执行）

1. `cd reqmesh-harness && uv lock --check` —— lock 与 pyproject 同步（P6 起：P5 遗留的 websockets 漂移已修复）。
2. `uv run pytest` —— 离线基线：533 passed / 3 skipped / 2 deselected（**不回退**；evals 不在 pytest 集合）。
3. `uv run python evals/run_offline.py` —— evals 离线 5/5 全绿（发布门）。
4. `uv build` —— 双产物（sdist + wheel）生成。
5. 部署文档复核：`docs/deployment.md` 可复现步骤（免 root 路径 + systemd 模板 + LAN 口径 + DSH 注册）。

## 3. 发布步骤

```bash
cd reqmesh-harness
uv build                                  # dist/reqmesh_harness-<VERSION>.tar.gz + .whl
# 版本号已在 pyproject.toml（唯一事实源）与 src/reqmesh_harness/__init__.py（__version__）同步
uv lock --check
# 方向层：
git tag v<X.Y.Z>
git push origin v<X.Y.Z>
# GitHub Release（方向层）：tag v<X.Y.Z> + 挂载 dist/ 两个产物到 Assets
```

## 4. 版本号约定

- 语义化版本（SemVer）：0.x 区间内 minor 表示里程碑合入（P1–P6 = 0.2.0）；1.0.0 是稳定公开契约承诺——
  当前仍将演进（ADMIN 层、bulk/rename 族在 P2 延后清单），时机未到（spec p6 决策④）。
- 版本号唯一事实源 = `pyproject.toml project.version`；`__init__.__version__` 与其同步
  （test_skeleton 断言之）。

## 5. 回滚/升级边界

- 发布失败（双产物缺失/verify 失败）：不打 tag、不发 Release；修复后重新走 §2–§3。
- 已发版本的缺陷：新版本（patch/minor）修复，不回改已发布 tag（git 历史不可变）。
- reqmesh 实例升级与 harness 无关（引用上游文档）；本仓发布只覆盖 harness。
