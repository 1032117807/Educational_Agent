from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    if not args.executable.is_file():
        raise SystemExit(f"发布程序不存在：{args.executable}")
    with tempfile.TemporaryDirectory() as data_dir:
        environment = {**os.environ, "LEARNING_DATA_DIR": data_dir}
        for phase in ("首次启动", "退出后重开"):
            result = subprocess.run(
                [str(args.executable), "--smoke-test"],
                env=environment,
                check=False,
                timeout=30,
            )
            if result.returncode:
                raise SystemExit(f"{phase}冒烟失败：{result.returncode}")
        if not (Path(data_dir) / "learning.db").exists():
            raise SystemExit("发布版没有创建数据库")
        if not any((Path(data_dir) / "workspace").rglob("release-smoke.txt")):
            raise SystemExit("发布版没有完成资料导入")
    print("发布版启动、建库、建课程、导入文本、建任务、退出和重开均通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
