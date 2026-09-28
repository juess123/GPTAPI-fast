#!/usr/bin/env python3
"""Manage locked base Python packages and isolated per-task Python dependencies."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
LOCK_DIR = ROOT / ".dependency-install.lock"
PYTHON_REQUIREMENTS = ROOT / "requirements.txt"


def locked_packages(path: Path) -> list[str]:
    result = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            if "==" not in line:
                raise RuntimeError(f"依赖没有锁定精确版本：{line}")
            result.append(line)
    return result


def package_names(path: Path) -> list[str]:
    return [re.split(r"\[|==", item, maxsplit=1)[0] for item in locked_packages(path)]


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def required_versions(path: Path) -> dict[str, tuple[str, str]]:
    result = {}
    for item in locked_packages(path):
        left, version = item.rsplit("==", 1)
        name = left.split("[", 1)[0]
        result[canonical(name)] = (name, version)
    return result


def missing_requirements(path: Path, search_path: Path | None = None) -> list[str]:
    wanted = required_versions(path)
    distributions = (importlib.metadata.distributions() if search_path is None
                     else importlib.metadata.distributions(path=[str(search_path)]))
    installed = {canonical(dist.metadata["Name"]): dist.version
                 for dist in distributions if dist.metadata.get("Name")}
    return [f"{name}=={version}" for key, (name, version) in wanted.items()
            if installed.get(key) != version]


def lock_owner_is_alive() -> bool:
    try:
        text = (LOCK_DIR / "owner.txt").read_text(encoding="utf-8")
        pid = int(dict(line.split("=", 1) for line in text.splitlines()).get("pid", "0"))
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError, OSError):
        return False


@contextmanager
def install_lock(timeout: int = 3600):
    start = time.time()
    while True:
        try:
            LOCK_DIR.mkdir()
            (LOCK_DIR / "owner.txt").write_text(
                f"pid={os.getpid()}\ntime={time.time()}\n", encoding="utf-8")
            break
        except FileExistsError:
            if not lock_owner_is_alive():
                shutil.rmtree(LOCK_DIR, ignore_errors=True)
                continue
            if time.time() - start > timeout:
                raise RuntimeError("等待依赖安装锁超时")
            time.sleep(1)
    try:
        yield
    finally:
        shutil.rmtree(LOCK_DIR, ignore_errors=True)


def run_checked(command: list[str]) -> None:
    print("$ " + " ".join(f'"{part}"' if " " in part else part for part in command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def ensure_python_packages() -> None:
    expected = VENV / "Scripts" / "python.exe"
    if Path(sys.executable).resolve() != expected.resolve():
        raise RuntimeError(f"请使用项目环境运行依赖检查：{expected}")
    missing = missing_requirements(PYTHON_REQUIREMENTS)
    if missing:
        print("普通 Python 缺失或版本不符：" + ", ".join(missing))
        run_checked([str(expected), "-m", "pip", "install", "--disable-pip-version-check",
                     "--requirement", str(PYTHON_REQUIREMENTS)])
    else:
        print("普通 Python 依赖已满足")


def ensure_all() -> None:
    with install_lock():
        ensure_python_packages()


def validate_task_requirements(items: object) -> list[str]:
    if not isinstance(items, list):
        raise RuntimeError("dependencies.python 必须是数组")
    result = []
    for raw in items:
        if not isinstance(raw, str) or not raw.strip():
            raise RuntimeError("dependencies.python 包含无效项目")
        text = raw.strip()
        try:
            requirement = Requirement(text)
        except InvalidRequirement as error:
            raise RuntimeError(f"无效的 PyPI requirement：{text}（{error}）") from error
        if requirement.url:
            raise RuntimeError(f"任务依赖不接受 URL/Git 来源：{text}")
        result.append(text)
    return list(dict.fromkeys(result))


def installed_manifest(target: Path) -> list[dict[str, str]]:
    packages = []
    for distribution in importlib.metadata.distributions(path=[str(target)]):
        name = distribution.metadata.get("Name")
        if name:
            packages.append({"name": name, "version": distribution.version})
    return sorted(packages, key=lambda item: item["name"].lower())


def installed_versions(search_path: Path | None = None) -> dict[str, tuple[str, str]]:
    distributions = (importlib.metadata.distributions() if search_path is None
                     else importlib.metadata.distributions(path=[str(search_path)]))
    return {canonical(dist.metadata["Name"]): (dist.metadata["Name"], dist.version)
            for dist in distributions if dist.metadata.get("Name")}


def split_reusable(requirements: list[str], base: dict[str, tuple[str, str]]) -> tuple[list[str], list[dict[str, str]]]:
    install = []
    reused = []
    for text in requirements:
        requirement = Requirement(text)
        present = base.get(canonical(requirement.name))
        satisfied = (present is not None and not requirement.extras
                     and (not requirement.specifier
                          or requirement.specifier.contains(present[1], prereleases=True)))
        if satisfied:
            reused.append({"requirement": text, "name": present[0], "version": present[1],
                           "source": ".venv"})
        else:
            install.append(text)
    return install, reused


def ensure_task(dependencies_path: Path, task_packages: Path) -> None:
    try:
        data = json.loads(dependencies_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"无法读取任务依赖声明：{error}") from error
    requirements = validate_task_requirements(data.get("python", []))
    target = task_packages / "python"
    task_packages.mkdir(parents=True, exist_ok=True)
    install, reused = split_reusable(requirements, installed_versions())
    for item in reused:
        print(f"复用 {item['source']}：{item['name']}=={item['version']}")
    with install_lock():
        target.mkdir(parents=True, exist_ok=True)
        if install:
            run_checked([str(VENV / "Scripts" / "python.exe"), "-m", "pip", "install",
                         "--disable-pip-version-check", "--upgrade", "--ignore-installed",
                         "--target", str(target), *install])
    manifest = {
        "requested": {"python": requirements},
        "installed": {"python": installed_manifest(target)},
        "reused": {"python": reused},
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    (task_packages / "environment.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"任务级 Python 依赖已就绪：{task_packages}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ensure", action="store_true")
    parser.add_argument("--ensure-task", action="store_true")
    parser.add_argument("--dependencies")
    parser.add_argument("--task-packages")
    parser.add_argument("--show-allowlist", action="store_true")
    args = parser.parse_args()
    if args.show_allowlist:
        print("普通 Python：" + ", ".join(package_names(PYTHON_REQUIREMENTS)))
    elif args.ensure_task:
        if not args.dependencies or not args.task_packages:
            parser.error("--ensure-task 需要 --dependencies 和 --task-packages")
        ensure_task(Path(args.dependencies).resolve(), Path(args.task_packages).resolve())
    elif args.ensure:
        ensure_all()
        print("Python 依赖环境已就绪")
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
