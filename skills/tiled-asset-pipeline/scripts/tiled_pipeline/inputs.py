"""Source inventory and native TSX metadata extraction, without semantic guesses."""
from pathlib import Path
import io
import math
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw
from .files import (MAX_PIXELS, integer, json_bytes, outside_source, parse_xml,
                    png_bytes, publish, read_bytes, require, safe_path, sha)


def image_from(data):
    with Image.open(io.BytesIO(data)) as opened:
        require(opened.width * opened.height <= MAX_PIXELS and max(opened.size) <= 8192, "图像超过像素或单边尺寸预算")
        require(opened.format == "PNG", "转换输入图片须为 PNG；其他格式先无损导出并记录来源")
        return opened.convert("RGBA")


def reference(root, base, value):
    require(isinstance(value, str) and value and ":" not in value and "\\" not in value,
            "原生引用须为本地相对路径")
    require(not Path(value).is_absolute(), "原生引用不能是绝对路径")
    candidate = base / value
    try:
        rel = candidate.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise ValueError("原生引用越出来源根") from error
    # Check the traversed path before resolving links.
    for path in [candidate, *candidate.parents]:
        if path == root.parent:
            break
        require(not path.is_symlink(), "原生引用经过符号链接")
    path = safe_path(root, rel)
    read_bytes(path)
    return rel


def read_native(root, path, source_ids):
    """Import grid geometry, sparse IDs, probabilities, Wang tags and native timing."""
    data = read_bytes(path)
    xml = parse_xml(data)
    require(xml.tag == "tileset", "需要外部 TSX 图块集")
    width, height = integer(int(xml.get("tilewidth", "0")), 1, 4096), integer(int(xml.get("tileheight", "0")), 1, 4096)
    margin, spacing = integer(int(xml.get("margin", "0"))), integer(int(xml.get("spacing", "0")))
    columns = integer(int(xml.get("columns", "0")))
    count = integer(int(xml.get("tilecount", "0")), 1, 65536)
    declared = {integer(int(tile.get("id", "-1"))): tile for tile in xml.findall("tile")}
    require(len(declared) == len(xml.findall("tile")), "原生 TSX 图块 Id 重复")
    image_node = xml.find("image")
    tiles = []

    def tile_record(local, node, image, rect):
        require(not image.get("trans"), "首版不接受颜色键透明；请显式导出 RGBA PNG")
        rel = reference(root, path.parent, image.get("source"))
        require(rel in source_ids, "TSX 引用非 PNG 图片")
        record = {"id": local, "source": source_ids[rel], "rect": rect,
                  "kind": "tile", "group": "native", "name": f"tile-{local}", "notes": ""}
        if node is not None and node.get("probability") is not None:
            record["probability"] = float(node.get("probability"))
        return record

    if image_node is not None:
        require(columns > 0, "图集 columns 必须大于零")
        for local in range(count):
            x, y = local % columns, local // columns
            tiles.append(tile_record(local, declared.get(local), image_node,
                                     [margin + x * (width + spacing), margin + y * (height + spacing), width, height]))
    else:
        require(columns == 0 and count == len(declared), "图片集合 tilecount 与实际成员不符")
        for local, node in sorted(declared.items()):
            image = node.find("image")
            require(image is not None, "图片集合成员缺少图片")
            rel = reference(root, path.parent, image.get("source"))
            size = image_from(read_bytes(safe_path(root, rel))).size
            tiles.append(tile_record(local, node, image, [0, 0, *size]))
    wangsets = []
    for index, node in enumerate(xml.findall("wangsets/wangset")):
        wangsets.append({"id": f"terrain-{index + 1}", "name": node.get("name", f"Terrain {index+1}"),
                         "type": node.get("type", "mixed"),
                         "colors": [{"name": c.get("name", "Terrain"), "color": c.get("color", "#ffffff"),
                                     "probability": float(c.get("probability", "1"))} for c in node.findall("wangcolor")],
                         "tiles": [{"tile": int(t.get("tileid", "-1")),
                                    "wangid": [int(n) for n in t.get("wangid", "").split(",")]}
                                   for t in node.findall("wangtile")],
                         "requiredPatterns": [], "status": "pending",
                         "evidence": "原生 TSX；尚须核对完整性与语义", "notes": ""})
    terrain_ids = {tile["tile"] for w in wangsets for tile in w["tiles"]}
    for tile in tiles:
        if tile["id"] in terrain_ids:
            tile["kind"] = "terrain"
    animations = []
    for local, node in sorted(declared.items()):
        animation = node.find("animation")
        if animation is not None:
            animations.append({"tile": local, "playback": "loop", "timing": "native",
                               "evidence": "原生 TSX animation/frame.duration",
                               "frames": [{"tile": int(f.get("tileid", "-1")), "durationMs": int(f.get("duration", "0"))}
                                          for f in animation.findall("frame")]})
    offset = xml.find("tileoffset")
    return {"id": "native", "name": xml.get("name", path.stem), "tileSize": [width, height],
            "gridEvidence": f"原生 TSX，margin={margin}, spacing={spacing}；仍须查看原像素", "tiles": tiles,
            "tileOffset": [int(offset.get("x", "0")), int(offset.get("y", "0"))] if offset is not None else [0, 0],
            "wangsets": wangsets, "animations": animations}


