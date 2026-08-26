# shared/components/ui

跨 feature 的无业务语义 UI 原子。

| 组件 | 职责 |
|---|---|
| `PageBusy` | 页/面板加载态（转圈 + 文案）；首屏无数据用占位，有内容刷新用 `overlay` |
| `PageTabs` | 页级分区切换（`el-tabs` + 朱印底线）；`v-model` + `items`；可选 `#trailing` 槽（右侧统计/操作）；面板由父级 `v-show` 编排 |
| `SegmentSwitch` | 页头紧凑分段（`el-segmented`）；`v-model` + `items`（name/label/disabled） |
| `BasicForm` | 配置化筛选/表单（对齐 CBasicForm）；`schemas` + `v-model`；见下文 |
| `BasicTable` | 配置化表格（对齐 CBasicTable）；`columns` + `dataSource`/`request`；见下文 |
| `ListToolbar` | 列表工具栏；`config` 按键开关：`create`/`batchDelete`/`import`/`export`；不写或 `false` 不显示，写 `{ onClick, disabled?, loading?, show? }` 即接线 |
| `HeaderStat` | 页头行内读数（标签在上、数值在下），专供 `PageHeader` 的 `stats` 槽；`label`/`value`/`tone`/`lead`。不带卡片壳——页头已有分隔线，再套 `StatCard` 会变「卡中卡」 |
| `EmptyState` / `StatCard` / … | 既有展示原子；`EmptyState` 用自绘「空账页 + 淡印章」替代 EP 默认插图，随主题走 |

页头本身是布局件，在 `shared/components/layout/PageHeader.vue`。

## BasicTable（对齐 CBasicTable）

**模式**

- `request`：`(params) => { list, total }`，组件管分页与加载
- `dataSource` + `pagination` 对象：外部控页；`@current-change` / `@size-change`
- `pagination=false`：无分页（短列表，如复盘中心候选验证表）
- `pagination=true` / `{}`：内置分页（默认 layout 含 jumper）
- `virtualized`：启用 Element Plus `el-table-v2`；与完整数据 `dataSource`、`pagination=false` 搭配用于大表。含动态 slot/formatter、选择、固定列和键盘行焦点；多级表头、展开、列筛选/排序、合并单元格或函数 `rowKey` 会自动回退到 `el-table`

**能力**：`v-model:columns`、`toolbarConfig`（refresh / zoom / custom 列设置）、`mergeField`、`editConfig`+`editRender`、多级表头 `children`、列 `filters`/`filterMethod`、`formatter`/`render`/`slotName`、`offsetHeight`、`cell-click`/`row-click`/`selection-change`

**方法**：`fetch` / `reloadTable` / `restReload` / `setPagination` / `getTableData` / `doLayout` / `setEditRow` / `clearEdit` / `getRowEdit` / `isEditByRow` / `clearSelection` / `getTableRef`

**样式**：表头 `panel-2` + mist、单元格 padding、斑马纹全站统一（全局内置，页面无需再写 `:deep`）。

## BasicForm（对齐 CBasicForm）

**属性**：`schemas`、`v-model`、`rowProps`、`colProps`、`collapse`（仅 `''` 关闭；传 `false`/`true` 均开启）、`label-width` / `size` / `disabled` 及 `el-form` 透传

**schema**：`field` / `label`(可函数) / `component` / `componentProps` / `componentEvents` / `slotName` / `render` / `defaultValue` / `hidden` / `colSpan` / `rules` / `labelWidth`

**组件**：`input`(含 textarea) / `input-number` / `select` / `RadioGroup` / `checkbox` / `CheckboxGroup` / `tree-select` / `date-picker` / `cascader` / `switch`  
（不含参考仓专有 `CUserSelect` / `com-select` / `QIZUploadAttach` 等）

**v-model 同步**：`local` ↔ `modelValue` 用结构相等（`basicFormEqual`），避免 `daterange` 等数组字段因父级每次克隆新引用而与 emit 互相追打卡死页面。

**选项**：`options` 静态，或 `componentProps.request` 接口驱动（`fieldValue`/`fieldLabel`/`immediate`）；字段 ref 上 `getRequest()` 可联动刷新

**方法**：`submit` / `getFieldsValue` / `setFieldsValue` / `resetForm` / `setProps` / `getFormRef` / `getFieldRef`

列表页推荐骨架：

```vue
<div class="page-fill">
  <PageContainer>
    <template #search>
      <BasicForm ref="formRef" v-model="filters" :schemas="schemas" />
      <el-button type="primary" @click="tableRef?.restReload()">查询</el-button>
      <el-button @click="onReset">重置</el-button>
    </template>
    <template #main>
      <BasicTable
        ref="tableRef"
        v-model:columns="columns"
        :request="loadDataTable"
        :pagination="true"
        :toolbar-config="{ refresh: true, custom: true }"
        stripe
      />
    </template>
  </PageContainer>
</div>
```

**视口**：`PageTabs` 优先放在 `.page-scroll` 外。有图/表可吃高度的面板加 `.page-pane`；短文案面板不要硬撑 Sheet。细则见 `frontend/AGENTS.md` §3.7.1。

扩展：新交互原子先确认「去掉业务名词仍成立」再放本目录；只服务单一 bc 的放 `features/<bc>/components`。
