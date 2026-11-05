# Tiled 素材与地形集整理

将不同像素素材交给同一个 AI Skill 和转换器，整理成可编辑的 **TSX 图块集、Terrain/Wang 地形集、完整图章、组合示例、环境动画，以及一个展示 TMX**。

中文优先，MIT 开源，文件处理完全本地运行。原素材只读，不需要游戏引擎、远程转换服务或模型 API Key。AI 客户端自身的模型服务与权限由客户端提供。

## 一句话使用

安装后对 AI 说：

> 使用 $tiled-asset-pipeline，把这个目录的像素素材完整整理成 Tiled 图块集和地形集，输出到另一个目录；需要的依赖请自动安装。

AI 会检查环境、盘点并看图、建立素材描述，再调用统一转换器，最后检查并展示预览。已有描述的素材可以直接重新生成。

**“一键”是 AI 编排完整流程。** 转换器不会在缺乏规则时自行理解任意 PNG；影响正确性的网格、连接或帧序歧义仍需澄清。源素材缺角、缺收口时，只交付真实的受限地形集和缺项说明，不伪造完整性。

## 安装 Skill

将仓库的 `skills/tiled-asset-pipeline` **整个目录**复制到 AI 客户端支持的技能目录，包含 scripts、references 和 agents。例如 Codex 的个人技能目录：

```sh
mkdir -p ~/.agents/skills
cp -R skills/tiled-asset-pipeline ~/.agents/skills/
```

Windows PowerShell：

```powershell
$skillRoot = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.agents/skills'
New-Item -ItemType Directory -Force -Path $skillRoot | Out-Null
Copy-Item -Recurse skills/tiled-asset-pipeline $skillRoot
```

已有同名技能时请先比较并保留自己的修改，不盲目覆盖。其他 AI 客户端可以将 SKILL.md 作为任务指引加载，但必须同时能访问完整资源目录。

## 前置条件与自动安装

必需能力：AI 能看图、读写本地文件并执行命令。标准环境为 **Python 3.11–3.14 + Pillow 12.3.0**。Skill 会先检测，缺什么就按授权任务自动准备，不只让用户自行安装。

- 有 Python：创建任务目录下独立的 `.tiled-asset-pipeline/.venv` 并安装固定依赖。
- 没有合适的 Python：复用 uv，或从官方安装器准备用户级 uv，再安装 Python 3.12。
- 已有环境可用：直接使用，不改系统 Python 或其他项目。
- Tiled 编辑器：按需查看或实际试刷；离线生成不需要启动它。

安装需要访问官方发行源；依赖齐备后的转换可断网进行。权限或网络阻止时，AI 应报告实际问题和恢复命令。详见 [环境与恢复](skills/tiled-asset-pipeline/references/environment.md)。

## 命令行快速体验

在仓库根目录执行。先用已有 Python 准备任务环境：

```text
python3 skills/tiled-asset-pipeline/scripts/pipeline.py doctor --install --workspace .
```

无 Python 时运行 `sh skills/tiled-asset-pipeline/scripts/bootstrap.sh .`（macOS/Linux），或 `./skills/tiled-asset-pipeline/scripts/bootstrap.ps1 -Workspace .`（Windows）。

后续使用 doctor 输出的虚拟环境 Python；下面的 `<python>` 均替换为该绝对路径。Windows 通常在 `.tiled-asset-pipeline/.venv/Scripts/python.exe`，macOS/Linux 在 `.tiled-asset-pipeline/.venv/bin/python`。

```text
<python> -B skills/tiled-asset-pipeline/scripts/pipeline.py inspect --source skills/tiled-asset-pipeline/assets/examples/corner/source --output outputs/inventory
<python> -B skills/tiled-asset-pipeline/scripts/pipeline.py build --manifest skills/tiled-asset-pipeline/assets/examples/corner/manifest.json --source skills/tiled-asset-pipeline/assets/examples/corner/source --output outputs/corner
<python> -B skills/tiled-asset-pipeline/scripts/pipeline.py check --manifest skills/tiled-asset-pipeline/assets/examples/corner/manifest.json --source skills/tiled-asset-pipeline/assets/examples/corner/source --output outputs/corner
<python> -B skills/tiled-asset-pipeline/scripts/pipeline.py preview --map outputs/corner/catalog.tmx --output outputs/corner-preview.png
```

第二套示例只更换描述与来源：

```text
<python> -B skills/tiled-asset-pipeline/scripts/pipeline.py build --manifest skills/tiled-asset-pipeline/assets/examples/edge/manifest.json --source skills/tiled-asset-pipeline/assets/examples/edge/source --output outputs/edge
```

| 命令               | 作用                                  |
| ---------------- | ----------------------------------- |
| doctor           | 检测 Python/Pillow、内存 PNG 读写；不安装      |
| doctor --install | 建立独立环境、安装并验证，返回解释器路径                |
| inspect          | 盘点 PNG、提取 TSX/TMX 元数据、生成像素坐标图和待分析草稿 |
| build            | 读取完整描述，生成、渲染并校验成品                   |
| check            | 严格只读重新核验，不修复、不更新时间戳                 |
| preview          | 从实际 TMX 离线渲染；已有不同内容时拒绝覆盖            |

