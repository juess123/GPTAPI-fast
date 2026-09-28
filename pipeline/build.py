#!/usr/bin/env python3
"""Execute one generated Excel script and validate its workbook output."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
XLSX_NAME = "final_quote.xlsx"


def make_run_dir(output_root: Path) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H%M%S")
    run_dir = output_root / stamp
    suffix = 2
    while run_dir.exists():
        run_dir = output_root / f"{stamp}-{suffix}"
        suffix += 1
    run_dir.mkdir()
    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="执行生成的 Excel 脚本并检查工作簿")
    parser.add_argument("--gen-dir", default=str(ROOT / "pipeline" / "generated"))
    parser.add_argument("--out-dir", default=str(ROOT / "output"))
    parser.add_argument("--input-dir", default=str(ROOT / "input"))
    parser.add_argument("--task-packages-dir")
    parser.add_argument("--run-dir", help="指定现有输出目录，用于 Excel 自动修复重试")
    parser.add_argument("--run-name", help="保留兼容参数；指定固定子目录名")
    args = parser.parse_args(argv)

    gen_dir = Path(args.gen_dir).expanduser().resolve()
    output_root = Path(args.out_dir).expanduser().resolve()
    input_dir = Path(args.input_dir).expanduser().resolve()
    script = gen_dir / "make_xlsx.py"
    if not script.is_file():
        print(f"[错误] 找不到 Excel 构建脚本：{script}", file=sys.stderr)
        return 1

    if args.run_dir:
        run_dir = Path(args.run_dir).expanduser().resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
    elif args.run_name:
        run_dir = output_root / Path(args.run_name).name
        run_dir.mkdir(parents=True, exist_ok=True)
    else:
        run_dir = make_run_dir(output_root)

    child_env = os.environ.copy()
    child_env.update({
        "OUT_DIR": str(run_dir),
        "INPUT_DIR": str(input_dir),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    })
    if args.task_packages_dir:
        python_packages = Path(args.task_packages_dir).expanduser().resolve() / "python"
        old_path = child_env.get("PYTHONPATH", "")
        child_env["PYTHONPATH"] = str(python_packages) + (os.pathsep + old_path if old_path else "")

    print(f"本次输出目录: {run_dir}", flush=True)
    command = [sys.executable, str(script)]
    print("$ " + " ".join(f'"{part}"' if " " in part else part for part in command), flush=True)
    proc = subprocess.run(command, cwd=ROOT, env=child_env, text=True,
                          encoding="utf-8", errors="replace")
    xlsx = run_dir / XLSX_NAME
    if proc.returncode != 0 or not xlsx.is_file():
        detail = (f"make_xlsx.py 返回 {proc.returncode}" if proc.returncode else
                  f"make_xlsx.py 未生成 {XLSX_NAME}")
        failure = {
            "schema": 1,
            "failure_type": "xlsx_runtime_error" if proc.returncode else "xlsx_missing_output",
            "message": detail,
            "output": "脚本执行失败或未生成指定 Excel 文件。",
            "script": str(script),
            "expected": str(xlsx),
        }
        (run_dir / "xlsx_failure.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[错误] {detail}", file=sys.stderr)
        return 1

    try:
        from openpyxl import load_workbook
        workbook = load_workbook(xlsx, read_only=True, data_only=False)
        sheet_names = workbook.sheetnames
        if not sheet_names:
            raise ValueError("工作簿中没有工作表")
        workbook.close()
    except Exception as error:  # noqa: BLE001
        failure = {
            "schema": 1,
            "failure_type": "xlsx_invalid_output",
            "message": f"Excel 文件无法正常读取：{type(error).__name__}: {error}",
            "output": "openpyxl 无法打开模型生成的工作簿。",
            "script": str(script),
            "expected": str(xlsx),
        }
        (run_dir / "xlsx_failure.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[错误] {failure['message']}", file=sys.stderr)
        return 1

    (run_dir / "xlsx_failure.json").unlink(missing_ok=True)
    print(f"工作表: {', '.join(sheet_names)}")
    print(f"XLSX_ONLY_OK {xlsx} ({xlsx.stat().st_size} 字节)", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
