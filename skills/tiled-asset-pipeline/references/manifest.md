# 素材描述格式 v1

每套素材只有一份生产描述 `manifest.json`。它是源坐标、分类及规则的权威；转换器不自行猜测语义。完整实例见 [Corner](../assets/examples/corner/manifest.json) 与 [Edge](../assets/examples/edge/manifest.json)，机器可读结构见 [manifest.schema.json](manifest.schema.json)。运行时使用标准库执行相应字段与跨引用、像素、覆盖检查，不依赖 JSON Schema 包。

## 顶层字段

| 字段 | 类型/含义 |
| --- | --- |
| version | 固定整数 1 |
| name | 稳定 Id，小写字母开头，允许数字和连字符，最多 64 字符 |
| mapTileSize | `[宽,高]`，真实展示地图网格，不默认 16 |
| gridEvidence | 非空网格依据及候选排除理由 |
| scope | 本次素材用途与整理范围 |
| sources | PNG 来源数组，见下文 |
| imports | 原生 TSX/TMX 的相对路径和 SHA256；变更须重新分析 |
| groups | `{id,name}` 数组；明确用途与结构，颜色/季节是组内变体 |
| tilesets | 图块集数组；不同尺度/用途可分图块集 |
| stamps | 完整多格物件；没有则空数组 |
| combinations | 可复用图章之间的实际搭配；没有则空数组 |
| terrainExclusions | `{family,reason}`：不适用地形族及依据。零地形集时不可为空 |
| exclusions | `{source,rect,reason}`：已收录 PNG 中未使用区域及具体理由 |
| pending | 待核实事项；只有空数组才能正式 build |

生产描述请不要放机器绝对路径、时间戳、密钥或模型参数。文件引用使用 `/` 相对路径，以 `--source` 为根。原生 TSX 内的 `../` 可在根内解析；生产描述不接受 `..`、符号链接或外部 URL。source 与 output 不可互相包含。

来源元素：`{id,path,sha256,status,notes}`。`status` 为 `included` 或 `excluded`；notes 记录用途、许可现状和排除依据。许可未知须如实写未知。每个 included PNG 的可见像素都必须被图块矩形或明确排除区域覆盖；只有目录扫描不算覆盖完成。全透明格不自动视为物件，但可作为真实动画终帧或有证据的地形空域。

## 图块集与 Wang

图块集字段：`id`、`name`、`tileSize:[w,h]`、`gridEvidence`、`tiles`、`wangsets`、`animations`；可选 `tileOffset:[x,y]`，默认 `[0,0]`。

每个 tile：

```json
{"id": 7, "source": "sheet", "rect": [16, 8, 8, 8], "kind": "tile", "group": "building", "name": "屋身左下", "notes": "按完整房屋图章组合", "probability": 1}
```

id 为显式稳定局部编号，0..65535，允许稀疏；source 指来源 Id，rect 是像素 `[x,y,w,h]`。kind 为 `tile`、`terrain` 或 `frame`。矩形不可越界，不自动裁边或缩放；地形格尺寸须等于 tileSize，普通格可以更小。probability 可省略，默认 1；允许 0..10000 的有限数。

主体、火焰、阴影等分开的部件可在描述中合成完整图块或动画帧：用 `size` 和有序 `parts` 替代 `source`、`rect`，两种写法不能混用。每个部件显式提供来源矩形及画布内的 `x,y`，不得越界。空区域保留原 RGBA，重叠区域按 source-over 合成；合成后的像素不能称为某个单独源格的原像素。来源覆盖检查包含全部部件。例：

```json
{"id": 8, "kind": "frame", "group": "light", "name": "完整灯光第1帧", "size": [16,32], "parts": [{"source": "sheet", "rect": [0,0,16,16], "x": 0, "y": 16}, {"source": "sheet", "rect": [16,0,16,16], "x": 0, "y": 0}]}
```

这是来源坐标描述，不是自动识别或补绘；部件的相位、锚点和叠放顺序仍须人工核对。

输出使用标准图片集合 TSX，保留每个显式局部 Id。GID 区间按最大局部 Id+1 分配，不按成员数量假定连续。

Wang 集字段：

```json
{
  "id": "bank", "name": "浅岸", "type": "corner",
  "colors": [{"name": "陆地", "color": "#487840", "probability": 1}],
  "tiles": [{"tile": 7, "wangid": [0,1,0,1,0,0,0,0]}],
  "requiredPatterns": [[0,1,0,1,0,0,0,0], [0,1,0,1,0,1,0,1]],
  "status": "limited", "evidence": "原像素的右上和右下为陆地；原生说明佐证",
  "notes": "只有单侧岸线；缺完整陆地连接，不能用于填充内区"
}
```

八位置固定为上边、右上角、右边、右下角、下边、左下角、左边、左上角；颜色从 1 编号，0 是未指定。corner 的边为零，edge 的角为零，mixed 同时使用。requiredPatterns 必须以来源能力需求为依据，显式列出预期集合，不能根据实际有多少格反推“完整”。

`complete` 要求所有预期连接存在；`limited` 允许缺项，但 notes 必须解释形状限制。所有 terrain 格必须真实登记到 Wang，规则不得引用普通格。多个格可以共享同一连接，表示纹理变体，不能替代缺失连接。工具验证结构与覆盖，不从标签证明原像素接口正确；AI 仍须查看实际源格和样例。

## 完整图章与组合

图章字段：`id`、显式 `tileId`、`name`、`group`、`size:[w,h]`、`anchor:[x,y]`、`footprint:[x,y,w,h]`、`evidence`、`parts`。

`parts` 是有序的 `{tileset,tile,x,y}`，从底层向上层叠加，坐标相对图章画布。未重叠的区域逐字节复制原 RGBA；重叠部分按 source-over 合成，不能声称合成像素等于单个源格。图章不能为空或完全透明。接地点为图章画布内参考，不用于改变 Tiled 的底部左锚点。

组合字段：`id,name,group,size,relation,evidence,members`，可选 notes。members 至少两项 `{stamp,x,y}`；每项引用完整图章，保留独立对象，不将整组截图回填 TMX。relation 说明真实关系，结构检查无法证明自然语言描述正确，必须视觉审阅。

## 动画

图块集内 animations 元素：

```json
{"tile": 0, "playback": "loop", "timing": "native", "evidence": "原生 TSX 每帧 120ms", "frames": [{"tile": 0, "durationMs": 120}, {"tile": 3, "durationMs": 120}]}
```

tile 是代表图块，frames 引用同一图块集内的完整画布。每帧 1..60000ms，最多 256 帧，总预览最长 60 秒；timing 为 native 或 preview，evidence 说明帧序及时间依据。

- loop：标准 TSX animation 与循环 APNG。
- once：不写循环 TSX；APNG 播放一次，行为保留在清单中。
- states：不自动播放，输出依次排列的 PNG 接触表与状态清单。

部件/阴影需先在源 PNG 或完整帧中明确组合；首版不自动解析专有编辑源，也不推断事件状态机。
