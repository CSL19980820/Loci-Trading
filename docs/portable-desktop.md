# Loci 桌面便携版

## 打包形态（onedir）

产物是文件夹，不是单文件超级 exe：

```
Loci/
  Loci.exe          # 入口（启动快）
  _internal/        # 依赖与前端静态资源
  data/             # 运行时数据（与 exe 同级，首次自动建）
```

- **为何不用 onefile**：单文件每次启动都要解压到临时目录，体积大时会明显拖慢（尤其含 pandas/numpy）。
- **体积**：打包已排除未使用的 `scipy` 等；主体积仍来自 pandas/numpy/akshare（行情必需）。

默认数据目录：`{exe 所在目录}/data/`。首次可改路径；运维页「数据目录」可再改（需重启）。

```powershell
cd frontend; bun install; bun run build; cd ..
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean loci.spec
# 部署示例
.\scripts\build-loci.ps1 -DeployDir "E:\entertainment_software\Loci"
```

桌面端窗口菜单 / 侧栏底部「帮助」可创建桌面快捷方式。