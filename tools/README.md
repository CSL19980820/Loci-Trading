# tools/ · 一次性与辅助脚本

不是产品代码，不参与打包，不被 `src/**` import。

| 脚本 | 用途 |
|---|---|
| `import_smoke.py` | **逐个 import `src/**` 与 `cli/**`**（545 个模块）。比 `compileall` 严格：能抓出「语法正确但缩进错位」的代码。CI 之外的日常关卡就用它 |
| `reindent.py` | 把被写歪前导空格的 Python 源码重排成合法 4 空格缩进。**只改前导空白，不改行内容** |
| `enc2py.py` | 把「缩进编码源」展开成正常 Python。写大文件时把缩进从空白字符变成行首一个字母，从源头消灭走样 |

## 为什么会有后三个

本仓由 AI Agent 大批量生成 Python，**前导空格是最容易写错的一位**。
实测过的三种失败形态，严重度递增：

1. `IndentationError` —— 最好的一种，立刻炸。
2. 语法正确但**块体被拉平**（`if (...)` 的多行条件之后，块体与 `if` 同级）。
3. 语法正确、`import` 也成功，但**整块代码掉进了错误的作用域**——
   `app = create_app()` 被缩进进 `create_app` 的函数体，`compileall` 全绿，
   `python -c "import src.app.main"` 也全绿，只有 uvicorn 启动时报
   `Attribute "app" not found in module`，整个容器起不来。

因此关卡是三层，缺一不可：

```powershell
python tools\reindent.py <file>              # 修（可选）
.\.venv\Scripts\python.exe tools\import_smoke.py   # 每个模块真的 import 一遍
.\.venv\Scripts\python.exe -m pytest tests/ -q   # 语义
```

第 3 类缺陷连 `import_smoke` 都抓不到，只有**断言符号存在**的测试能拦——
见 `tests/shared/test_module_symbols.py`。

## `enc2py.py` 的编码格式

行首一个字符决定这一行怎么展开：

- `A`..`Z`：缩进层级 0..25 → `4 * level` 个空格 + 该行剩余内容
- `|`：原样输出（去掉前缀）。docstring 正文、SQL DDL 等要保留自有缩进的内容用它
- 空行：原样输出

```
Adef greet(name):
B"""打招呼。"""
Bif not name:
Craise ValueError("空名字")
Breturn f"你好，{name}"
```

```powershell
python tools\enc2py.py draft.enc src\somewhere\module.py   # 展开后自动 ast.parse 复核
```

`.enc` 是**临时草稿**，不要留在仓库里。
