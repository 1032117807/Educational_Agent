from __future__ import annotations

import shutil
import subprocess
import sys
import os
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-only", action="store_true")
    args = parser.parse_args()
    deploy = shutil.which("pyside6-deploy")
    if not deploy:
        candidate = Path(sys.executable).parent / "Scripts" / "pyside6-deploy.exe"
        deploy = str(candidate) if candidate.exists() else None
    if not deploy:
        raise SystemExit("未找到 pyside6-deploy，请先安装 requirements.txt")
    if not args.package_only:
        command = [
            deploy, str(ROOT / "app" / "main.py"), "--name", "PersonalLearningDesktop",
            "--extra-modules", "QtCharts,QtSql", "--mode", "standalone", "--force",
        ]
        print("执行：", " ".join(command))
        cache_dir = ROOT / ".build-cache" / "nuitka"
        cache_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            command, cwd=ROOT, check=False,
            env={**os.environ, "NUITKA_CACHE_DIR": str(cache_dir)},
        )
        if result.returncode:
            print("构建失败")
            return result.returncode
    executables = list((ROOT / "app").glob("*.dist/*.exe"))
    if not executables:
        print("构建失败：未生成可执行文件")
        return 1
    distribution = executables[0].parent
    shutil.copy2(ROOT / "alembic.ini", distribution / "alembic.ini")
    shutil.copytree(ROOT / "migrations", distribution / "migrations", dirs_exist_ok=True)
    output_dir = ROOT / "dist"
    output_dir.mkdir(exist_ok=True)
    archive_base = output_dir / "PersonalLearningDesktop-1.0.0-windows-x64"
    archive = Path(shutil.make_archive(str(archive_base), "zip", distribution))
    print(f"构建完成：{executables[0]}")
    print(f"分发包：{archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
