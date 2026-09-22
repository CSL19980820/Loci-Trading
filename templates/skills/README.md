# Skill 模板

仓库内置技能包，经「从模板同步」安装到 `data/skills/`。

## 模板类型

| 类型 | 识别 | 例子 | 运行方式 |
|---|---|---|---|
| **专属战法** | `strategy_skill: true` / `signal_engine` / `signals` | `market-leader-map`、`limit-up-momentum` | 工坊战法配置 → 盘后选股 + 盘中监测双 Job。`dragon-return` 纸面舱已退役，模板同步会跳过 |
| **可编辑选股指标** | `capability: screen` + `screen.yaml` | — | 指标参数表 + 普通 `screen` 任务；默认参数修改后下次运行生效 |
| **Agent 技能** | 普通 SKILL（无上述战法键） | 暂无内置模板 | 对话 Skill Run，或运维里建 `kind=skill` 任务 |

## 约定：Skill 不写调度

SKILL.md **不写** `schedule` / `cron` / 运行频率。时机由系统 Job 或用户对话决定。
正文里的时间只允许是**取数窗口**（如「最近 60 根日线」）或策略语义时段（如尾盘核价），不是 cron。

## 战法专用 frontmatter

| 键 | 含义 |
|---|---|
| `strategy_skill: true` | 标记为专属战法，走战法配置面板（双 Job） |
| `signal_engine` | 本地量化信号引擎标识；缺省时按 slug 匹配 |
| `signals` | 该战法会产出的信号，取值 `buy_hint` / `sell_hint` / `watch_only` |

## 安装

### 一键同步（推荐）

```powershell
# HTTP（需写权限）
curl -X POST http://127.0.0.1:8000/api/skills/sync-templates

# Python
python -c "from src.ops.application.skills import sync_skills_from_templates; print(sync_skills_from_templates())"
```

前端：**工坊 → 技能** → **「从模板同步战法」**（会同步全部模板，含 Agent 技能）。

打包/便携版从包内 `templates/skills` 解析（与 `PROJECT_ROOT` 一致）。

`yixian-auction`（一线定乾坤·首板次日）已退役。模板源码仍保留作历史研究，但安装、
导入、活动目录、托管任务和自主交易员研究入口都会拒绝该 slug。

部署产物必须带上 `templates/`：容器镜像的 `COPY templates`、发布包的
`Copy-Tree templates`、PyInstaller 的 `loci.spec` 三处都已包含，别在瘦身时删掉。

### 单包安装

```powershell
python -c "from src.ops.application.skills import install_skill_dir; print(install_skill_dir('templates/skills/market-leader-map'))"
```

## 启用战法

安装后进「工坊 → 技能 → 打开战法 → 配置」：

- **LLM 供应商**：必填
- **盘后选股** / **盘中监测**：开关与推送

保存后系统建 `skill:<slug>` 与 `监测·<slug>`。未配置前不跑、不耗悟道配额。

## 启用 Agent 技能

安装后可用：

1. 助手对话挂载该技能，或
2. 运维新建 Job：`kind=skill`，`config.skill=<slug>`，并指定 LLM `provider`
