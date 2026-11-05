# 验证记录

日期：2026-11-05。

## 本地实际执行

环境为 macOS arm64、Python 3.13.4、Pillow 12.3.0。固定依赖已实际安装验证；doctor 返回 ready=true，内存 PNG 编解码保留 RGBA。

`python -B -m unittest discover -s tests -v`：**27 项，26 项通过，1 项 Windows 专项跳过**。全部行为测试使用自行绘制的几何夹具与临时目录，不依赖外部素材：

- 8px 完整 Corner 与 12px 带边距/间距、稀疏 Id 的受限 Edge，使用同一转换器；示例接边像素一致。
- Mixed Wang、同连接变体、缺连接拒绝、零地形边界及未解释可见区域拒绝。
- 完整图章与独立组合成员，RGBA 裁切、循环/单次/状态预览和透明终帧。
- 显式来源部件合成完整动画帧、重叠合成、主体保留及越界拒绝。
- 真实 Tiled 结构组、80 个高分区的无重叠排布、有限地图像素预算与隐藏原图目录。
- 密集展示对象不带非空 `name`，名称保存在自定义属性中；普通格、地形、帧、图章及组合的名称仍可读，移入属性不改变离线像素。
- 原生 TSX/TMX 盘点、margin/spacing、稀疏图片集合、概率及帧时长；补齐描述后直接 build/check。
- 来源或原生元数据变化、坏引用、稀疏 Id 空洞、符号链接、未知文件冲突及用户手改保护。
- 相同输入重复生成不改字节和时间戳，check 不写文件，源目录不改写。
- 环境齐备、缺 Pillow、Python 版本不合适、重复安装、安装失败及无 Python 时已有 uv 的 POSIX 启动分支。

另外实际执行：

- doctor --install 创建独立环境并安装固定依赖，重复执行成功复用。
- PowerShell 启动器在本机 PowerShell 7 中走已有 Python 分支成功，语法解析通过。
- 三套内置示例 corner、edge、composite 可由 `examples/make_examples.py` 复现；临时目录内 build/check 和重复构建均通过。
- JSON Schema 与示例使用本机已有的 Draft202012Validator 验证通过；jsonschema 不属于运行依赖。
- Skill 标准校验和仓库发布检查通过，覆盖元数据、资源、本地链接、JSON 与私有信息标记。

## 开源包范围

仓库仅保留代码、技能、中文文档、CI、测试及三套自制示例。外部测试素材、派生 TMX/TSX/PNG、生产描述、评审图和本机虚拟环境均不属于发布内容。

所有发布示例的 PNG 和描述均可通过自制夹具生成器在临时目录复现并逐字节对比。行为测试在临时目录运行，不在源码包中留下输出。

## 跨平台 CI 与能力边界

2026-11-05 首次 GitHub Actions 已通过 Windows/macOS/Linux × Python 3.11/3.14 六组组合，覆盖行为测试与仓库发布检查。对应源码提交为 `59eca75`，详见 [远程运行记录](https://github.com/yue-zk/tiled-asset-pipeline/actions/runs/42039566278)。

Windows 缺 Python 的原生启动器测试已在 Windows CI 执行通过。官方 uv 安装器及 Python 3.12 的实际下载没有在本机触发，相关分支以隔离桩验证命令和失败处理。

Tiled GUI 试刷、游戏引擎导入、碰撞和导航均未验证。离线渲染不呈现编辑器标签；文件和像素测试不能代替 GUI、艺术语义或用户视觉认可。

## 本地复现

先按 README 准备固定依赖，使用 doctor 返回的 Python：

```text
<python> -B -m unittest discover -s tests -v
<python> -B tools/validate_release.py
```

示例构建与检查命令见 [README](README.md)。本地输入建议放在仓库外或 `private-assets/`，产物放在 `outputs/`；两者与本机环境均已加入 Git 忽略规则。
