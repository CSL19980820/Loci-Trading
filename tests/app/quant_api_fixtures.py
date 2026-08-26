"""组合根 HTTP 测试共用夹具。

原先内联在 `test_quant_api.py`，该文件拆分后由多个测试模块共用。
"""
from __future__ import annotations

import io
import zipfile

SKILL_MANIFEST = """---
name: 测试技能
slug: test-skill
version: 0.1.0
description: 用于接口测试
---

请按步骤执行。
"""


def _skill_zip(extra: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SKILL.md", SKILL_MANIFEST)
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return buffer.getvalue()
