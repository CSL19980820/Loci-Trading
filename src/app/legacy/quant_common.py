"""（已清空）原组合根共用 HTTP 模型与依赖打开器。

内容已按归属拆走，本文件保留仅为标记去向，不要再往里加东西：

- 请求模型 → 各上下文 `src/<context>/api/schemas.py`
- 依赖打开器与「缺依赖 503」映射 → `src/shared/api_deps.py`
- 请求模型基类 `QuantModel` / `UniverseSpecModel` → `src/shared/api_models.py`

拆分原因：这些符号原本让 6 个限界上下文的 api 层反向依赖组合根，任何一个域改
自己的请求字段都要动 `src/app`。
"""
