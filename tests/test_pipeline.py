from pathlib import Path
import copy
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/tiled-asset-pipeline/scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "examples"))
from make_examples import make_example, wang_id
from tiled_pipeline.compiler import compile_manifest, run
from tiled_pipeline.files import read_json, sha, publish
from tiled_pipeline.inputs import inspect_sources, read_native
from tiled_pipeline.render import render_bytes, preview_file
from tiled_pipeline import environment


def snapshot(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()}


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest, self.source = make_example(self.root / "input")
        self.output = self.root / "output"

    def test_two_layouts_same_compiler_and_limited_terrain(self):
        first = run(self.manifest, self.source, self.output)
        other, source = make_example(self.root / "other", "edge")
        second = run(other, source, self.root / "other-output")
        self.assertEqual(first["terrainSets"], second["terrainSets"])
        self.assertEqual(first["animations"], 3)
        self.assertEqual(second["animations"], 0)
        report = read_json(self.root / "other-output/coverage.json")
        self.assertEqual(len(report["terrain"][0]["missingPatterns"]), 2)
        self.assertEqual(report["terrain"][0]["status"], "limited")
        self.assertEqual(report["tilesets"][0]["span"], 31)

    def test_original_fixture_edges_match_the_declared_corner_and_edge_rules(self):
        for mode in ("corner", "edge"):
            path, source = make_example(self.root / ("seams-"+mode), mode)
            manifest = read_json(path)
            dataset = manifest["tilesets"][0]
            image = Image.open(source / "sheet.png").convert("RGBA")
            pixels = {}
            for tile in dataset["tiles"]:
                x, y, w, h = tile["rect"]
                pixels[tile["id"]] = image.crop((x,y,x+w,y+h))
            for a in dataset["wangsets"][0]["tiles"]:
                for b in dataset["wangsets"][0]["tiles"]:
                    ca, cb = a["wangid"], b["wangid"]
                    horizontal = (ca[1] == cb[7] and ca[3] == cb[5]) if mode == "corner" else ca[2] == cb[6]
                    vertical = (ca[3] == cb[1] and ca[5] == cb[7]) if mode == "corner" else ca[4] == cb[0]
                    pa, pb = pixels[a["tile"]], pixels[b["tile"]]
                    if horizontal:
                        self.assertEqual(pa.crop((pa.width-1,0,pa.width,pa.height)).tobytes(), pb.crop((0,0,1,pb.height)).tobytes())
                    if vertical:
                        self.assertEqual(pa.crop((0,pa.height-1,pa.width,pa.height)).tobytes(), pb.crop((0,0,pb.width,1)).tobytes())

    def test_determinism_read_only_and_unknown_files(self):
        before_source = snapshot(self.source)
        run(self.manifest, self.source, self.output)
        (self.output / "user.txt").write_text("keep")
        before = snapshot(self.output)
        self.assertEqual(run(self.manifest, self.source, self.output)["changedFiles"], 0)
        run(self.manifest, self.source, self.output, check=True)
        self.assertEqual(before, snapshot(self.output))
        self.assertEqual(before_source, snapshot(self.source))

    def test_all_crops_preserve_rgba_and_complete_stamp(self):
        run(self.manifest, self.source, self.output)
        data = read_json(self.manifest)
        with Image.open(self.source / "sheet.png") as source:
            original = source.convert("RGBA")
        for dataset in data["tilesets"]:
            for tile in dataset["tiles"]:
                x, y, w, h = tile["rect"]
                with Image.open(self.output / f"images/{dataset['id']}-{tile['id']}.png") as crop:
                    self.assertEqual(crop.convert("RGBA").tobytes(), original.crop((x, y, x+w, y+h)).tobytes())
        with Image.open(self.output / "stamps/house.png") as stamp:
            self.assertEqual(stamp.size, (16, 16))
        with Image.open(self.output / "animations/signal-0.png") as animation:
            self.assertEqual(animation.n_frames, 4)
            animation.seek(3)
            self.assertIsNone(animation.convert("RGBA").getchannel("A").getbbox())

    def test_render_uses_final_tmx_and_detects_bad_gid(self):
        artifacts, _, _ = compile_manifest(read_json(self.manifest), self.source)
        self.assertEqual(render_bytes(artifacts, "catalog.tmx").tobytes(),
                         Image.open(io.BytesIO(artifacts["preview.png"])).convert("RGBA").tobytes())
        xml = ET.fromstring(artifacts["catalog.tmx"])
        xml.find(".//objectgroup/object").set("gid", "999999")
        artifacts["catalog.tmx"] = ET.tostring(xml)
        with self.assertRaisesRegex(ValueError, "GID"):
            render_bytes(artifacts, "catalog.tmx")

    def test_composite_frames_keep_body_transparent_terminal_and_source_coverage(self):
        manifest = read_json(self.manifest)
        frames = manifest["tilesets"][2]
        originals = copy.deepcopy(frames["tiles"])
        for tile in frames["tiles"]:
            flame = {"source": tile.pop("source"), "rect": tile.pop("rect"), "x": 0, "y": 0}
            tile.update(size=[8, 16], parts=[
                {"source": "sheet", "rect": manifest["tilesets"][1]["tiles"][0]["rect"], "x": 0, "y": 8}, flame])
        frames["tileSize"] = [8, 16]
        artifacts, _, _ = compile_manifest(manifest, self.source)
        source = Image.open(self.source / "sheet.png").convert("RGBA")
        for old, tile in zip(originals, frames["tiles"]):
            result = Image.open(io.BytesIO(artifacts[f"images/signal-{tile['id']}.png"])).convert("RGBA")
            x, y, w, h = old["rect"]
            self.assertEqual(result.crop((0,0,8,8)).tobytes(), source.crop((x,y,x+w,y+h)).tobytes())
            self.assertIsNotNone(result.crop((0,8,8,16)).getchannel("A").getbbox())
        # Source-over is meaningful when a component overlaps an existing opaque body.
        frames["tiles"][0]["parts"][0]["y"] = 0
        artifacts, _, _ = compile_manifest(manifest, self.source)
        result = Image.open(io.BytesIO(artifacts["images/signal-0.png"])).convert("RGBA")
        a = frames["tiles"][0]["parts"][0]["rect"]
        b = originals[0]["rect"]
        expected = Image.new("RGBA", (8,16))
        expected.paste(source.crop((a[0],a[1],a[0]+8,a[1]+8)), (0,0))
        expected.alpha_composite(source.crop((b[0],b[1],b[0]+8,b[1]+8)), (0,0))
        self.assertEqual(result.tobytes(), expected.tobytes())
        for change in (lambda t: t.update(source="sheet"),
                       lambda t: t["parts"][0].update(x=8),
                       lambda t: t["parts"][0].update(source="missing"),
                       lambda t: t.update(parts=[])):
            invalid = copy.deepcopy(manifest)
            change(invalid["tilesets"][2]["tiles"][0])
            with self.assertRaises(ValueError):
                compile_manifest(invalid, self.source)

    def test_catalog_packs_tall_sections_and_keeps_grouped_members_editable(self):
        manifest = read_json(self.manifest)
        original = manifest["combinations"][0]
        manifest["combinations"] = []
        for i in range(80):
            item = copy.deepcopy(original)
            item.update(id=f"tall-{i}", name=f"高分区{i}", size=[64,512])
            manifest["combinations"].append(item)
        artifacts, _, _ = compile_manifest(manifest, self.source)
        xml = ET.fromstring(artifacts["catalog.tmx"])
        group = xml.find("group[@name='砖屋构件']")
        combinations = [g for g in group.findall("objectgroup") if g.get("name").startswith("组合 · ")]
        self.assertEqual(len(combinations), 80)
        self.assertTrue(all(len(g.findall("object")) == 2 for g in combinations))
        bounds = [(int(g.get("offsetx")), int(g.get("offsety")), 64,512) for g in combinations]
        for i, (x,y,w,h) in enumerate(bounds):
            for a,b,c,d in bounds[i+1:]:
                self.assertTrue(x+w <= a or a+c <= x or y+h <= b or b+d <= y)
        self.assertGreater(len({x for x,_,_,_ in bounds}), 1)
        self.assertLessEqual(int(xml.get("width"))*int(xml.get("height"))*64, 16_777_216)
        self.assertIsNotNone(xml.find("group[@name='原图素材目录（逐张开启）']/imagelayer/image"))

    def test_dense_catalog_labels_are_properties_without_visual_overlay_names(self):
        manifest = read_json(self.manifest)
        artifacts, _, _ = compile_manifest(manifest, self.source)
        xml = ET.fromstring(artifacts["catalog.tmx"])
        objects = xml.findall(".//objectgroup/object")
        self.assertTrue(objects)
        self.assertTrue(all(not obj.get("name") for obj in objects))
        for group in manifest["groups"]:
            parent = xml.find(f"group[@name='{group['name']}']")
            for kind, layer_name in (("tile", "普通图块"), ("terrain", "地形源格"), ("frame", "动画帧")):
                expected = [tile["name"] for dataset in sorted(manifest["tilesets"], key=lambda d: d["id"])
                            for tile in sorted(dataset["tiles"], key=lambda t: t["id"])
                            if tile["group"] == group["id"] and tile["kind"] == kind]
                if expected:
                    layer = parent.find(f"objectgroup[@name='{layer_name}']")
                    self.assertEqual([obj.find("./properties/property[@name='名称']").get("value")
                                      for obj in layer.findall("object")], expected)
        stamps = {stamp["id"]: stamp for stamp in manifest["stamps"]}
        for group in manifest["groups"]:
            expected = [stamp["name"] for _, stamp in sorted(stamps.items()) if stamp["group"] == group["id"]]
            if expected:
                layer = xml.find(f"group[@name='{group['name']}']/objectgroup[@name='完整图章']")
                self.assertEqual([obj.find("./properties/property[@name='名称']").get("value")
                                  for obj in layer.findall("object")], expected)
        for combination in manifest["combinations"]:
            layer = xml.find(f".//objectgroup[@name='组合 · {combination['name']}']")
            self.assertEqual([obj.find("./properties/property[@name='名称']").get("value")
                              for obj in layer.findall("object")],
                             [stamps[member["stamp"]]["name"] for member in combination["members"]])

        # The metadata move must not alter the rendered pixels.  Reintroduce
        # legacy names in a copy and compare the same offline render.
        legacy = ET.fromstring(artifacts["catalog.tmx"])
        for obj in legacy.findall(".//objectgroup/object"):
            prop = obj.find("./properties/property[@name='名称']")
            if prop is not None:
                obj.set("name", prop.get("value"))
        legacy_artifacts = dict(artifacts)
        legacy_artifacts["catalog.tmx"] = ET.tostring(legacy, encoding="utf-8")
        self.assertEqual(render_bytes(artifacts, "catalog.tmx"),
                         render_bytes(legacy_artifacts, "catalog.tmx"))

    def test_manual_edit_refused_before_any_write(self):
        run(self.manifest, self.source, self.output)
        (self.output / "catalog.tmx").write_bytes(b"user edited")
        before = snapshot(self.output)
        with self.assertRaisesRegex(ValueError, "修改"):
            run(self.manifest, self.source, self.output)
        with self.assertRaises(ValueError):
            run(self.manifest, self.source, self.output, check=True)
        self.assertEqual(before, snapshot(self.output))

    def test_source_changed_and_broken_reference_no_repair(self):
        run(self.manifest, self.source, self.output)
        before = snapshot(self.output)
        (self.source / "sheet.png").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "哈希"):
            run(self.manifest, self.source, self.output, check=True)
        self.assertEqual(before, snapshot(self.output))

    def test_missing_reference_and_sparse_hole(self):
        run(self.manifest, self.source, self.output)
        (self.output / "images/land-0.png").unlink()
        before = snapshot(self.output)
        with self.assertRaises(ValueError):
            run(self.manifest, self.source, self.output, check=True)
        self.assertEqual(before, snapshot(self.output))
        artifacts, _, report = compile_manifest(read_json(self.manifest), self.source)
        xml = ET.fromstring(artifacts["catalog.tmx"])
        signal = next(t for t in report["tilesets"] if t["id"] == "signal")
        xml.find(".//objectgroup/object").set("gid", str(signal["firstgid"]+1))
        artifacts["catalog.tmx"] = ET.tostring(xml)
        with self.assertRaisesRegex(ValueError, "空洞"):
            render_bytes(artifacts, "catalog.tmx")

    def test_missing_complete_wang_rejected(self):
        manifest = read_json(self.manifest)
        manifest["tilesets"][0]["wangsets"][0]["tiles"].pop()
        with self.assertRaisesRegex(ValueError, "缺少连接"):
            compile_manifest(manifest, self.source)

    def test_mixed_wang_and_variants(self):
        manifest = read_json(self.manifest)
        dataset = manifest["tilesets"][0]
        terrain = dataset["wangsets"][0]
        terrain["type"] = "mixed"
        patterns = []
        for i, entry in enumerate(terrain["tiles"]):
            pattern = [(i >> (j % 4)) & 1 for j in range(8)]
            entry["wangid"] = pattern
            patterns.append(pattern)
        terrain["requiredPatterns"] = patterns
        alternate = copy.deepcopy(dataset["tiles"][1])
        alternate["id"] = 40
        alternate["name"] = "同结构外观变体"
        dataset["tiles"].append(alternate)
        terrain["tiles"].append({"tile": 40, "wangid": patterns[1]})
        _, _, report = compile_manifest(manifest, self.source)
        self.assertEqual(report["terrain"][0]["patterns"], 16)
        self.assertEqual(report["terrain"][0]["variants"], 17)

    def test_pending_grid_path_and_zero_terrain_boundaries(self):
        manifest = read_json(self.manifest)
        for modify in (lambda m: m.update(gridEvidence=""), lambda m: m.update(pending=["unknown"]),
                       lambda m: m["sources"][0].update(path="../escape.png"),
                       lambda m: m["tilesets"][0]["tiles"][0].update(rect=[999, 0, 8, 8])):
            current = copy.deepcopy(manifest)
            modify(current)
            with self.assertRaises(ValueError):
                compile_manifest(current, self.source)
        manifest["tilesets"][0]["wangsets"] = []
        for tile in manifest["tilesets"][0]["tiles"]:
            tile["kind"] = "tile"
        with self.assertRaisesRegex(ValueError, "零地形"):
            compile_manifest(manifest, self.source)
        manifest["terrainExclusions"] = [{"family": "全部地形", "reason": "测试显式仅收普通图块"}]
        compile_manifest(manifest, self.source)

    def test_inspect_refuses_to_claim_grid_and_preserves_source(self):
        before = snapshot(self.source)
        inspect_sources(self.source, self.root / "inventory")
        draft = read_json(self.root / "inventory/manifest.draft.json")
        self.assertTrue(draft["pending"])
        self.assertFalse(draft["gridEvidence"])
        self.assertEqual(before, snapshot(self.source))
        with self.assertRaises(ValueError):
            compile_manifest(draft, self.source)

    def test_unaccounted_visible_regions_are_not_complete(self):
        manifest = read_json(self.manifest)
        manifest["tilesets"][1]["tiles"].pop()
        with self.assertRaisesRegex(ValueError, "未收录"):
            compile_manifest(manifest, self.source)

    def test_refuses_source_output_overlap_and_unknown_collision(self):
        with self.assertRaisesRegex(ValueError, "来源目录之外"):
            run(self.manifest, self.source, self.source / "out")
        self.output.mkdir()
        (self.output / "catalog.tmx").write_text("unrelated map")
        before = snapshot(self.output)
        with self.assertRaisesRegex(ValueError, "未知文件冲突"):
            run(self.manifest, self.source, self.output)
        self.assertEqual(before, snapshot(self.output))

    def test_no_loop_animation_for_once_or_states_and_group_variants_visible(self):
        artifacts, _, report = compile_manifest(read_json(self.manifest), self.source)
        xml = ET.fromstring(artifacts["tilesets/signal.tsx"])
        self.assertIsNotNone(xml.find("tile[@id='0']/animation"))
        self.assertIsNone(xml.find("tile[@id='3']/animation"))
        self.assertIsNone(xml.find("tile[@id='6']/animation"))
        self.assertTrue(all(len(tile.findall("properties")) == 1 for tile in xml.findall("tile")))
        with Image.open(io.BytesIO(artifacts["animations/signal-3.png"])) as animation:
            self.assertEqual(animation.info["loop"], 1)
        with Image.open(io.BytesIO(artifacts["animations/signal-6.png"])) as states:
            self.assertEqual(states.size, (32, 8))

    @unittest.skipIf(os.name == "nt", "Windows 创建 symlink 可能需要额外系统权限")
    def test_symlink_refused(self):
        (self.source / "link.png").symlink_to(self.source / "sheet.png")
        with self.assertRaisesRegex(ValueError, "符号链接"):
            inspect_sources(self.source, self.root / "inventory")

    def test_inspect_native_grid_spacing_and_sparse_ids(self):
        source = self.root / "native"
        source.mkdir()
        image = Image.new("RGBA", (29, 15), (18, 32, 48, 255))
        image.save(source / "grid.png")
        (source / "grid.tsx").write_text('<tileset name="Grid" tilewidth="12" tileheight="12" columns="2" tilecount="2" margin="1" spacing="3"><image source="grid.png" width="29" height="15"/><tile id="0"><animation><frame tileid="0" duration="70"/><frame tileid="1" duration="90"/></animation></tile></tileset>')
        (source / "sparse.tsx").write_text('<tileset name="Sparse" tilewidth="29" tileheight="15" columns="0" tilecount="2"><tile id="2"><image source="grid.png" width="29" height="15"/></tile><tile id="8"><image source="grid.png" width="29" height="15"/></tile></tileset>')
        (source / "entry.tmx").write_text('<map><tileset firstgid="1" source="grid.tsx"/><tileset firstgid="3" source="sparse.tsx"/></map>')
        inspect_sources(source, self.root / "inventory")
        draft = read_json(self.root / "inventory/manifest.draft.json")
        self.assertEqual(draft["tilesets"][0]["tiles"][1]["rect"], [16, 1, 12, 12])
        self.assertEqual(draft["tilesets"][0]["animations"][0]["frames"][1]["durationMs"], 90)
        self.assertEqual([t["id"] for t in draft["tilesets"][1]["tiles"]], [2, 8])
        self.assertEqual(len(draft["imports"]), 3)

    def test_cli_build_check_preview(self):
        for command in ("build", "check"):
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS/"pipeline.py"), command,
                                     "--manifest", str(self.manifest), "--source", str(self.source), "--output", str(self.output)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        preview_file(self.output/"catalog.tmx", self.root/"preview.png")
        self.assertEqual((self.output/"preview.png").read_bytes(), (self.root/"preview.png").read_bytes())

    def test_native_inspection_to_build_without_asset_specific_code(self):
        source = self.root / "native"
        source.mkdir()
        image = Image.new("RGBA", (29, 15), (18, 32, 48, 255))
        image.save(source / "grid.png")
        (source / "grid.tsx").write_text('<tileset name="Grid" tilewidth="12" tileheight="12" columns="2" tilecount="2" margin="1" spacing="3"><image source="grid.png"/><tile id="0" probability="2"><animation><frame tileid="0" duration="70"/><frame tileid="1" duration="90"/></animation></tile></tileset>')
        (source / "entry.tmx").write_text('<map><tileset firstgid="1" source="grid.tsx"/></map>')
        inspect_sources(source, self.root / "inventory")
        draft = read_json(self.root / "inventory/manifest.draft.json")
        draft.update(mapTileSize=[12,12], gridEvidence="原生 TSX 声明", scope="普通图块与原生动画",
                     pending=[], terrainExclusions=[{"family": "当前两格", "reason": "测试明确仅收普通帧，无地形需求"}])
        for record in draft["sources"]:
            record.update(status="included", notes="自制测试 PNG")
        draft["exclusions"] = [{"source": "image-1", "rect": [0,0,29,1], "reason": "图集顶部余边"},
                               {"source": "image-1", "rect": [0,13,29,2], "reason": "图集底部余边"},
                               {"source": "image-1", "rect": [0,1,1,12], "reason": "左边距"},
                               {"source": "image-1", "rect": [13,1,3,12], "reason": "格间距"},
                               {"source": "image-1", "rect": [28,1,1,12], "reason": "右边距"}]
        path = self.root / "native-manifest.json"
        path.write_text(json.dumps(draft), encoding="utf-8")
        result = run(path, source, self.output)
        self.assertEqual(result["animations"], 1)
        run(path, source, self.output, check=True)
        self.assertEqual(ET.parse(self.output/"tilesets/native-1.tsx").find("tile[@id='0']").get("probability"), "2.0")
        (source / "grid.tsx").write_text("changed")
        with self.assertRaisesRegex(ValueError, "元数据"):
            run(path, source, self.output, check=True)