inspect 不替你猜网格，草稿 `mapTileSize` 为 null。请 AI 实际看图并把草稿复制到盘点目录外分析维护；不能将未分析模板当成完成品。

## 成品与示例

```text
catalog.tmx             单入口展示板，含空白练习层
tilesets/*.tsx          图块/地形/图章，显式稳定局部编号
images/*.png            原 RGBA 裁切
sources/*.png           已收录来源原字节快照
stamps/*.png            完整多格物件
combinations/*.png      组合预览；TMX 中成员仍是独立对象
animations/*.png        APNG 动画或状态接触表
manifest.json           当前生产描述
coverage.json           来源、分组、规则、缺项、动画和验证状态
preview.png             从最终 TMX 渲染的整体预览
README.md               中文使用说明
.pipeline-output.json   生成登记，保护用户修改
```

示例使用自行绘制的几何图形，无第三方美术资产：

- `skills/tiled-asset-pipeline/assets/examples/corner`：8px、完整 Corner 16 连接、建筑图章、组合及循环/单次/状态动画。
- `skills/tiled-asset-pipeline/assets/examples/edge`：12px、margin=2、spacing=1、稀疏编号，缺 2 种连接的受限 Edge。
- `skills/tiled-asset-pipeline/assets/examples/composite`：8px 网格、完整 8×16 灯光帧，固定主体与独立光效按明确部件坐标合成。

可用 `python examples/make_examples.py` 重建这三套示例原图和描述。这是自制夹具生成器，不是生产转换器，也不代表 AI 作品或用户认可。

## 支持范围

首版接收 PNG 裁切描述，可从已有外部 TSX 提取图集边距/间距、图片集合稀疏 Id、Wang 和标准动画；TMX 用于盘点素材引用，不迁移旧地图布局。输出是有限正交展示板、图片集合 TSX、CSV 图层和原尺寸对象。

支持 Corner/Edge/Mixed、同连接变体、完整图章、独立组合成员、原生循环与单次/状态预览。未知动画速度如实标为预览速度。

图块也可使用明确来源矩形的有序部件合成完整帧，例如固定灯架与独立火焰。展示地图按实际 Tiled 结构组组织，采用二维分区排布，原图目录默认隐藏，组合仍保留独立可编辑成员。

密集目录对象的说明保存在自定义属性 `名称` 中，不使用画布对象名称标签，避免缩放总览时文字覆盖素材。离线预览不渲染编辑器标签，不能单凭预览认定编辑器显示已验证。

无限/等距/六角地图、压缩数据、GID 翻转、对象旋转/缩放、颜色键、专有编辑源解析等不在首版渲染范围，遇到明确报错。内嵌 tileset 请先导出外部 TSX。具体规则见 [格式与验收](skills/tiled-asset-pipeline/references/format-validation.md)。

## 安全重建与质量边界

- 源目录只读，输出目录放在其外；所有可见来源区域须收录或明确排除。
- 相同输入不重复改写，检查不修改内容或时间戳。
- 产物被手改、删除或与未知文件冲突时拒绝覆盖；保留用户文件，选择新目录重新生成。
- 写入使用同步输出锁、完整预检查和暂存文件。单文件替换为原子操作；异常中断后检查会拒绝不一致产物，请用新目录恢复，不声称整个目录是跨文件原子事务。
- 输出是素材展示板；实际场景另存，不用生成器覆盖手改场景。
- 自动验证不代表视觉认可、GUI 试刷或引擎验证；这些状态分别报告。

## 开发与验证

```text
python -m pip install -r skills/tiled-asset-pipeline/scripts/requirements.txt
python -B -m unittest discover -s tests -v
python -B tools/validate_release.py
```

GitHub Actions 配置 Windows/macOS/Linux × Python 3.11/3.14。未在 CI 实际运行前，配置存在不等于三平台通过。执行记录见 [VALIDATION.md](VALIDATION.md)。

描述规范：[manifest.md](skills/tiled-asset-pipeline/references/manifest.md)。Skill 入口：[SKILL.md](skills/tiled-asset-pipeline/SKILL.md)。

## 许可证

仓库代码、技能文档和自制示例采用 [MIT](LICENSE)。用户提供的素材仍遵守原作者许可，不因工具开源自动变成 MIT。

本地验证时请将第三方素材放在仓库外，或放入已忽略的 `private-assets/`，生成结果放入已忽略的 `outputs/`。公开仓库只保留工具、文档及 `assets/examples/` 下可由夹具生成器复现的自制示例。

本转换器独立编写，参考公开格式，没有附带游戏工程代码、商业素材、历史任务或私有服务接口。

参考：[Tiled 格式](https://doc.mapeditor.org/en/stable/reference/tmx-map-format/)、[地形集](https://doc.mapeditor.org/en/stable/manual/terrain/)、[Codex 技能](https://developers.openai.com/codex/skills/)。
