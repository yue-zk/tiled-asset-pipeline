#!/bin/sh
# User-scoped environment preparation for macOS/Linux. No system Python changes.
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
workspace=${1:-"$(pwd)"}
python_bin=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(not(sys.version_info.major == 3 and 11 <= sys.version_info.minor <= 14))' >/dev/null 2>&1; then
        python_bin=$(command -v "$candidate")
        break
    fi
done
if [ -z "$python_bin" ]; then
    if command -v uv >/dev/null 2>&1; then
        uv_bin=$(command -v uv)
    elif [ -x "$HOME/.local/bin/uv" ]; then
        uv_bin="$HOME/.local/bin/uv"
    else
        printf '%s\n' 'Installing uv from https://astral.sh/uv/install.sh into the user directory.' >&2
        installer=$(mktemp)
        trap 'rm -f "$installer"' EXIT HUP INT TERM
        if command -v curl >/dev/null 2>&1; then
            curl --fail --silent --show-error --location https://astral.sh/uv/install.sh -o "$installer"
        elif command -v wget >/dev/null 2>&1; then
            wget -q https://astral.sh/uv/install.sh -O "$installer"
        else
            printf '%s\n' 'Neither curl nor wget is available. See references/environment.md.' >&2
            exit 2
        fi
        UV_NO_MODIFY_PATH=1 UV_INSTALL_DIR="$HOME/.local/bin" sh "$installer"
        uv_bin="$HOME/.local/bin/uv"
    fi
    "$uv_bin" python install 3.12
    python_bin=$("$uv_bin" python find --managed-python 3.12)
fi
exec "$python_bin" -B "$script_dir/pipeline.py" doctor --install --workspace "$workspace"
