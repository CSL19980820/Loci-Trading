# Codex 在线核验协作流程

本项目默认与 Codex 配合使用。Python 程序负责获取和整理基础数据，Codex 负责在线预览网页、公告和公开资料，并把核验结果写成固定 JSON，再交给程序合并进定稿报告。

## 标准流程

1. 运行程序生成基础数据：

   ```powershell
   .\.venv\Scripts\python.exe analyze.py 002460 --cost 84.363 --shares 600 --formats json,csv
   ```

2. Codex 读取 `summary.json` 和 `ai_context.json`，在线核验以下内容：

   - 证券代码、简称、交易所和证券类型
   - 最新公告、财报披露日期、重大风险提示
   - 官方/权威来源是否与程序数据存在明显差异
   - 行业或政策事件是否需要在报告中提示

3. Codex 按 `examples/online_evidence.sample.json` 生成 `online_evidence.json`。

4. 重新运行程序合并证据并输出定稿：

   ```powershell
   .\.venv\Scripts\python.exe analyze.py 002460 --cost 84.363 --shares 600 --online-evidence online_evidence.json --formats all
   ```

## 证据质量要求

- 每条来源必须包含：标题、URL、来源名称、查询时点、要点摘要。
- 公告、规则、监管结论优先使用交易所、证监会、巨潮资讯、上市公司公告等权威来源。
- 行情、资金流、估值等网页数据必须注明口径可能不同。
- 任何 Codex 推断必须标注为 `inference`，不能伪装成事实。
- 证据 JSON 不得包含 API token、账号、密码或券商交易信息。

## 输出位置

建议把在线证据放在输出目录或项目根目录：

- `output/{code}_{name}_{date}/online_evidence.json`
- 或手工指定 `--online-evidence path\to\online_evidence.json`

报告中的“Codex 在线核验摘要”章节只渲染证据 JSON，不要求程序直接联网。
