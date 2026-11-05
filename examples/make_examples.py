"""Generate original geometric fixtures; all pixels are authored by this file."""
from pathlib import Path
import hashlib
import json
import sys
from PIL import Image, ImageDraw


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def wang_id(bits, mode):
    result = [0] * 8
    positions = (1, 3, 5, 7) if mode == "corner" else (0, 2, 4, 6)
    for i, position in enumerate(positions):
        result[position] = (bits >> i) & 1
    return result


def make_example(root, variant="corner"):
    root = Path(root)
    source = root / "source"
    source.mkdir(parents=True, exist_ok=True)
    tile, margin, spacing = (8, 0, 0) if variant == "corner" else (12, 2, 1)
    count, columns = (24, 6) if variant == "corner" else (16, 4)
    rows = (count + columns - 1) // columns
    image = Image.new("RGBA", (2*margin+columns*tile+(columns-1)*spacing,
                               2*margin+rows*tile+(rows-1)*spacing), (17, 23, 31, 0))
    rectangles = []
    for index in range(count):
        x, y = margin+(index % columns)*(tile+spacing), margin+(index // columns)*(tile+spacing)
        rectangles.append([x, y, tile, tile])
        patch = Image.new("RGBA", (tile, tile), (176, 133, 81, 255))
        draw = ImageDraw.Draw(patch)
        if index < 16:
            # Original four-quadrant notation, deliberately diagrammatic rather than game artwork.
            corners = [(tile//2, 0, tile-1, tile//2-1), (tile//2, tile//2, tile-1, tile-1),
                       (0, tile//2, tile//2-1, tile-1), (0, 0, tile//2-1, tile//2-1)]
            for bit, bounds in enumerate(corners):
                if index & (1 << bit):
                    draw.rectangle(bounds, fill=(58, 131, 77, 255))
            if variant != "corner":
                draw.rectangle((0, 0, tile-1, tile-1), fill=(176, 133, 81, 255))
                arms = [(tile//3, 0, 2*tile//3-1, 2*tile//3-1),
                        (tile//3, tile//3, tile-1, 2*tile//3-1),
                        (tile//3, tile//3, 2*tile//3-1, tile-1),
                        (0, tile//3, 2*tile//3-1, 2*tile//3-1)]
                for bit, bounds in enumerate(arms):
                    if index & (1 << bit):
                        draw.rectangle(bounds, fill=(58, 131, 77, 255))
        elif index in (16, 17, 18, 19):
            patch = Image.new("RGBA", (tile, tile), (17, 23, 31, 0))
            draw = ImageDraw.Draw(patch)
            draw.rectangle((0, 1, tile-1, tile-1), fill=(174, 86, 65, 255))
            draw.line((0, tile-1, tile-1, tile-1), fill=(84, 47, 40, 255))
        else:
            patch = Image.new("RGBA", (tile, tile), (17, 23, 31, 0))
            if index != 23:
                draw = ImageDraw.Draw(patch)
                draw.ellipse((1, 1, tile-2, tile-2), fill=(255, 160+index, 40, 255))
                draw.point((index % tile, 2), fill=(120, 25, 10, 255))
        image.paste(patch, (x, y))
    image.save(source / "sheet.png")
    digest = hashlib.sha256((source/"sheet.png").read_bytes()).hexdigest()
    mode = "corner" if variant == "corner" else "edge"
    allowed = list(range(16)) if mode == "corner" else [i for i in range(16) if i not in (5, 10)]
    local_ids = {i: i if mode == "corner" else i*2 for i in allowed}
    terrain_tiles = [{"id": local_ids[i], "source": "sheet", "rect": rectangles[i], "kind": "terrain",
                      "group": "ground", "name": f"连接 {i}", "notes": "自制拓扑示意格", "probability": 1}
                     for i in allowed]
    terrain = {"id": "land", "name": "原生地形", "tileSize": [tile, tile],
               "gridEvidence": f"由本生成器显式绘制 {tile}px；margin={margin}, spacing={spacing}",
               "tiles": terrain_tiles, "animations": [], "wangsets": [
                   {"id": "ground", "name": "草土示意", "type": mode,
                    "colors": [{"name": "草地", "color": "#3a834d", "probability": 1}],
                    "tiles": [{"tile": local_ids[i], "wangid": wang_id(i, mode)} for i in allowed],
                    "requiredPatterns": [wang_id(i, mode) for i in range(16)],
                    "status": "complete" if mode == "corner" else "limited",
                    "evidence": "自制四位拓扑定义；仅演示格式，不代表真实素材美术认可",
                    "notes": "" if mode == "corner" else "缺少 5 和 10 的相对双边连接；这些形状不得自动铺设"}]}
    manifest = {"version": 1, "name": "demo-"+variant, "mapTileSize": [tile, tile],
                "gridEvidence": f"自制 {tile}px 网格，不是从图片尺寸整除猜测", "scope": "自制地形与地图物件示例",
                "sources": [{"id": "sheet", "path": "sheet.png", "sha256": digest, "status": "included",
                             "notes": "本仓库自行绘制的几何测试素材；MIT"}], "imports": [],
                "groups": [{"id": "ground", "name": "草土地形"}, {"id": "building", "name": "砖屋构件"},
                           {"id": "signal", "name": "环境灯光"}],
                "tilesets": [terrain], "stamps": [], "combinations": [], "pending": [],
                "terrainExclusions": [], "exclusions": []}
    if mode == "corner":
        pieces = [{"id": i-16, "source": "sheet", "rect": rectangles[i], "kind": "tile", "group": "building",
                   "name": f"屋身构件 {i-16}", "notes": "应按完整房屋图章复用"} for i in range(16, 20)]
        frames = [{"id": (i-20)*3, "source": "sheet", "rect": rectangles[i], "kind": "frame", "group": "signal",
                   "name": f"灯光帧 {i-20}", "notes": "最后一帧完全透明；仍须保留"} for i in range(20, 24)]
        manifest["tilesets"] += [{"id": "building", "name": "屋身", "tileSize": [8, 8], "gridEvidence": "生成器显式 8px 构件",
                                 "tiles": pieces, "wangsets": [], "animations": []},
                                {"id": "signal", "name": "灯光", "tileSize": [8, 8], "gridEvidence": "8px 完整帧画布",
                                 "tiles": frames, "wangsets": [], "animations": [
                                     {"tile": 0, "playback": "loop", "timing": "native", "evidence": "示例定义每帧 120ms",
                                      "frames": [{"tile": t["id"], "durationMs": 120} for t in frames]},
                                     {"tile": 3, "playback": "once", "timing": "preview", "evidence": "示例单次预览速度，非素材原生",
                                      "frames": [{"tile": t["id"], "durationMs": 160} for t in frames]},
                                     {"tile": 6, "playback": "states", "timing": "preview", "evidence": "状态集合，时长仅占位预览",
                                      "frames": [{"tile": t["id"], "durationMs": 100} for t in frames]}]}]
        stamp = {"id": "house", "tileId": 4, "name": "完整砖屋", "group": "building", "size": [16, 16],
                 "anchor": [8, 16], "footprint": [0, 8, 16, 8], "evidence": "四个源格按定义重组，主体完整",
                 "parts": [{"tileset": "building", "tile": i, "x": i % 2*8, "y": i//2*8} for i in range(4)]}
        manifest["stamps"] = [stamp]
        manifest["combinations"] = [{"id": "row-houses", "name": "双屋共边排列", "group": "building", "size": [32, 16],
                                      "relation": "两栋完整屋身的侧边贴合，接地点同高", "evidence": "明确成员坐标的独立重组",
                                      "members": [{"stamp": "house", "x": 0, "y": 0}, {"stamp": "house", "x": 16, "y": 0}]}]
    else:
        manifest["exclusions"] = [{"source": "sheet", "rect": rectangles[i], "reason": "连接 5/10 故意不纳入受限规则示例"} for i in (5, 10)]
    write_json(root / "manifest.json", manifest)
    return root / "manifest.json", source


def make_composite_example(root):
    """Original fixture with a fixed body and independently changing light component."""
    path, source = make_example(root)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["name"] = "demo-composite"
    frames = manifest["tilesets"][2]
    frames["tileSize"] = [8, 16]
    for tile in frames["tiles"]:
        component = {"source": tile.pop("source"), "rect": tile.pop("rect"), "x": 0, "y": 0}
        tile.update(size=[8,16], parts=[
            {"source": "sheet", "rect": manifest["tilesets"][1]["tiles"][0]["rect"], "x": 0, "y": 8},
            component])
    write_json(path, manifest)
    return path, source


if __name__ == "__main__":
    for variant in ("corner", "edge"):
        default = Path(__file__).resolve().parents[1] / "skills/tiled-asset-pipeline/assets/examples"
        manifest, source = make_example(Path(sys.argv[1] if len(sys.argv) > 1 else default) / variant, variant)
        print(manifest)
    manifest, source = make_composite_example(Path(sys.argv[1] if len(sys.argv) > 1 else default) / "composite")
    print(manifest)
