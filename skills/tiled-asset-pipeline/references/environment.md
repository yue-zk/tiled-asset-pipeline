# 环境检测和自动准备

## 运行条件

AI 宿主须能看图、读写文件和执行本地命令。本工具没有模型 API、密钥、服务端或游戏引擎依赖。Python 支持范围为 3.11–3.14，图像库固定 `Pillow==12.3.0`。初次安装需要网络；环境齐备后转换完全离线。

工具启动阶段不导入 Pillow，因此缺 Pillow 也可以运行 doctor。doctor 的 PNG 读写验证在内存完成，不会写用户素材。

```text
python <skill>/scripts/pipeline.py doctor
python <skill>/scripts/pipeline.py doctor --install --workspace <任务目录>
```

`doctor` 退出码 0 为齐备，1 为需要补齐。`--install` 创建 `<任务目录>/.tiled-asset-pipeline/.venv`，从 PyPI 安装 requirements.txt 并用该解释器重新运行 doctor，返回 Python 的绝对路径。后续命令均使用这个 Python；不用激活环境，也不改 shell 配置。其他命令失败为退出码 2。

## 没有 Python 时

macOS / Linux：

```sh
sh "<skill>/scripts/bootstrap.sh" "<任务目录>"
```

Windows，在已有 PowerShell 中：

```powershell
& "<skill>\scripts\bootstrap.ps1" -Workspace "<任务目录>"
```

脚本先探测 PATH 上的 Python 3.11–3.14。没有合适版本时优先使用已有 uv；uv 也缺失时，下载官方安装脚本至临时文件，安装到用户的 `.local/bin`，不修改 PATH。然后使用 `uv python install 3.12` 和 `uv python find --managed-python 3.12`，继续建立独立环境。

macOS/Linux 下载需要 curl 或 wget。Windows 使用系统 PowerShell 的 Invoke-WebRequest；不自动修改执行策略，不需要安装 PowerShell 7。平台策略阻止脚本执行时报告具体错误，由用户按其管理策略处理，不绕过策略。没有 Python 时也不能直接运行 Python 写的 doctor，因此必须先走上述原生启动脚本。

只有依赖缺失才执行安装。AI 应先说明将下载什么、安装到哪里，再按已授权任务继续；宿主要求授权时遵循其流程。网络故障时保留现有环境，报告失败命令；不可静默更换下载镜像、包版本或使用系统级管理员安装。

## 恢复与可选工具

- 安装 Pillow 失败：检查 pip 报错、网络及 Python 版本；可用返回的虚拟环境 Python 重新执行 `-m pip install -r <skill>/scripts/requirements.txt`。
- venv 不可用：已有 uv 时用 `uv python install 3.12` 准备完整解释器，再重跑 bootstrap。不自动执行 sudo、apt 或修改系统 Python。
- 离线环境缺依赖：请用户提供可信本地发行包或在允许联网后重试；不能声称已自动安装。
- Tiled GUI：仅用户需要打开或试刷时检测和安装，遵循目标系统已有包管理与权限。不影响离线转换。

官方来源：

- uv 安装：https://docs.astral.sh/uv/getting-started/installation/
- uv Python：https://docs.astral.sh/uv/guides/install-python/
- Pillow：https://pypi.org/project/pillow/12.3.0/
