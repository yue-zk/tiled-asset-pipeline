"""Environment diagnosis stays usable before Pillow is installed."""
from pathlib import Path
import json
import shutil
import subprocess
import sys

PILLOW_VERSION = "12.3.0"


def supported(version):
    return version[0] == 3 and 11 <= version[1] <= 14


def diagnose():
    result = {"python": sys.version.split()[0], "pythonSupported": supported(sys.version_info),
              "pillowRequired": PILLOW_VERSION, "uv": bool(shutil.which("uv")),
              "tiled": bool(shutil.which("tiled")), "ready": False}
    try:
        from PIL import Image, __version__
        from io import BytesIO
        result["pillow"] = __version__
        image = Image.new("RGBA", (2, 2), (7, 11, 17, 0))
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        with Image.open(BytesIO(buffer.getvalue())) as decoded:
            result["pngRoundTrip"] = decoded.convert("RGBA").tobytes() == image.tobytes()
        result["ready"] = result["pythonSupported"] and __version__ == PILLOW_VERSION and result["pngRoundTrip"]
    except (ImportError, OSError) as error:
        result["error"] = str(error)
    return result


def install(workspace, runner=subprocess.run):
    if not supported(sys.version_info):
        raise ValueError("需要 Python 3.11–3.14。请按 references/environment.md 使用 uv 安装 Python 3.12 后重试")
    workspace = Path(workspace).resolve()
    environment = workspace / ".tiled-asset-pipeline" / ".venv"
    for path in [environment, environment.parent]:
        if path.is_symlink():
            raise ValueError("虚拟环境路径不能经过符号链接")
    executable = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    # bin/python may be the normal venv interpreter symlink; its environment directory may not.
    commands = []
    if not executable.exists():
        commands.append([sys.executable, "-m", "venv", str(environment)])
    requirements = Path(__file__).parents[1] / "requirements.txt"
    commands += [[str(executable), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(requirements)],
                 [str(executable), "-B", str(Path(__file__).parents[1] / "pipeline.py"), "doctor"]]
    for command in commands:
        try:
            completed = runner(command, text=True, capture_output=True, check=False)
        except OSError as error:
            raise ValueError(f"环境准备失败: {error}。按 environment.md 修复后重跑 doctor --install") from error
        if completed.returncode:
            raise ValueError(f"环境准备失败（退出码 {completed.returncode}）: {completed.stderr.strip()}\n恢复命令: {json.dumps(command, ensure_ascii=False)}")
    return {"ready": True, "python": str(executable), "environment": str(environment)}
