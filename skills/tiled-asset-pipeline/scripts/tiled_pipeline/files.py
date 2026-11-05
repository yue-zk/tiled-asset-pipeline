"""Bounded reads, deterministic serialization and guarded publication."""
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import hashlib
import io
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET

MAX_PIXELS = 16_777_216
MAX_BYTES = 64 * 1024 * 1024
REGISTRY = ".pipeline-output.json"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, low=0, high=MAX_PIXELS):
    require(type(value) is int and low <= value <= high, f"整数超出范围: {value!r}")
    return value


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", value),
            f"Id 须使用小写字母、数字和连字符: {value!r}")
    return value


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def relative(value):
    require(isinstance(value, str) and value and "\\" not in value and ":" not in value,
            f"需要相对 POSIX 路径: {value!r}")
    path = PurePosixPath(value)
    require(not path.is_absolute() and all(p not in (".", "..") for p in value.split("/")),
            f"引用越界或路径不规范: {value}")
    return path


def safe_path(root, value):
    path = Path(root)
    for part in relative(value).parts:
        path = path / part
        require(not path.is_symlink(), f"不接受符号链接: {value}")
    return path


def read_bytes(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), f"文件缺失或为符号链接: {path.name}")
    require(path.stat().st_size <= MAX_BYTES, f"文件超过读取预算: {path.name}")
    return path.read_bytes()


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, f"JSON 键重复: {key}")
            result[key] = value
        return result
    return json.loads(read_bytes(path), object_pairs_hook=pairs,
                      parse_constant=lambda s: (_ for _ in ()).throw(ValueError(f"非法 JSON 数值: {s}")))


def parse_xml(data):
    require(len(data) <= MAX_BYTES and b"<!DOCTYPE" not in data.upper() and b"<!ENTITY" not in data.upper(),
            "不接受 DTD、实体声明或超预算 XML")
    try:
        return ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError(f"XML 语法错误: {error}") from error


def xml_bytes(element):
    ET.indent(element, space="  ")
    return ET.tostring(element, encoding="utf-8", xml_declaration=True) + b"\n"


def png_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=9)
    return buffer.getvalue()


def outside_source(source, output):
    require(not Path(output).is_symlink(), "输出目录不能为符号链接")
    source, output = Path(source).resolve(), Path(output).resolve()
    require(not output.is_relative_to(source), "输出目录必须位于来源目录之外，以保证原素材只读")
    require(not source.is_relative_to(output), "输出目录不能包含来源目录")


@contextmanager
def output_lock(output):
    """One synchronous writer per output; no framework or async runtime needed."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = output.parent / ("." + output.name + ".pipeline.lock")
    require(not lock.is_symlink(), "锁路径不能为符号链接")
    with lock.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def publish(output, artifacts):
    """Preflight every file, stage bytes, replace only changed generated files."""
    output = Path(output).absolute()
    require(REGISTRY not in artifacts, "生成清单名称被占用")
    require(sum(len(data) for data in artifacts.values()) <= 256 * 1024 * 1024, "产物超过总预算")
    for name in artifacts:
        relative(name)
    with output_lock(output):
        registry_path = safe_path(output, REGISTRY)
        previous = read_json(registry_path)["files"] if registry_path.exists() else {}
        for name, digest in previous.items():
            path = safe_path(output, name)
            require(path.is_file() and sha(read_bytes(path)) == digest,
                    f"已有产物被修改或删除，拒绝覆盖: {name}；请使用新输出目录")
        for name, data in artifacts.items():
            path = safe_path(output, name)
            if path.exists() and name not in previous:
                require(path.is_file() and read_bytes(path) == data, f"未知文件冲突: {name}")
        updated = {**artifacts, REGISTRY: json_bytes({"version": 1, "files": {n: sha(b) for n, b in sorted(artifacts.items())}})}
        output.mkdir(parents=True, exist_ok=True)
        changed = 0
        with tempfile.TemporaryDirectory(prefix=".pipeline-stage-", dir=output.parent) as temporary:
            stage = Path(temporary)
            for name, data in updated.items():
                path = safe_path(output, name)
                if path.exists() and read_bytes(path) == data:
                    continue
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            for name in updated:  # registry is committed last
                target = stage / name
                if target.exists():
                    path = safe_path(output, name)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(target, path)
                    changed += 1
            for name in previous.keys() - artifacts.keys():
                safe_path(output, name).unlink()
        return changed


def compare_output(output, artifacts):
    """No locks, directory creation, writes or repairs in check mode."""
    output = Path(output)
    registry = read_json(safe_path(output, REGISTRY))
    expected = {n: sha(data) for n, data in sorted(artifacts.items())}
    require(registry == {"version": 1, "files": expected}, "生成清单与描述不一致，请检查来源或输出")
    for name, data in artifacts.items():
        require(read_bytes(safe_path(output, name)) == data, f"产物不一致: {name}")
