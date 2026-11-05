"""Strict finite orthogonal TMX reader and native-resolution offline renderer."""
from pathlib import Path, PurePosixPath
import io
import math
import posixpath
from PIL import Image, ImageDraw
from .files import (MAX_PIXELS, integer, parse_xml, png_bytes, read_bytes,
                    require, safe_path)
from .inputs import image_from


def resolve(base, ref):
    require(isinstance(ref, str) and ref and ":" not in ref and "\\" not in ref and not ref.startswith("/"),
            "地图引用必须为本地相对路径")
    result = posixpath.normpath(posixpath.join(posixpath.dirname(base), ref))
    require(result != ".." and not result.startswith("../"), "地图引用越出交付根")
    return result


def number(value, low=-1_000_000, high=1_000_000):
    parsed = float(value)
    require(math.isfinite(parsed) and parsed.is_integer(), "不支持非整数像素坐标")
    return integer(int(parsed), low, high)


def render_bytes(files, map_name, time_ms=0):
    def reader(name):
        require(name in files, f"地图引用缺失: {name}")
        return files[name]
    return render(reader, map_name, time_ms)


def render(reader, map_name, time_ms=0):
    integer(time_ms, 0, 3_600_000)
    root = parse_xml(reader(map_name))
    require(root.tag == "map" and root.get("orientation") == "orthogonal" and root.get("infinite", "0") == "0",
            "首版预览仅支持有限正交地图")
    width, height = integer(int(root.get("width", "0")), 1), integer(int(root.get("height", "0")), 1)
    tw, th = integer(int(root.get("tilewidth", "0")), 1, 4096), integer(int(root.get("tileheight", "0")), 1, 4096)
    require(width * height * tw * th <= MAX_PIXELS, "预览地图超过像素预算")
    background = root.get("backgroundcolor", "#00000000")
    if background.startswith("#") and len(background) == 9:  # Tiled #AARRGGBB
        background = "#" + background[3:] + background[1:3]
    canvas = Image.new("RGBA", (width * tw, height * th), background)
    tilesets, end = [], 1
    for reference in root.findall("tileset"):
        first = integer(int(reference.get("firstgid", "0")), 1, 0x0fffffff)
        require(reference.get("source"), "预览要求外部 TSX")
        name = resolve(map_name, reference.get("source"))
        xml = parse_xml(reader(name))
        require(xml.tag == "tileset", "TSX 根节点错误")
        require(xml.get("objectalignment", "bottomleft") in ("bottomleft", "unspecified"),
                "首版对象预览只支持底部左锚点")
        image_node = xml.find("image")
        sw, sh = integer(int(xml.get("tilewidth", "0")), 1, 4096), integer(int(xml.get("tileheight", "0")), 1, 4096)
        count = integer(int(xml.get("tilecount", "0")), 1, 65536)
        nodes = xml.findall("tile")
        declared = {integer(int(t.get("id", "-1")), 0, 65535): t for t in nodes}
        require(len(declared) == len(nodes), "TSX 图块 Id 重复")
        pixels = {}
        if image_node is not None:
            require(not image_node.get("trans"), "不支持颜色键透明")
            image = image_from(reader(resolve(name, image_node.get("source"))))
            columns = integer(int(xml.get("columns", "0")), 1, 65536)
            spacing, margin = integer(int(xml.get("spacing", "0"))), integer(int(xml.get("margin", "0")))
            for local in range(count):
                x, y = margin + (local % columns) * (sw + spacing), margin + (local // columns) * (sh + spacing)
                require(x + sw <= image.width and y + sh <= image.height, "TSX 图集尺寸不足")
                pixels[local] = image.crop((x, y, x + sw, y + sh))
        else:
            require(int(xml.get("columns", "0")) == 0 and len(declared) == count, "稀疏图片集合数量不符")
            for local, node in declared.items():
                image_node = node.find("image")
                require(image_node is not None and not image_node.get("trans"), "图片集合缺图或颜色键不支持")
                image = image_from(reader(resolve(name, image_node.get("source"))))
                require(image.size == (int(image_node.get("width", image.width)), int(image_node.get("height", image.height))),
                        "TSX 声明尺寸与图片不符")
                require(image.width <= sw and image.height <= sh, "集合图片超过声明尺寸")
                pixels[local] = image
        require(not set(declared) - pixels.keys(), "声明图块 Id 越界")
        span = max(pixels) + 1
        require(first >= end and first + span <= 0x10000000, "GID 区间冲突或溢出")
        end = first + span
        animations = {}
        for local, node in declared.items():
            sequence = node.find("animation")
            if sequence is not None:
                frames = [(integer(int(f.get("tileid", "-1"))), integer(int(f.get("duration", "0")), 1, 60000))
                          for f in sequence.findall("frame")]
                require(1 <= len(frames) <= 256 and all(n in pixels for n, _ in frames), "动画帧引用不存在")
                animations[local] = frames
        offset = xml.find("tileoffset")
        offsets = (number(offset.get("x", "0")), number(offset.get("y", "0"))) if offset is not None else (0, 0)
        tilesets.append((first, pixels, animations, offsets))
    require(tilesets, "地图未引用图块集")

    def tile(gid):
        integer(gid, 1, 0xffffffff)
        require(gid & 0xf0000000 == 0, "首版预览不支持 GID 翻转/旋转标记；请保留原向素材")
        selected = next((s for s in reversed(tilesets) if s[0] <= gid), None)
        require(selected is not None, "GID 无所属图块集")
        first, pixels, animations, offset = selected
        local = gid - first
        require(local in pixels, "GID 越界或引用稀疏 Id 空洞")
        if local in animations:
            frames = animations[local]
            at = time_ms % sum(ms for _, ms in frames)
            for candidate, duration in frames:
                if at < duration:
                    local = candidate
                    break
                at -= duration
        return pixels[local], offset

    ids = set()

    def visit(parent, dx=0, dy=0, visible=True):
        for node in parent:
            if node.tag in ("properties", "tileset"):
                continue
            require(node.tag in ("layer", "objectgroup", "group", "imagelayer"), f"不支持的图层: {node.tag}")
            require(float(node.get("opacity", "1")) == 1, "首版预览不支持图层透明度")
            nx, ny = dx + number(node.get("offsetx", "0")), dy + number(node.get("offsety", "0"))
            shown = visible and node.get("visible", "1") != "0"
            if node.tag == "group":
                visit(node, nx, ny, shown)
            elif node.tag == "layer":
                require(int(node.get("x", "0")) == 0 and int(node.get("y", "0")) == 0, "首版不支持图层格坐标偏移")
                w, h = integer(int(node.get("width", "0")), 1), integer(int(node.get("height", "0")), 1)
                require(w * h <= MAX_PIXELS, "图层过大")
                data = node.find("data")
                require(data is not None and data.get("encoding") == "csv" and not data.get("compression"), "仅支持 CSV 图块层")
                values = [integer(int(n.strip()), 0, 0xffffffff) for n in (data.text or "").split(",") if n.strip()]
                require(len(values) == w * h, "图层数据数量错误")
                for index, gid in enumerate(values):
                    if gid:
                        image, offset = tile(gid)
                        if shown:
                            canvas.alpha_composite(image, (nx + index % w * tw + offset[0], ny + (index // w + 1)*th - image.height + offset[1]))
            elif node.tag == "objectgroup":
                objects = node.findall("object")
                order = node.get("draworder", "topdown")
                require(order in ("topdown", "index"), "未知对象排序")
                if order == "topdown":
                    objects = sorted(objects, key=lambda o: number(o.get("y", "0")))
                for obj in objects:
                    identity = integer(int(obj.get("id", "0")), 1)
                    require(identity not in ids, "对象 Id 重复")
                    ids.add(identity)
                    require(float(obj.get("rotation", "0")) == 0, "首版不支持旋转对象")
                    x, y = nx + number(obj.get("x", "0")), ny + number(obj.get("y", "0"))
                    if obj.get("gid"):
                        image, offset = tile(int(obj.get("gid")))
                        require(number(obj.get("width", str(image.width))) == image.width and number(obj.get("height", str(image.height))) == image.height,
                                "不能缩放图块对象")
                        if shown and obj.get("visible", "1") != "0":
                            canvas.alpha_composite(image, (x + offset[0], y - image.height + offset[1]))
                    elif obj.find("text") is not None:
                        if shown:
                            ImageDraw.Draw(canvas).text((x, y), obj.find("text").text or "", fill="black")
                    else:
                        require(not shown, "不支持可见的非图块对象")
            else:
                image_node = node.find("image")
                require(image_node is not None, "图像层缺失图片")
                image = image_from(reader(resolve(map_name, image_node.get("source"))))
                if shown:
                    canvas.alpha_composite(image, (nx, ny))
    visit(root)
    return canvas


def preview_file(map_path, output, time_ms=0):
    map_path = Path(map_path).absolute()
    root = map_path.parent
    require(not map_path.is_symlink(), "地图不能是符号链接")
    image = render(lambda name: read_bytes(safe_path(root, name)), map_path.name, time_ms)
    data = png_bytes(image)
    output = Path(output)
    require(not output.is_symlink(), "预览输出不能是符号链接")
    if output.exists():
        require(read_bytes(output) == data, "预览路径已有不同内容，请选新路径")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as file:
            file.write(data)
    return {"preview": str(output.absolute()), "size": list(image.size), "source": str(map_path)}
