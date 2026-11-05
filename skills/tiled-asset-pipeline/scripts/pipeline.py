#!/usr/bin/env python3
"""Tiled asset pipeline CLI. The doctor branch has no image-library import."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description="通用 Tiled 素材整理；语义由 AI 写入素材描述")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="检测依赖；--install 自动准备独立虚拟环境")
    doctor.add_argument("--install", action="store_true")
    doctor.add_argument("--workspace", type=Path, default=Path.cwd())
    inspect = commands.add_parser("inspect", help="只读盘点来源，输出坐标预览、原生元数据与待分析描述")
    inspect.add_argument("--source", type=Path, required=True)
    inspect.add_argument("--output", type=Path, required=True)
    for name in ("build", "check"):
        command = commands.add_parser(name, help="生成并验证" if name == "build" else "严格只读核验")
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--source", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
    preview = commands.add_parser("preview", help="从实际 TMX 离线渲染，不启动编辑器")
    preview.add_argument("--map", type=Path, required=True)
    preview.add_argument("--output", type=Path, required=True)
    preview.add_argument("--time-ms", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        from tiled_pipeline import environment
        if args.command == "doctor":
            report = environment.install(args.workspace) if args.install else environment.diagnose()
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["ready"] else 1
        diagnosis = environment.diagnose()
        if not diagnosis["ready"]:
            raise ValueError("环境未就绪，请先运行 doctor --install --workspace <任务目录>，再使用返回的 Python 执行")
        if args.command == "inspect":
            from tiled_pipeline.inputs import inspect_sources
            report = inspect_sources(args.source, args.output)
        elif args.command in ("build", "check"):
            from tiled_pipeline.compiler import run
            report = run(args.manifest, args.source, args.output, check=args.command == "check")
        else:
            from tiled_pipeline.render import preview_file
            report = preview_file(args.map, args.output, args.time_ms)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"错误: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