def coordinate_preview(image):
    """Pixel-coordinate contact sheet; no grid is selected on the user's behalf."""
    page = Image.new("RGBA", (image.width + 40, image.height + 40), (245, 245, 245, 255))
    page.alpha_composite(image, (40, 40))
    draw = ImageDraw.Draw(page)
    for x in range(0, image.width, 32):
        draw.text((x + 40, 5), str(x), fill="black")
        draw.line((x + 40, 30, x + 40, page.height), fill=(255, 0, 180, 100))
    for y in range(0, image.height, 32):
        draw.text((1, y + 40), str(y), fill="black")
        draw.line((30, y + 40, page.width, y + 40), fill=(255, 0, 180, 100))
    return page


def inspect_sources(source, output):
    source = Path(source).resolve()
    require(source.is_dir(), "来源必须是目录")
    outside_source(source, output)
    entries = list(source.rglob("*"))
    require(not any(p.is_symlink() for p in entries), "来源中存在符号链接")
    paths = sorted(p for p in entries if p.is_file())
    require(len(paths) <= 4096, "来源文件数超过预算，请缩小素材范围")
    for path in paths:
        for parent in [path, *path.relative_to(source).parents]:
            require(not (source / parent).is_symlink(), "来源中存在符号链接")
    images = [p for p in paths if p.suffix.lower() == ".png"]
    require(images, "未发现 PNG 素材")
    sources, artifacts, source_ids = [], {}, {}
    total_pixels = 0
    for number, path in enumerate(images, 1):
        rel, data = path.relative_to(source).as_posix(), read_bytes(path)
        identity = f"image-{number}"
        source_ids[rel] = identity
        image = image_from(data)
        total_pixels += image.width * image.height
        require(total_pixels <= 4 * MAX_PIXELS, "来源总像素超过预算，请分批盘点")
        sources.append({"id": identity, "path": rel, "sha256": sha(data), "status": "pending", "notes": "待实际查看并判定用途"})
        artifacts[f"coordinates/{identity}.png"] = png_bytes(coordinate_preview(image))
    imports, tilesets, embedded = [], [], []
    for path in paths:
        if path.suffix.lower() not in (".tsx", ".tmx"):
            continue
        data = read_bytes(path)
        imports.append({"path": path.relative_to(source).as_posix(), "sha256": sha(data)})
        xml = parse_xml(data)
        if xml.tag == "map":
            for node in xml.findall("tileset"):
                if node.get("source"):
                    reference(source, path.parent, node.get("source"))
                else:
                    embedded.append(path.relative_to(source).as_posix())
        elif xml.tag == "tileset":
            tileset = read_native(source, path, source_ids)
            tileset["id"] = f"native-{len(tilesets)+1}"
            tilesets.append(tileset)
    draft = {"version": 1, "name": "my-materials", "mapTileSize": None,
             "gridEvidence": "", "scope": "", "sources": sources, "imports": imports,
             "groups": [{"id": "native", "name": "待语义归组"}], "tilesets": tilesets,
             "stamps": [], "combinations": [], "terrainExclusions": [],
             "exclusions": [], "pending": ["查看坐标预览，确认网格、地图用途、动画及地形覆盖后移除此项"],
             "nativeNotes": {"embeddedTilesetsNeedExport": sorted(set(embedded))}}
    # No default grid: build refuses null dimensions and pending evidence.
    artifacts["manifest.draft.json"] = json_bytes(draft)
    artifacts["inventory.json"] = json_bytes({"sources": sources, "imports": imports,
                                             "otherFiles": [p.relative_to(source).as_posix() for p in paths
                                                            if p.suffix.lower() not in (".png", ".tsx", ".tmx")]})
    artifacts["README.md"] = ("# 来源盘点\n\ncoordinates/ 是像素坐标预览，粉色线每 32 像素，仅为测量刻度，不代表素材网格。\n\n"
                              "manifest.draft.json 是待分析模板：mapTileSize 未确认，不能直接当作完整描述。\n"
                              "请将草稿复制到盘点目录之外编辑；重跑 inspect 不会覆盖已改的草稿。\n").encode()
    changed = publish(output, artifacts)
    return {"images": len(sources), "nativeTilesets": len(tilesets), "changedFiles": changed,
            "draft": str(Path(output).absolute() / "manifest.draft.json"), "semanticAnalysisRequired": True}