class EnvironmentTests(unittest.TestCase):
    def test_supported_and_missing_python_range(self):
        for version in ((3, 11), (3, 12), (3, 13), (3, 14)):
            self.assertTrue(environment.supported(version))
        for version in ((3, 10), (3, 15), (2, 7)):
            self.assertFalse(environment.supported(version))

    def test_ready_and_missing_pillow(self):
        self.assertTrue(environment.diagnose()["ready"])
        with patch.dict(sys.modules, {"PIL": None}):
            self.assertFalse(environment.diagnose()["ready"])

    def test_install_commands_repeated_and_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls = []
            def runner(command, **kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(command, 0, "", "")
            result = environment.install(temporary, runner)
            self.assertEqual(len(calls), 3)
            self.assertTrue(result["ready"])
            executable = Path(result["python"])
            executable.parent.mkdir(parents=True)
            executable.write_text("")
            calls.clear()
            environment.install(temporary, runner)
            self.assertEqual(len(calls), 2)
            self.assertIn("requirements.txt", calls[0][-1])
            with self.assertRaisesRegex(ValueError, "退出码 9"):
                environment.install(temporary, lambda command, **kw: subprocess.CompletedProcess(command, 9, "", "offline"))
            with patch.object(environment.sys, "version_info", (3, 10)):
                with self.assertRaisesRegex(ValueError, "uv"):
                    environment.install(temporary, runner)

    @unittest.skipIf(os.name == "nt", "POSIX 启动器专项；Windows 使用原生 PS 启动器")
    def test_bootstrap_without_python_uses_uv_and_handles_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            (bin_dir / "dirname").symlink_to("/usr/bin/dirname")
            fake_python = root / "managed-python"
            fake_python.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$BOOT_LOG"\n', encoding="utf-8")
            fake_python.chmod(0o755)
            uv = bin_dir / "uv"
            uv.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$BOOT_LOG"\nif [ "$2" = find ]; then printf "%s\\n" "$BOOT_PY"; fi\n', encoding="utf-8")
            uv.chmod(0o755)
            log = root / "calls"
            env = {**os.environ, "PATH": str(bin_dir), "BOOT_PY": str(fake_python), "BOOT_LOG": str(log)}
            result = subprocess.run(["/bin/sh", str(SCRIPTS/"bootstrap.sh"), str(root)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = log.read_text()
            self.assertIn("python install 3.12", calls)
            self.assertIn("python find --managed-python 3.12", calls)
            self.assertIn("doctor\n--install", calls)
            uv.write_text("#!/bin/sh\nexit 13\n")
            result = subprocess.run(["/bin/sh", str(SCRIPTS/"bootstrap.sh"), str(root)], env=env, capture_output=True)
            self.assertEqual(result.returncode, 13)

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows 原生启动器专项；在 Windows CI 运行")
    def test_windows_bootstrap_without_python_uses_uv(self):
        powershell = shutil.which("pwsh")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            python_stub = root / "managed.cmd"
            python_stub.write_text('@echo off\necho %*>> "%BOOT_LOG%"\nexit /b 0\n')
            uv = bin_dir / "uv.cmd"
            uv.write_text('@echo off\necho %*>> "%BOOT_LOG%"\nif "%2"=="find" echo %BOOT_PY%\nexit /b 0\n')
            log = root / "calls"
            env = {**os.environ, "PATH": str(bin_dir), "BOOT_PY": str(python_stub), "BOOT_LOG": str(log)}
            result = subprocess.run([powershell, "-NoProfile", "-File", str(SCRIPTS/"bootstrap.ps1"), "-Workspace", str(root)],
                                    env=env, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = log.read_text()
            self.assertIn("python install 3.12", calls)
            self.assertIn("doctor --install", calls)
            uv.write_text('@echo off\nexit /b 13\n')
            failed = subprocess.run([powershell, "-NoProfile", "-File", str(SCRIPTS/"bootstrap.ps1"), "-Workspace", str(root)],
                                    env=env, capture_output=True)
            self.assertNotEqual(failed.returncode, 0)


if __name__ == "__main__":
    unittest.main()
