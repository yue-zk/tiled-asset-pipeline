"""Manifest-driven compiler. No image interpretation, provider calls or engine code."""
from pathlib import Path
import io
import math
import re
import xml.etree.ElementTree as ET
from PIL import Image, ImageChops, ImageDraw
from .files import (MAX_PIXELS, compare_output, identifier, integer, json_bytes, outside_source,
                    png_bytes, publish, read_bytes, read_json, require, safe_path, sha, xml_bytes)
from .inputs import image_from


def text(value, label):
    require(isinstance(value, str) and value.strip(), f"缺少 {label}")
    return value


def size(value):
    require(isinstance(value, list) and len(value) == 2, "尺寸必须为 [宽,高]")
    result = [integer(n, 1, 4096) for n in value]
    require(result[0] * result[1] <= MAX_PIXELS, "尺寸超过预算")
    return result


def rect(value, image):
    require(isinstance(value, list) and len(value) == 4, "来源矩形必须为 [x,y,w,h]")
    x, y = [integer(n) for n in value[:2]]
    w, h = size(value[2:])
    require(x + w <= image.width and y + h <= image.height, "来源矩形越界")
    return (x, y, x + w, y + h)


def properties(node, values):
    if values:
        parent = ET.SubElement(node, "properties")
        for name, value in sorted(values.items()):
            ET.SubElement(parent, "property", name=name, value=str(value))


def probability(value):
    require(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 10000,
            "概率必须为 0..10000 的有限数值")
    return str(value)


def validate_wang(wang, tiles):
    identifier(wang["id"])
    text(wang["name"], "地形名")
    mode = wang["type"]
    require(mode in ("corner", "edge", "mixed"), "不支持的 Wang 类型")
    require(wang["status"] in ("complete", "limited"), "地形尚未审查")
    text(wang["evidence"], "地形语义证据")
    if wang["status"] == "limited":
        text(wang["notes"], "受限地形的缺项与使用边界")
    colors = wang["colors"]
    require(isinstance(colors, list) and 1 <= len(colors) <= 8, "地形颜色数量必须为 1..8")
    for color in colors:
        text(color["name"], "地形颜色名称")
        require(re.fullmatch(r"#[0-9a-fA-F]{6}", color["color"]), "地形色标须为 #RRGGBB")
        probability(color.get("probability", 1))

    def pattern(value):
        require(isinstance(value, list) and len(value) == 8, "wangid 必须包含八个位置")
        result = tuple(integer(n, 0, len(colors)) for n in value)
        unused = range(0, 8, 2) if mode == "corner" else range(1, 8, 2) if mode == "edge" else ()
        require(not any(result[i] for i in unused), f"{mode} 的未用位置必须为零")
        return result

    required = [pattern(p) for p in wang["requiredPatterns"]]
    require(required and len(set(required)) == len(required), "必须显式声明无重复的预期连接集合")
    seen, actual = set(), set()
    for entry in wang["tiles"]:
        local = integer(entry["tile"], 0, 65535)
        require(local in tiles and local not in seen, "Wang 引用缺失图块或重复图块")
        require(tiles[local]["kind"] == "terrain", "Wang 只能引用明确登记的地形格")
        seen.add(local)
        actual.add(pattern(entry["wangid"]))
    missing = sorted(set(required) - actual)
    require(not actual - set(required), "Wang 实际连接超出预期集合")
    require(wang["status"] != "complete" or not missing, f"完整地形缺少连接: {missing}")
    require(any(float(tiles[n].get("probability", 1)) > 0 for n in seen), "全部地形格概率为零")
    return {"id": wang["id"], "name": wang["name"], "type": mode, "status": wang["status"],
            "patterns": len(actual), "variants": len(seen), "missingPatterns": [list(p) for p in missing],
            "notes": wang.get("notes", ""), "evidence": wang["evidence"]}


