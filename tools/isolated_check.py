"""Run a Python check with all mutable application paths in an isolated directory.

Usage: python tools/isolated_check.py tools/import_smoke.py
       python tools/isolated_check.py -m pytest tests/... -q
The child exits before the temporary directory is removed, including on Windows.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    with tempfile.TemporaryDirectory(prefix="loci-check-") as directory:
        data = Path(directory)
        (data / "loci.config.json").write_text("{}", encoding="utf-8")
        (data / "mcp.json").write_text('{"mcpServers":{}}', encoding="utf-8")
        env = os.environ.copy()
        # Strip all inherited deployment overrides before assigning isolated destinations.
        for key in list(env):
            if key.startswith(("PALACE_", "LOCI_")):
                env.pop(key)
        env.update({"LOCI_DATA_DIR": str(data), "LOCI_CONFIG_JSON": str(data / "loci.config.json"),
                    "PALACE_MCP_JSON": str(data / "mcp.json"), "LOCI_IDENTITY_DB": str(data / "identity.db"),
                    "PALACE_ENABLE_SCHEDULER": "0", "PALACE_ENV": "local",
                    "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"})
        completed = subprocess.run([sys.executable, *sys.argv[1:]], cwd=root, env=env, check=False)
        return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
