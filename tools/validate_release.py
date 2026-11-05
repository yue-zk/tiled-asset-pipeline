"""Portable release hygiene: runnable without third-party dependencies."""
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/tiled-asset-pipeline"


def main():
    failures = []
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if not path.is_file() or any(p in (".git", ".venv", "outputs", "private-assets", "__pycache__", ".tiled-asset-pipeline") for p in rel.parts):
            continue
        if path.suffix == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError) as error:
                failures.append(f"{rel}: invalid JSON: {error}")
        if path.suffix in (".md", ".py", ".json", ".yaml", ".yml", ".sh", ".ps1"):
            content = path.read_text(encoding="utf-8")
            # Assemble private markers to avoid flagging this validator itself.
            private = ["cn." + "etetet", "asset" + "Usage"]
            if any(s in content for s in private):
                failures.append(f"{rel}: private project marker")
            for prefix in ("/" + "Users/", "/" + "home/"):
                if re.search(re.escape(prefix) + r'''[^/\s"']+/''', content):
                    failures.append(f"{rel}: personal absolute path")
                    break
            if path.suffix == ".md":
                for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", content):
                    if "://" in target or target.startswith("#"):
                        continue
                    destination = target.split("#", 1)[0]
                    if destination and not (path.parent / destination).exists():
                        failures.append(f"{rel}: missing link {target}")
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    if not text.startswith("---\nname: tiled-asset-pipeline\ndescription: ") or text.count("\n---\n") < 1:
        failures.append("Skill frontmatter invalid")
    for name in ("scripts/pipeline.py", "scripts/requirements.txt", "agents/openai.yaml", "references/manifest.schema.json"):
        if not (SKILL / name).is_file():
            failures.append(f"Missing skill resource: {name}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("Release checks passed: metadata, local links, JSON and private-marker scan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
