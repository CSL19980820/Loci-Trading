"""分享包不得带上盘中留存带。

`ADR-014` 把这条列为唯一必须同批改的既有功能。实测发现 `build_share_pack` 是
**白名单**（只拷显式命名的 `palace.db` / `market.db` / `ops.db` / `mcp.json` /
`skills/` / config），从不整目录遍历 `data_dir()`，因此 `intraday/` 与 `.dek`
本来就进不去。本测试把这个性质**锁住**：哪天有人把它改成「拷整个 data 目录再排除
几项」的黑名单写法，这里会红。

为什么值得单独一条测试：`.dek` 一旦跟着密文一起发出去，加密就等于没做。
"""
from __future__ import annotations

import inspect
import unittest

from src.ops.application import share_pack


class SharePackExcludesIntradayTest(unittest.TestCase):
    def test_data_staging_is_an_allow_list_not_a_deny_list(self):
        """源码级断言：不得出现对 data_dir 的整目录遍历/拷贝。"""
        source = inspect.getsource(share_pack)
        self.assertNotIn("copytree(data_dir()", source)
        self.assertNotIn("copytree(\n      data_dir()", source)
        for pattern in ("data_dir().rglob", "data_dir().iterdir", "shutil.copytree(root"):
            self.assertNotIn(pattern, source, f"分享包出现了整目录拷贝：{pattern}")

    def test_intraday_is_not_a_share_pack_option(self):
        """留存带不该出现在可勾选项里——它是本机私有的盘中留痕。"""
        source = inspect.getsource(share_pack)
        self.assertNotIn("intraday", source.lower())

    def test_named_copies_do_not_reach_the_intraday_root(self):
        """白名单里的每个落点都必须是具体文件名或 skills 目录。"""
        source = inspect.getsource(share_pack)
        self.assertIn('data_staging / "palace.db"', source)
        self.assertIn('data_staging / "market.db"', source)
        self.assertIn('data_staging / "ops.db"', source)
        self.assertIn('data_staging / "mcp.json"', source)


if __name__ == "__main__":
    unittest.main()