def compile_manifest(manifest, source):
    require(type(manifest["version"]) is int and manifest["version"] == 1, "不支持的描述版本")
    identifier(manifest["name"])
    map_size = size(manifest["mapTileSize"])
    text(manifest["gridEvidence"], "原生网格证据")
    text(manifest["scope"], "素材范围")
    require(manifest.get("pending") == [], "素材描述仍有待核实项；不能标为完成")
    require(1 <= len(manifest["sources"]) <= 1024, "来源数量必须为 1..1024")
    artifacts, images, snapshots, source_records = {}, {}, {}, []
    source_pixels = 0
    for record in manifest["sources"]:
        identity = identifier(record["id"])
        require(identity not in images, "来源 Id 重复")
        path = safe_path(source, record["path"])
        data = read_bytes(path)
        require(sha(data) == record["sha256"], f"来源哈希已变化: {record['path']}")
        require(record["status"] in ("included", "excluded"), "来源仍待判定")
        text(record["notes"], "来源用途及许可说明")
        images[identity] = image_from(data)
        source_pixels += images[identity].width * images[identity].height
        require(source_pixels <= 4 * MAX_PIXELS, "来源总像素超过预算，请按素材范围分批整理")
        snapshots[record["path"]] = record["sha256"]
        source_records.append(record)
        if record["status"] == "included":
            artifacts[f"sources/{identity}.png"] = data
    for record in manifest.get("imports", []):
        require(sha(read_bytes(safe_path(source, record["path"]))) == record["sha256"], "原生元数据已变化")
        snapshots[record["path"]] = record["sha256"]
    groups = {}
    for group in manifest["groups"]:
        identity = identifier(group["id"])
        require(identity not in groups, "结构组 Id 重复")
        groups[identity] = text(group["name"], "结构组名称")
    require(groups, "至少需要一个结构组")
    source_status = {r["id"]: r["status"] for r in source_records}
    coverage_masks = {key: Image.new("L", image.size) for key, image in images.items()}
    sets, terrain_reports, total_tiles = {}, [], 0
    pixel_total = 0
    for definition in manifest["tilesets"]:
        key = identifier(definition["id"])
        require(key != "stamps", "图块集 Id stamps 为完整图章保留")
        require(key not in sets, "图块集 Id 重复")
        tile_size = size(definition["tileSize"])
        text(definition["name"], "图块集名称")
        text(definition["gridEvidence"], "图块集网格证据")
        tiles, pixels, animations = {}, {}, {}
        for tile in definition["tiles"]:
            local = integer(tile["id"], 0, 65535)
            require(local not in tiles, "图块 Id 重复")
            require(tile["kind"] in ("tile", "terrain", "frame"), "图块类别必须为 tile/terrain/frame")
            require(tile["group"] in groups, "图块结构组不存在")
            text(tile["name"], "图块名称")
            probability(tile.get("probability", 1))
            if "parts" in tile:
                require("source" not in tile and "rect" not in tile,
                        "合成图块不能同时声明直接裁切")
                image = Image.new("RGBA", tuple(size(tile["size"])))
                require(isinstance(tile["parts"], list) and 1 <= len(tile["parts"]) <= 256,
                        "合成图块须包含 1..256 个来源部件")
                parts = tile["parts"]
            else:
                require("size" not in tile, "直接裁切图块不能声明合成尺寸")
                image = None
                parts = [{"source": tile["source"], "rect": tile["rect"], "x": 0, "y": 0}]
            for part in parts:
                identity = part["source"]
                require(identity in images, "图块来源不存在")
                require(source_status[identity] == "included", "图块引用已排除来源")
                bounds = rect(part["rect"], images[identity])
                crop = images[identity].crop(bounds)
                ImageDraw.Draw(coverage_masks[identity]).rectangle(
                    (bounds[0], bounds[1], bounds[2]-1, bounds[3]-1), fill=255)
                if image is None:
                    image = crop
                else:
                    x, y = integer(part["x"]), integer(part["y"])
                    require(x + crop.width <= image.width and y + crop.height <= image.height,
                            "合成图块部件越界")
                    region = image.crop((x, y, x + crop.width, y + crop.height))
                    if region.getchannel("A").getextrema() == (0, 0):
                        image.paste(crop, (x, y))
                    else:
                        image.alpha_composite(crop, (x, y))
            require(image.width <= tile_size[0] and image.height <= tile_size[1], "图块超过图块集原生尺寸")
            if tile["kind"] == "terrain":
                require(list(image.size) == tile_size, "地形格须与原生网格相同")
            pixels[local], tiles[local] = image, tile
            pixel_total += image.width * image.height
        require(tiles, "不能生成空图块集")
        total_tiles += len(tiles)
        require(total_tiles <= 8192 and pixel_total <= 4 * MAX_PIXELS, "图块数量或像素总量超过预算")
        ids = set()
        wang_ids = set()
        for wang in definition.get("wangsets", []):
            require(wang["id"] not in wang_ids, "地形 Id 重复")
            wang_ids.add(wang["id"])
            report = validate_wang(wang, tiles)
            report["tileset"] = key
            terrain_reports.append(report)
            ids.update(t["tile"] for t in wang["tiles"])
        require(ids == {n for n, t in tiles.items() if t["kind"] == "terrain"}, "地形格与真实 Wang 规则登记不一致")
        for animation in definition.get("animations", []):
            local = integer(animation["tile"], 0, 65535)
            require(local in tiles and local not in animations, "动画引用缺失或重复")
            require(animation["playback"] in ("loop", "once", "states"), "动画模式必须为 loop/once/states")
            require(animation["timing"] in ("native", "preview"), "动画时长必须声明 native 或 preview")
            text(animation["evidence"], "动画帧序及时长证据")
            require(1 <= len(animation["frames"]) <= 256, "动画帧数须为 1..256")
            total = 0
            for frame in animation["frames"]:
                require(frame["tile"] in tiles, "动画帧引用缺失或稀疏 Id 空洞")
                total += integer(frame["durationMs"], 1, 60000)
                require(pixels[frame["tile"]].size == pixels[local].size, "完整动画帧画布必须一致")
            require(total <= 60000, "单条预览动画不能超过 60 秒")
            animations[local] = animation
        offset = definition.get("tileOffset", [0, 0])
        require(isinstance(offset, list) and len(offset) == 2, "tileOffset 需要 [x,y]")
        for n in offset:
            integer(n, -4096, 4096)
        sets[key] = {"definition": definition, "tiles": tiles, "pixels": pixels, "animations": animations,
                     "offset": offset}
    require(sets, "至少需要一个图块集")
    for exclusion in manifest.get("exclusions", []):
        require(exclusion["source"] in images, "排除区域来源不存在")
        text(exclusion["reason"], "区域排除理由")
        bounds = rect(exclusion["rect"], images[exclusion["source"]])
        ImageDraw.Draw(coverage_masks[exclusion["source"]]).rectangle((bounds[0], bounds[1], bounds[2]-1, bounds[3]-1), fill=255)
    for identity, image in images.items():
        if source_status[identity] == "included":
            missing = ImageChops.multiply(image.getchannel("A"), ImageChops.invert(coverage_masks[identity]))
            require(missing.getbbox() is None, f"来源存在未收录且未解释的可见区域: {identity} {missing.getbbox()}")
    if not terrain_reports:
        require(manifest.get("terrainExclusions"), "零地形集必须逐族说明不适用，或记录用户明确只要普通图块")
    for item in manifest.get("terrainExclusions", []):
        text(item["family"], "地形族"); text(item["reason"], "不适用证据")

    # Image collection tilesets preserve explicit local IDs, including sparse IDs.
    for key, dataset in sets.items():
        definition, pixels, tiles = dataset["definition"], dataset["pixels"], dataset["tiles"]
        root = ET.Element("tileset", version="1.10", name=definition["name"],
                          tilewidth=str(max(p.width for p in pixels.values())),
                          tileheight=str(max(p.height for p in pixels.values())), columns="0", tilecount=str(len(tiles)))
        if dataset["offset"] != [0, 0]:
            ET.SubElement(root, "tileoffset", x=str(dataset["offset"][0]), y=str(dataset["offset"][1]))
        for local, tile in sorted(tiles.items()):
            image = pixels[local]
            image_path = f"images/{key}-{local}.png"
            artifacts[image_path] = png_bytes(image)
            node = ET.SubElement(root, "tile", id=str(local), probability=probability(tile.get("probability", 1)))
            metadata = {"名称": tile["name"], "结构组": groups[tile["group"]],
                        "类别": tile["kind"], "使用要点": tile.get("notes", "")}
            animation = dataset["animations"].get(local)
            if animation and animation["playback"] != "loop":
                metadata.update({"播放行为": animation["playback"], "说明": "状态或单次序列见清单；不写为循环 TSX 动画"})
            properties(node, metadata)
            ET.SubElement(node, "image", source="../" + image_path, width=str(image.width), height=str(image.height))
            if animation and animation["playback"] == "loop":
                sequence = ET.SubElement(node, "animation")
                for frame in animation["frames"]:
                    ET.SubElement(sequence, "frame", tileid=str(frame["tile"]), duration=str(frame["durationMs"]))
        if definition.get("wangsets"):
            parent = ET.SubElement(root, "wangsets")
            for wang in definition["wangsets"]:
                node = ET.SubElement(parent, "wangset", name=wang["name"], type=wang["type"], tile="-1")
                properties(node, {"使用要点": wang.get("notes", ""), "能力": wang["status"]})
                for color in wang["colors"]:
                    ET.SubElement(node, "wangcolor", name=color["name"], color=color["color"], tile="-1",
                                  probability=probability(color.get("probability", 1)))
                for item in sorted(wang["tiles"], key=lambda n: n["tile"]):
                    ET.SubElement(node, "wangtile", tileid=str(item["tile"]), wangid=",".join(map(str, item["wangid"])))
        artifacts[f"tilesets/{key}.tsx"] = xml_bytes(root)

    require(len(manifest.get("stamps", [])) <= 1024 and len(manifest.get("combinations", [])) <= 1024,
            "图章或组合数量超过预算")
    stamps, stamp_records = {}, {}
    composed_pixels = 0
    object_ids = set()
    for stamp in manifest.get("stamps", []):
        identity = identifier(stamp["id"])
        require(identity not in stamps and stamp["group"] in groups, "图章重复或结构组缺失")
        integer(stamp["tileId"], 0, 65535)
        require(stamp["tileId"] not in object_ids, "图章 tileId 重复")
        object_ids.add(stamp["tileId"])
        dimensions = size(stamp["size"])
        composed_pixels += dimensions[0] * dimensions[1]
        require(composed_pixels <= 4 * MAX_PIXELS, "图章总像素超过预算")
        canvas = Image.new("RGBA", tuple(dimensions))
        text(stamp["name"], "图章名称")
        text(stamp["evidence"], "完整图章证据")
        rect(stamp["footprint"], canvas)
        require(len(stamp["anchor"]) == 2, "图章须登记接地点")
        require(0 <= integer(stamp["anchor"][0]) <= canvas.width and 0 <= integer(stamp["anchor"][1]) <= canvas.height, "接地点越界")
        require(stamp["parts"], "图章不能为空")
        for part in stamp["parts"]:
            require(part["tileset"] in sets and part["tile"] in sets[part["tileset"]]["pixels"], "图章成员引用缺失")
            image = sets[part["tileset"]]["pixels"][part["tile"]]
            x, y = integer(part["x"]), integer(part["y"])
            require(x + image.width <= canvas.width and y + image.height <= canvas.height, "图章成员越界")
            # Copy unoccupied rectangles verbatim, including transparent RGB; composite only true overlaps.
            region = canvas.crop((x, y, x + image.width, y + image.height))
            if region.getchannel("A").getextrema() == (0, 0):
                canvas.paste(image, (x, y))
            else:
                canvas.alpha_composite(image, (x, y))
        require(canvas.getchannel("A").getbbox() is not None, "全透明占位不能充当完整图章")
        stamps[identity], stamp_records[identity] = canvas, stamp
    combinations = {}
    for combination in manifest.get("combinations", []):
        identity = identifier(combination["id"])
        require(identity not in combinations and combination["group"] in groups, "组合 Id 重复或组缺失")
        text(combination["name"], "组合名称")
        text(combination["relation"], "组合连接/承接/遮挡关系")
        text(combination["evidence"], "组合来源或实际重组证据")
        require(len(combination["members"]) >= 2, "组合须为至少两个可独立复用的完整成员")
        dimensions = size(combination["size"])
        composed_pixels += dimensions[0] * dimensions[1]
        require(composed_pixels <= 4 * MAX_PIXELS, "图章与组合总像素超过预算")
        canvas = Image.new("RGBA", tuple(dimensions))
        for member in combination["members"]:
            require(member["stamp"] in stamps, "组合图章成员缺失")
            image = stamps[member["stamp"]]
            x, y = integer(member["x"]), integer(member["y"])
            require(x + image.width <= canvas.width and y + image.height <= canvas.height, "组合成员越界")
            canvas.alpha_composite(image, (x, y))
        combinations[identity] = canvas

    catalog, placements = make_catalog(manifest, sets, stamps, stamp_records, combinations, groups)
    artifacts["catalog.tmx"] = xml_bytes(catalog)
    if stamps:
        root = ET.Element("tileset", version="1.10", name="完整图章", tilewidth=str(max(i.width for i in stamps.values())),
                          tileheight=str(max(i.height for i in stamps.values())), columns="0", tilecount=str(len(stamps)))
        for identity in sorted(stamps):
            stamp, image = stamp_records[identity], stamps[identity]
            path = f"stamps/{identity}.png"
            artifacts[path] = png_bytes(image)
            node = ET.SubElement(root, "tile", id=str(stamp["tileId"]))
            properties(node, {"名称": stamp["name"], "结构组": groups[stamp["group"]],
                              "接地点": json_bytes(stamp["anchor"]).decode().strip(),
                              "实体占地": json_bytes(stamp["footprint"]).decode().strip()})
            ET.SubElement(node, "image", source="../" + path, width=str(image.width), height=str(image.height))
        artifacts["tilesets/stamps.tsx"] = xml_bytes(root)
    for identity, image in combinations.items():
        artifacts[f"combinations/{identity}.png"] = png_bytes(image)
    # Render the serialized TMX through the same reader used by preview; no parallel layout image.
    from .render import render_bytes
    artifacts["preview.png"] = png_bytes(render_bytes(artifacts, "catalog.tmx"))
    animation_records = []
    for key, dataset in sets.items():
        for local, animation in dataset["animations"].items():
            preview_path = f"animations/{key}-{local}.png"
            frames = [dataset["pixels"][frame["tile"]] for frame in animation["frames"]]
            if animation["playback"] == "states":
                require(frames[0].width * frames[0].height * len(frames) <= MAX_PIXELS, "状态接触表超过预算")
                sheet = Image.new("RGBA", (frames[0].width * len(frames), frames[0].height))
                for n, frame in enumerate(frames):
                    sheet.paste(frame, (n * frame.width, 0))
                artifacts[preview_path] = png_bytes(sheet)
            else:
                buffer = io.BytesIO()
                options = {"save_all": True, "append_images": frames[1:],
                           "duration": [f["durationMs"] for f in animation["frames"]],
                           "loop": 0 if animation["playback"] == "loop" else 1,
                           "disposal": 0, "blend": 0}
                frames[0].save(buffer, format="PNG", **options)
                artifacts[preview_path] = buffer.getvalue()
            animation_records.append({"tileset": key, **animation, "preview": preview_path})
    report = {"version": 1, "name": manifest["name"], "sources": source_records,
              "tilesets": [{"id": k, "localIds": sorted(s["tiles"]), "firstgid": placements[k],
                            "span": max(s["tiles"]) + 1} for k, s in sets.items()],
              "groups": [{"id": g, "name": n, "variants": sum(t["group"] == g for s in sets.values() for t in s["tiles"].values())}
                         for g, n in groups.items()],
              "terrain": terrain_reports, "terrainExclusions": manifest.get("terrainExclusions", []),
              "stamps": manifest.get("stamps", []), "combinations": manifest.get("combinations", []),
              "animations": animation_records, "exclusions": manifest.get("exclusions", []),
              "validation": {"files": "passed", "sourcePixels": "passed", "staticWang": "passed",
                             "visualReview": "not-verified", "tiledGUI": "not-verified", "engine": "not-verified"}}
    artifacts["manifest.json"] = json_bytes(manifest)
    artifacts["coverage.json"] = json_bytes(report)
    notes = ["# 素材使用说明", "", f"素材范围：{manifest['scope']}", "", f"网格依据：{manifest['gridEvidence']}", "",
             "入口：catalog.tmx；图章/地形/动画按结构组分层；目录锁定，空白练习层可绘制。",
             "密集目录对象不使用 Tiled 的 name 标签；选中对象后在属性中查看“名称”，避免总览缩放时标签遮挡素材。",
             "", "地形刷依赖原生规则；缺失形状不会自动补画。下列连接数量不等同于 GUI 刷子已实测。", ""]
    for terrain in terrain_reports:
        notes.append(f"- {terrain['name']}：{terrain['status']}，{terrain['patterns']} 种连接、{terrain['variants']} 个变体；缺项 {terrain['missingPatterns']}。{terrain['notes']}")
    notes += ["", "动画的单次/状态行为见 coverage.json；未知时长标为 preview，不作为原生时序。",
              "", "preview.png 从交付 TMX 渲染。视觉认可、Tiled GUI 与引擎导入均未自动验证。",
              "", "本目录为生成展示板。手工修改后重建会拒绝覆盖；实际场景请另存新地图。",
              "源图许可沿用原作者条件；本工具许可证不改变素材许可。", ""]
    artifacts["README.md"] = "\n".join(notes).encode()
    return artifacts, snapshots, report


