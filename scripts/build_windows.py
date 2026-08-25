from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import argparse
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sign_executable(executable: Path, *, required: bool) -> None:
    """Sign the Windows executable when release credentials are provided."""
    certificate_path = os.environ.get("WINDOWS_SIGN_CERT_PATH", "").strip()
    if not certificate_path:
        if required:
            raise SystemExit(
                "缺少 WINDOWS_SIGN_CERT_PATH；正式发布包必须使用代码签名证书。"
            )
        print("未配置代码签名证书：生成的是仅供本地验证的未签名构建。")
        return

    certificate = Path(certificate_path).expanduser()
    if not certificate.is_file():
        raise SystemExit(f"代码签名证书不存在：{certificate}")

    sign_tool = os.environ.get("WINDOWS_SIGNTOOL_PATH", "").strip()
    sign_tool = sign_tool or shutil.which("signtool")
    if not sign_tool:
        raise SystemExit(
            "未找到 signtool。请安装 Windows SDK，或设置 WINDOWS_SIGNTOOL_PATH。"
        )

    command = [
        sign_tool, "sign", "/fd", "SHA256", "/td", "SHA256",
        "/tr", os.environ.get("WINDOWS_SIGN_TIMESTAMP_URL", "https://timestamp.digicert.com"),
        "/f", str(certificate),
    ]
    password = os.environ.get("WINDOWS_SIGN_CERT_PASSWORD", "")
    if password:
        command.extend(["/p", password])
    command.append(str(executable))
    if subprocess.run(command, check=False).returncode:
        raise SystemExit("Windows 代码签名失败。")
    if subprocess.run([sign_tool, "verify", "/pa", str(executable)], check=False).returncode:
        raise SystemExit("Windows 代码签名验证失败。")
    print("Windows 代码签名与验证已完成。")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-only", action="store_true")
    parser.add_argument(
        "--require-signature",
        action="store_true",
        help="fail unless WINDOWS_SIGN_CERT_PATH is configured and the EXE verifies",
    )
    args = parser.parse_args()
    if args.require_signature and not os.environ.get("WINDOWS_SIGN_CERT_PATH", "").strip():
        raise SystemExit(
            "正式 Windows 发布需要 WINDOWS_SIGN_CERT_PATH；"
            "请先配置受信任的代码签名证书，再运行 --require-signature。"
        )
    if not args.package_only:
        build_root = ROOT / ".build-cache" / "pyinstaller"
        distribution_root = ROOT / "app"
        command = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm", "--clean", "--onedir", "--windowed",
            "--name", "PersonalLearningDesktop",
            "--icon", str(ROOT / "app" / "resources" / "app_icon.ico"),
            "--paths", str(ROOT),
            "--distpath", str(distribution_root),
            "--workpath", str(build_root / "work"),
            "--specpath", str(build_root / "spec"),
            "--add-data", f"{ROOT / 'app' / 'resources'};resources",
            "--add-data", f"{ROOT / 'alembic.ini'};.",
            "--add-data", f"{ROOT / 'migrations'};migrations",
            "--hidden-import", "langchain_chroma",
            # Local OCR/embedding stacks are optional. The release keeps the
            # SaaS AI/RAG path while avoiding multi-gigabyte ML frameworks.
            "--exclude-module", "paddleocr",
            "--exclude-module", "paddle",
            "--exclude-module", "torch",
            "--exclude-module", "transformers",
            "--exclude-module", "scipy",
            "--exclude-module", "sympy",
            "--exclude-module", "fastembed",
            "--exclude-module", "huggingface_hub",
            "--exclude-module", "sklearn",
            "--exclude-module", "tokenizers",
            "--exclude-module", "onnxruntime",
            str(ROOT / "app" / "main.py"),
        ]
        print("执行：", " ".join(map(str, command)))
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode:
            print("构建失败")
            return result.returncode
    executable = ROOT / "app" / "PersonalLearningDesktop" / "PersonalLearningDesktop.exe"
    if not executable.is_file():
        print("构建失败：未生成可执行文件")
        return 1
    sign_executable(executable, required=args.require_signature)
    distribution = executable.parent
    shutil.copy2(ROOT / "alembic.ini", distribution / "alembic.ini")
    shutil.copytree(ROOT / "migrations", distribution / "migrations", dirs_exist_ok=True)
    executable_digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    manifest = {
        "product": "PersonalLearningDesktop",
        "version": "1.0.0",
        "platform": "windows-x64",
        "executable": executable.name,
        "executable_sha256": executable_digest,
    }
    (distribution / "release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    output_dir = ROOT / "dist"
    output_dir.mkdir(exist_ok=True)
    archive_base = output_dir / "PersonalLearningDesktop-1.0.0-windows-x64"
    archive = Path(shutil.make_archive(str(archive_base), "zip", distribution))
    archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(archive.suffix + ".sha256").write_text(
        f"{archive_digest}  {archive.name}\n", encoding="ascii"
    )
    print(f"构建完成：{executable}")
    print(f"分发包：{archive}")
    print(f"SHA-256 校验文件：{archive.with_suffix(archive.suffix + '.sha256')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
