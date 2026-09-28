#!/usr/bin/env python3
"""Excel-only flow: send materials to GPT, install Python deps, build workbook."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent


def run(command: list[str]) -> int:
    print("$ " + " ".join(f'"{part}"' if " " in part else part for part in command), flush=True)
    return subprocess.run(command, cwd=ROOT).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--gen-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--task-packages", required=True)
    args = parser.parse_args(argv)

    input_dir = Path(args.input_dir).resolve()
    gen_dir = Path(args.gen_dir).resolve()
    output_root = Path(args.out_dir).resolve()
    task_packages = Path(args.task_packages).resolve()
    gen_dir.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)

    if run([sys.executable, str(HERE / "ask_model.py"), "--input-dir", str(input_dir),
            "--gen-dir", str(gen_dir)]):
        return 1

    dependencies = gen_dir / "dependencies.json"
    if not dependencies.is_file():
        dependencies.write_text(json.dumps({"python": []}), encoding="utf-8")
    try:
        declared = json.loads(dependencies.read_text(encoding="utf-8"))
        if not isinstance(declared, dict) or not isinstance(declared.get("python", []), list):
            raise ValueError("dependencies.json 中 python 必须是数组")
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"[错误] 无效的任务依赖声明：{error}", file=sys.stderr)
        return 1

    if run([sys.executable, str(HERE / "dependency_manager.py"), "--ensure-task",
            "--dependencies", str(dependencies), "--task-packages", str(task_packages)]):
        return 1

    build_cmd = [sys.executable, str(HERE / "build.py"), "--gen-dir", str(gen_dir),
                 "--out-dir", str(output_root), "--input-dir", str(input_dir),
                 "--task-packages-dir", str(task_packages)]
    for attempt in range(3):
        if run(build_cmd) == 0:
            runs = sorted((path for path in output_root.iterdir() if path.is_dir()),
                          key=lambda path: path.stat().st_mtime, reverse=True)
            if not runs:
                print("[错误] Excel 构建未产生输出目录", file=sys.stderr)
                return 1
            (output_root / "LATEST_RUN.txt").write_text(str(runs[0]), encoding="utf-8")
            print(f"EXCEL_WORKFLOW_OK {runs[0]}", flush=True)
            return 0

        runs = sorted((path for path in output_root.iterdir() if path.is_dir()),
                      key=lambda path: path.stat().st_mtime, reverse=True)
        failure = runs[0] / "xlsx_failure.json" if runs else None
        if failure is None or not failure.is_file() or attempt >= 2:
            print("[错误] Excel 生成失败，已达到自动修复次数上限或缺少错误报告。",
                  file=sys.stderr)
            return 1

        repair_report = gen_dir / f"xlsx-failure-attempt-{attempt + 1}.json"
        shutil.copy2(failure, repair_report)
        print(f"Excel 脚本运行失败，自动修复 {attempt + 1}/2", flush=True)
        if run([sys.executable, str(HERE / "repair_xlsx.py"), "--input-dir", str(input_dir),
                "--gen-dir", str(gen_dir), "--report", str(repair_report),
                "--attempt", str(attempt + 1)]):
            return 1
        build_cmd = [sys.executable, str(HERE / "build.py"), "--gen-dir", str(gen_dir),
                     "--out-dir", str(output_root), "--input-dir", str(input_dir),
                     "--task-packages-dir", str(task_packages), "--run-dir", str(runs[0])]

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