def make_catalog(manifest, sets, stamps, stamp_records, combinations, groups):
    mw, mh = manifest["mapTileSize"]
    root = ET.Element("map", version="1.10", orientation="orthogonal", renderorder="right-down",
                      infinite="0", width="1", height="1", tilewidth=str(mw), tileheight=str(mh))
    properties(root, {"用途": "素材展示板", "素材范围": manifest["scope"]})
    first, bases = 1, {}
    for key, dataset in sorted(sets.items()):
        bases[key] = first
        ET.SubElement(root, "tileset", firstgid=str(first), source=f"tilesets/{key}.tsx")
        first += max(dataset["tiles"]) + 1
    if stamps:
        bases["stamps"] = first
        ET.SubElement(root, "tileset", firstgid=str(first), source="tilesets/stamps.tsx")
    layer_id, object_id = 1, 1
    right, bottom = 0, 0
    page_width = max(2048, mw * 32)
    skyline = [(mw, mh, page_width-mw)]

    def layer(parent, tag, name, **attributes):
        nonlocal layer_id
        node = ET.SubElement(parent, tag, id=str(layer_id), name=name, **attributes)
        layer_id += 1
        return node

    def reserve(width, height):
        nonlocal right, bottom, skyline
        extent = width + mw * 2
        candidates = []
        for start, (x, _, _) in enumerate(skyline):
            if x + extent > page_width + mw * 2:
                continue
            covered = [s for s in skyline[start:] if s[0] < x+extent]
            if not covered or covered[-1][0]+covered[-1][2] < x+width:
                continue
            y = max(s[1] for s in covered)
            candidates.append((y+height, y, x))
        require(candidates, "素材分区宽度超出展示板预算")
        _, y, x = min(candidates)
        end = min(page_width, x+extent)
        updated = []
        for sx, sy, sw in skyline:
            if sx+sw <= x or sx >= end:
                updated.append((sx, sy, sw))
            else:
                if sx < x: updated.append((sx, sy, x-sx))
                if sx+sw > end: updated.append((end, sy, sx+sw-end))
        updated.append((x, y+height+mh*2, end-x))
        skyline = sorted(updated)
        right, bottom = max(right, x + width + mw), max(bottom, y + height + mh)
        return x, y

    def objects(parent, name, entries):
        nonlocal object_id
        node = layer(parent, "objectgroup", name, locked="1", draworder="index")
        x, y, row_height, width = 0, 0, 0, 0
        placed = []
        for gid, image_size, label, offset in entries:
            w, h = image_size
            if x + w > max(512, mw * 32) and x:
                y += row_height + mh
                x, row_height = 0, 0
            placed.append((gid, w, h, label, x - offset[0], y + h - offset[1]))
            width = max(width, x + w)
            x += w + mw
            row_height = max(row_height, h)
        ox, oy = reserve(width, y + row_height)
        node.set("offsetx", str(ox)); node.set("offsety", str(oy))
        for gid, w, h, label, x, y in placed:
            child = ET.SubElement(node, "object", id=str(object_id), gid=str(gid),
                                  x=str(x), y=str(y), width=str(w), height=str(h))
            # Dense catalog layers are opened at overview zoom in Tiled.  A name
            # attribute makes Tiled paint a badge over every object, so keep the
            # descriptive label as selectable metadata instead of an overlay.
            properties(child, {"名称": label})
            object_id += 1
        return node

    # A real Tiled group per structural family; flat variants remain selectable in its children.
    for group_id, group_name in groups.items():
        parent = layer(root, "group", group_name, locked="1")
        for kind, name in (("tile", "普通图块"), ("terrain", "地形源格"), ("frame", "动画帧")):
            entries = [(bases[k] + n, s["pixels"][n].size, t["name"], s["offset"])
                       for k, s in sorted(sets.items()) for n, t in sorted(s["tiles"].items())
                       if t["group"] == group_id and t["kind"] == kind]
            if entries:
                objects(parent, name, entries)
        entries = [(bases["stamps"] + s["tileId"], stamps[i].size, s["name"], [0, 0])
                   for i, s in sorted(stamp_records.items()) if s["group"] == group_id]
        if entries:
            objects(parent, "完整图章", entries)
        for key, dataset in sorted(sets.items()):
            for wang in dataset["definition"].get("wangsets", []):
                if not any(dataset["tiles"][t["tile"]]["group"] == group_id for t in wang["tiles"]):
                    continue
                patterns = {}
                for entry in sorted(wang["tiles"], key=lambda t: t["tile"]):
                    if float(dataset["tiles"][entry["tile"]].get("probability", 1)) > 0:
                        patterns.setdefault(tuple(entry["wangid"]), entry["tile"])
                if wang["type"] in ("corner", "edge") and len(wang["colors"]) == 1 and dataset["definition"]["tileSize"] == [mw, mh]:
                    values = [[0] * 8 for _ in range(8)]
                    vertices = {(x, z) for z in range(1, 6) for x in range(1, 6)}
                    # Demonstrate a hole only if the declared set supports all four concave corners.
                    concave = {(0,0,0,1,0,1,0,1), (0,1,0,0,0,1,0,1),
                               (0,1,0,1,0,0,0,1), (0,1,0,1,0,1,0,0)}
                    if wang["type"] == "corner" and concave <= patterns.keys():
                        vertices.remove((3,3))
                    for z in range(7):
                        for x in range(7):
                            if wang["type"] == "corner":
                                code = [0, int((x+1,z) in vertices), 0, int((x+1,z+1) in vertices),
                                        0, int((x,z+1) in vertices), 0, int((x,z) in vertices)]
                            else:
                                code = [int((x,z) in vertices), 0, int((x+1,z) in vertices), 0,
                                        int((x,z+1) in vertices), 0, int((x,z) in vertices), 0]
                            if tuple(code) in patterns:
                                values[z][x] = bases[key] + patterns[tuple(code)]
                    # Straight-only edge sets demonstrate their supported run, avoiding empty samples.
                    if wang["type"] == "edge" and len(patterns) == 1:
                        code = next(iter(patterns))
                        if code == (0,0,1,0,0,0,1,0):
                            values = [[0]*8 for _ in range(8)]
                            values[3][1:6] = [bases[key]+patterns[code]]*5
                        elif code == (1,0,0,0,1,0,0,0):
                            values = [[0]*8 for _ in range(8)]
                            for z in range(1,6): values[z][3] = bases[key]+patterns[code]
                    ox, oy = reserve(8*mw, 8*mh)
                    node = layer(parent, "layer", wang["name"]+" · 连接样例", locked="1",
                                 offsetx=str(ox), offsety=str(oy), width="8", height="8")
                    properties(node, {"使用要点": wang.get("notes", "")})
                    ET.SubElement(node, "data", encoding="csv").text = ",\n".join(",".join(map(str,row)) for row in values)
                else:
                    # Native multi-cell wall modules show a real repeated straight connection.
                    code, local = next(iter(sorted(patterns.items())))
                    image = dataset["pixels"][local]
                    horizontal = code == (0,0,1,0,0,0,1,0)
                    vertical = code == (1,0,0,0,1,0,0,0)
                    if horizontal or vertical:
                        ox, oy = reserve(image.width*(4 if horizontal else 1), image.height*(4 if vertical else 1))
                        node = layer(parent, "objectgroup", wang["name"]+" · 连续直段样例",
                                     locked="1", draworder="index", offsetx=str(ox), offsety=str(oy))
                        for i in range(4):
                            ET.SubElement(node, "object", id=str(object_id), gid=str(bases[key]+local),
                                          x=str(i*image.width if horizontal else 0),
                                          y=str((i+1)*image.height if vertical else image.height),
                                          width=str(image.width), height=str(image.height))
                            object_id += 1
                    else:
                        objects(parent, wang["name"]+" · 规则对应样例",
                                [(bases[key]+n, dataset["pixels"][n].size, str(c), dataset["offset"])
                                 for c,n in sorted(patterns.items())])
        for combination in manifest.get("combinations", []):
            if combination["group"] != group_id:
                continue
            ox, oy = reserve(*combination["size"])
            node = layer(parent, "objectgroup", "组合 · "+combination["name"], locked="1",
                         draworder="index", offsetx=str(ox), offsety=str(oy))
            properties(node, {"关系": combination["relation"], "使用要点": combination.get("notes", "")})
            for member in combination["members"]:
                image, stamp = stamps[member["stamp"]], stamp_records[member["stamp"]]
                child = ET.SubElement(node, "object", id=str(object_id),
                                      gid=str(bases["stamps"]+stamp["tileId"]), x=str(member["x"]),
                                      y=str(member["y"]+image.height), width=str(image.width), height=str(image.height))
                properties(child, {"名称": stamp["name"]})
                object_id += 1
    # Original sources can be toggled individually for reference without replacing editable objects.
    originals = layer(root, "group", "原图素材目录（逐张开启）", visible="0", locked="1")
    for source in manifest["sources"]:
        if source["status"] == "included":
            node = layer(originals, "imagelayer", source["path"], visible="0", locked="1")
            ET.SubElement(node, "image", source=f"sources/{source['id']}.png")
    columns, rows = max(16, math.ceil(right/mw)), math.ceil(bottom/mh)+8
    require(columns*rows*mw*mh <= MAX_PIXELS,
            f"展示地图过大（{columns*mw}×{rows*mh}），请缩小本次素材范围")
    practice = layer(root, "layer", "空白练习", width=str(columns), height=str(rows))
    ET.SubElement(practice, "data", encoding="csv").text = ",".join("0" for _ in range(columns*rows))
    notes = layer(root, "objectgroup", "编号与备注", visible="0", locked="1")
    properties(notes, {"说明": "来源、网格、缺连接与动画时序见 coverage.json / manifest.json"})
    root.set("width", str(columns)); root.set("height", str(rows))
    root.set("nextlayerid", str(layer_id)); root.set("nextobjectid", str(object_id))
    return root, bases


def run(manifest_path, source, output, check=False):
    source = Path(source).resolve()
    require(source.is_dir(), "来源目录不存在")
    outside_source(source, output)
    manifest = read_json(manifest_path)
    artifacts, snapshots, report = compile_manifest(manifest, source)
    # Source bytes are verified again immediately before publication / final check.
    for name, digest in snapshots.items():
        require(sha(read_bytes(safe_path(source, name))) == digest, f"处理期间来源发生变化: {name}")
    if check:
        compare_output(output, artifacts)
        changed = 0
    else:
        changed = publish(output, artifacts)
        compare_output(output, artifacts)
    return {"status": "passed", "command": "check" if check else "build", "changedFiles": changed,
            "output": str(Path(output).absolute()), "terrainSets": len(report["terrain"]),
            "stamps": len(report["stamps"]), "combinations": len(report["combinations"]),
            "animations": len(report["animations"]), "tiledGUI": "not-verified"}
