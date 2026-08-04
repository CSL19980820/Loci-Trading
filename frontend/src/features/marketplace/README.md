# marketplace

本机市场货架：浏览 / 已装 / 发布。货品三类——数据源、量化战法、Skills。

- **入口**：工坊 Tab「市场」（`/quant?tab=market`）；`/market` 重定向至此
- 货架子区用 `?shelf=browse|installed|publish`（避免与工坊 `?tab=` 冲突）；品类 `?kind=`
- 选股工作台只跑已安装；装包与卸载在此完成
- 可编辑的 `formula` 战法从货架直接跳 `/strategy-converter?slug=...`；只读 builtin 继续跳选股台
- 货源只有本机目录；「发布」分区做的是 Skill zip 安装，没有远端 catalog / 上传
- `composables/useMarketCatalog.ts`：合并 `getStrategies` + `getSkills` + `fetchLanesCatalog` + `getAkshareSources`；契约徽标（`badges`）在此统一成中文。数据源显示「工具 N」，未装 akshare 数不出来时回落「N 条线路」
- `components/MarketPanel.vue`：可嵌入工坊（`embedded`）或独立壳
- 货架表列：品类 | 名称 | 信任 | 契约 | 说明 | 操作；点行开 `MarketDetailDialog`，点操作按钮不开弹层
- `components/MarketDetailDialog.vue`：货品详情弹层。数据源额外显示来源地址（`LaneProvider.base_url`，只标出处，不是我们直接请求的地址）与「数据列表」
- `components/SourceDatasetList.vue`：某数据源下挂的接口清单（接口 · 作用 · 入参 · 返回），目录来自本机 akshare 反射，按 `?source=` 过滤
- `components/SourceDatasetDialog.vue`：单个子数据的入参与出参。**出参没有静态元数据**——只能实跑一次读列名，再过 `column_glossary` 得到中英对照；对不上的英文名留空，不猜译。无必填参数的接口开弹层时自动取一次
- 运维不再承载技能包装包；`/ops?tab=skills` → 工坊市场·已装
- 数据源在货架上只读：主动作按钮就叫「数据源」，跳工坊「数据源」（`/quant?tab=sources`）做启停与探测，本页不改开关
