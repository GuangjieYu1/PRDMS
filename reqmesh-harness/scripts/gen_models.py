#!/usr/bin/env python3
"""确定性 pydantic 模型生成管线（P1 spec 开放问题①的落地）。

输入：vendored openapi 快照 openapi/reqmesh-0.5.0.json（来自基线实例 /openapi.json）。
输出：src/reqmesh_harness/client/generated/models.py —— 提交入库，禁止手改。

已知事实（见 openapi/README.md）：reqmesh 的 openapi 只文档化请求体/创建/更新模型与
枚举，不文档化实体响应与实体 schema（如 Requirement）；因此生成模型的价值在
请求体/实体写入模型（P2 复用）与 fixture 形状校验，P1 工具层响应为原始 JSON 透传，
类型化输出模型留待 P3/P4 手写窄模型 + golden 校验。

重跑本脚本 git diff 应为空（确定性）：生成器版本经 uv.lock 锁定，
--disable-timestamp 去掉时间戳，头部固定（生成器版本 + 来源快照，脚本注入）。
"""

import importlib.metadata
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "openapi" / "reqmesh-0.5.0.json"
OUTPUT = ROOT / "src" / "reqmesh_harness" / "client" / "generated" / "models.py"


def banner() -> str:
    try:
        gen_version = importlib.metadata.version("datamodel-code-generator")
    except importlib.metadata.PackageNotFoundError:
        gen_version = "(未安装 datamodel-code-generator)"
    return (
        "# 此文件由 scripts/gen_models.py 从 vendored openapi 快照确定性生成——请勿手改。\n"
        f"# 生成器: datamodel-code-generator {gen_version}（版本经 uv.lock 锁定）"
        f" · 来源: openapi/{SNAPSHOT.name}\n"
    )


def main() -> None:
    if not SNAPSHOT.exists():
        sys.exit(f"快照缺失: {SNAPSHOT}（先按 openapi/README.md 抓取）")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir=OUTPUT.parent)
    tmp.close()
    cmd = [
        sys.executable,
        "-m",
        "datamodel_code_generator",
        "--input",
        str(SNAPSHOT),
        "--input-file-type",
        "openapi",
        "--output",
        tmp.name,
        "--output-model-type",
        "pydantic_v2.BaseModel",
        "--disable-timestamp",
        "--enum-field-as-literal",
        "all",
    ]
    print("运行:", " ".join(str(c) for c in cmd[4:]))
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-4000:])
        sys.exit(f"datamodel-code-generator 失败（exit {proc.returncode}）")
    generated = Path(tmp.name).read_text(encoding="utf-8")
    OUTPUT.write_text(banner() + generated, encoding="utf-8")
    Path(tmp.name).unlink(missing_ok=True)
    print(f"已写出 {OUTPUT}")


if __name__ == "__main__":
    main()
