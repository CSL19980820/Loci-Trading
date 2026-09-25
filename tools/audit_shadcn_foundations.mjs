#!/usr/bin/env node
/** Reproducible source inventory; static reachability is not runtime/UI verification. */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const sourceRoot = path.join(root, 'frontend/src')
const require = createRequire(path.join(root, 'frontend/package.json'))
const { parse: parseSfc } = require('@vue/compiler-sfc')
const { parse: parseTemplate } = require('@vue/compiler-dom')
const ts = require('typescript')
const destination = path.resolve(root, process.argv[2] || 'docs/reviews/2026-09-22-shadcn-system-post-inventory.json')
const normalize = value => value.split(path.sep).join('/')
const relative = value => normalize(path.relative(root, value))
const uiPrefix = 'frontend/src/shared/components/ui/'
// Exact foundation directories. In particular, ui/app and top-level ui/*.vue are NOT excluded.
// This records repository foundations, not a claim that every group is an official registry item.
const foundationGroups = new Set([
  'accordion', 'alert', 'alert-dialog', 'attachment', 'avatar', 'badge', 'bubble', 'button',
  'calendar', 'card', 'checkbox', 'collapsible', 'command', 'dialog', 'drawer', 'dropdown-menu',
  'empty', 'field', 'input', 'input-group', 'item', 'kbd', 'label', 'message', 'message-scroller',
  'native-select', 'number-field', 'pagination', 'popover', 'progress', 'radio-group', 'range-calendar',
  'resizable', 'scroll-area', 'select', 'separator', 'sheet', 'sidebar', 'skeleton', 'sonner', 'spinner',
  'switch', 'table', 'tabs', 'tags-input', 'textarea', 'toggle', 'toggle-group', 'tooltip',
])
const nativeTags = new Set(['button', 'input', 'select', 'textarea', 'table', 'progress'])
const semanticRoles = new Set(['dialog', 'alertdialog', 'listbox', 'option', 'tab', 'tablist', 'tabpanel'])
const legacyNames = new Set(['UiCard', 'UiCardContent', 'UiCardHeader', 'UiCardFooter', 'UiCardTitle',
  'UiCardDescription', 'UiBadge', 'UiField', 'UiSeparator', 'UiSkeleton'])
const kebab = value => value.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase()
const legacyByTag = new Map([...legacyNames].flatMap(name => [[name, name], [kebab(name), name]]))
// MANUAL_NO_REFERENCE_REVIEWS: exact reviewed source fingerprints; edits become pending again.
const reviewedNoReference = {
  "frontend/src/features/admin/components/ModelUsageChart.vue": {
    "sha256": "49a15126b2d0c9f9a56fc1498dd02d998e9017437abd9e2506fbab5b918c6535",
    "reason": "ECharts用量图宿主，保留图表能力与role=img，不以通用控件替代图形。"
  },
  "frontend/src/features/datasource/components/LatencyMeter.vue": {
    "sha256": "7fe69c6c7961e4ab27dbb638337b757f77a33e635931932c806c2915afc611c1",
    "reason": "延迟量程读数，细条是带超量程提示的度量显示，并非任务完成进度或表单交互。"
  },
  "frontend/src/features/ledger/components/ArchiveMobileFacts.vue": {
    "sha256": "71f8b09b03ee0317245e8969acc61a49a998ad9328d3e1c4fc2d288fde6ac17a",
    "reason": "行情事实的原生dl/dt/dd语义列表，仅展示数值。"
  },
  "frontend/src/features/market/components/PulseIndexStrip.vue": {
    "sha256": "f9202bc4078c6a9f42b65714498970346c1b358f243b922bc5fbbada54995987",
    "reason": "指数行情条，展示价格/涨跌/图标；tabindex用于聚焦可滚动区域，不是自制按钮。"
  },
  "frontend/src/features/ops/components/CodeEditor.vue": {
    "sha256": "08035320248b92d8344444151ec9a63e7fb58854a4afe13cf54eedbc5bf6f6ec",
    "reason": "Monaco编辑器及原生selection接口降级；唯一textarea已单独列入保留清单。"
  },
  "frontend/src/features/review/components/WinRateMobileSummary.vue": {
    "sha256": "7c971143691b1a95581e59d8eab2492ea790ca8d68ff4436808f49eb46fe953c",
    "reason": "业务统计数值摘要，无选择/提交/弹层控件。"
  },
  "frontend/src/features/strategy/components/ManualInline.vue": {
    "sha256": "56c648894595683b224076d99f23b0acefc826bc727e0d3c05dea01396615a5f",
    "reason": "安全行内文档渲染，strong/em/code及真实超链接保留HTML语义。"
  },
  "frontend/src/features/strategy/components/QuantBacktestDistBars.vue": {
    "sha256": "a9d1a027bc545c933c6d4724f1f12861ec7d0c38b4d4295887760ed56b98ff15",
    "reason": "收益分布图形，role=img及定制柱图显示，无基础输入交互。"
  },
  "frontend/src/features/strategy/components/QuantBacktestExtremeTape.vue": {
    "sha256": "fc8aaf7472758b03016015b8a7e628f4db74a4ee3e0a18ba0b586eee3fcb8f62",
    "reason": "极端收益事实与RouterLink/StockLink导航；领域图形及真实路由链接保留。"
  },
  "frontend/src/features/strategy/components/ScreenWorkbenchEditor.vue": {
    "sha256": "55b21be5e214898e36f2a4358283bd9305c70d95d9f8d67edbc45ec5057e7f37",
    "reason": "代码编辑器容器与编译状态读数；使用专用CodeEditor，不是通用Textarea遗漏。"
  },
  "frontend/src/shared/components/charts/EquityLineChart.vue": {
    "sha256": "5b904383aa50a402a63e3d47f52e31a3588f2801dca8c4d394aceae74aa75bce",
    "reason": "专用权益曲线图宿主，绘图引擎与业务标注保留。"
  },
  "frontend/src/shared/components/charts/KlineChart.vue": {
    "sha256": "e9e16e81323ad0491cb17037ecfe3f9deca00036371c9075ca415a0df859adb0",
    "reason": "专用K线绘图宿主，图形交互不由通用表单组件替代。"
  },
  "frontend/src/shared/components/charts/Sparkline.vue": {
    "sha256": "722c1c17b8bba19dd79d0c125d2c658788f4b830db6767e3f1fc183d681e045b",
    "reason": "小型SVG趋势图，无基础输入控件。"
  },
  "frontend/src/shared/components/layout/CachedRoutePage.vue": {
    "sha256": "77c187e9a4327e54879c5ae774354bda9125cdd3a9525870ca25553f1d047dad",
    "reason": "动态路由组件与滚动位置恢复容器；实际子页面由运行时传入，静态图不推断其渲染覆盖。"
  },
  "frontend/src/shared/components/layout/MobilePageFrame.vue": {
    "sha256": "b13b1ca33b8a8a55ac9da5ec93ece1b9cd90d51c4df8104c3e8ab3c4f7aa522d",
    "reason": "移动页面布局与滚动/slot容器，交互由插槽内容拥有。"
  },
  "frontend/src/shared/components/layout/MobilePageHeader.vue": {
    "sha256": "3582e91e96d9d3618a3f16e979a927146ba16baacf5da7d71f5feba13fc2f5de",
    "reason": "标题及动作slot布局，交互组件由调用方提供。"
  },
  "frontend/src/shared/components/layout/PageContainer.vue": {
    "sha256": "1e2dadbf8499aac7e22e33386c8c53a9ebba37a598078705cbdbffb1c308f967",
    "reason": "双栏布局和尺寸/滚动约束，非基础交互控件。"
  },
  "frontend/src/shared/components/ui/app/CheckboxChoices.vue": {
    "sha256": "6cea49d5b9f9646abc82d5d348edd0659df10b0668520d7ed517487a616f5901",
    "reason": "复选组字段上下文与role=group容器，实际Checkbox由插槽提供。"
  },
  "frontend/src/shared/components/ui/app/ChoiceGroup.vue": {
    "sha256": "d9bf0e168dac6ec76714ff466b0c9646458bc5325dd31144859c22c989d9da8d",
    "reason": "选择项分组元数据/slot适配，实际控件由父ChoiceField提供。"
  },
  "frontend/src/shared/components/ui/app/ChoiceOption.vue": {
    "sha256": "8c154e4d8df92b39a51c3781fe99fbe51b2d2ef01569ec96f5f4de5f2d4a8194",
    "reason": "选择项元数据/slot适配，实际控件由父ChoiceField提供。"
  },
  "frontend/src/shared/components/ui/app/DataColumn.vue": {
    "sha256": "0e2e670daaf13bc2bcd000d8168ca656b4b0440f822682f53e7b4633c6108b77",
    "reason": "表格列声明元数据，无独立DOM交互；表体由父级数据表实现。"
  },
  "frontend/src/shared/components/ui/app/FormLayout.vue": {
    "sha256": "304286862f59752e97af805ca8674f9176d3d09b5ea724f6d258b7a96eeddbc3",
    "reason": "原生form与表单上下文/校验布局；字段控件来自插槽，不强行把form变成展示组件。"
  },
  "frontend/src/shared/components/ui/Descriptions.vue": {
    "sha256": "bb27e06cbadf0dcbe55c40ca1dc480ad1d6dc0818befb004ed23f3bca7f7650f",
    "reason": "通用原生dl/dt/dd描述列表，无基础交互控件。"
  },
  "frontend/src/shared/components/ui/HeaderStat.vue": {
    "sha256": "ed8c182ffe98aa4d2256f3cee25ec3ac2dec6286e49c1047f2d6cb464ed74366",
    "reason": "标签和值的紧凑读数，无基础交互控件。"
  },
  "frontend/src/shared/components/ui/StockLink.vue": {
    "sha256": "df54d2309432351838766ae273f004bcd1fc9f581e7fe0b881136aaa92a8bfb3",
    "reason": "领域路由链接，保留RouterLink导航契约，不转换成按钮。"
  }
}

function walk(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))
    .flatMap(entry => entry.isDirectory() ? walk(path.join(directory, entry.name))
      : entry.isFile() ? [path.join(directory, entry.name)] : [])
}
const allFiles = walk(sourceRoot) // Filesystem traversal intentionally includes git-ignored source.
const codeFiles = allFiles.filter(file => /\.(vue|[cm]?[jt]sx?)$/.test(file))
const vueFiles = codeFiles.filter(file => file.endsWith('.vue'))
const knownFiles = new Set(codeFiles)
const knownAssets = new Set(allFiles)
function foundation(file) {
  const name = relative(file)
  if (!name.startsWith(uiPrefix)) return null
  const group = name.slice(uiPrefix.length).split('/')[0]
  return foundationGroups.has(group) ? group : null
}
function category(file) {
  if (foundation(file)) return 'primitive'
  const name = relative(file)
  if (name.startsWith('frontend/src/features/')) return 'feature'
  if (name.startsWith('frontend/src/shared/')) return 'shared'
  return 'shell_or_other'
}
function resolveImport(from, specifier) {
  const base = specifier.startsWith('@/') ? path.join(sourceRoot, specifier.slice(2))
    : specifier.startsWith('.') ? path.resolve(path.dirname(from), specifier) : null
  if (!base) return null
  return [base, ...['.ts', '.tsx', '.js', '.jsx', '.vue'].map(ext => base + ext),
    ...['index.ts', 'index.tsx', 'index.js', 'index.vue'].map(name => path.join(base, name))]
    .find(candidate => knownAssets.has(candidate)) || null
}
const nodes = new Map(codeFiles.map(file => [file, {
  file: relative(file), kind: category(file), foundation_group: foundation(file),
  test_source: /(?:\.|\/)(test|spec)(?:\.|\/)/.test(relative(file)),
  imports: [], unresolved_local_imports: [], native_controls: [], manual_semantics: [],
  legacy_imports: [], legacy_template_usages: [], dynamic_components: [], parse_errors: [],
}]))
const graph = new Map(codeFiles.map(file => [file, new Set()]))

function retention(file, tag, attributes = {}) {
  if (tag === 'input' && attributes.type === 'file') return {
    decision: 'retain', reason: '浏览器文件/目录选择能力；可由组件按钮触发，不能用普通文本Input替代。',
    hidden_evidence: attributes.hidden !== undefined ? 'hidden attribute'
      : attributes.class === 'assistant-sender__file' && /\.assistant-sender__file\s*\{[^}]*display:\s*none/s.test(fs.readFileSync(path.join(root, 'frontend/src/features/ai/components/AssistantSenderDock.css'), 'utf8'))
        ? 'AssistantSenderDock.css: .assistant-sender__file { display: none }' : 'not established by this scan',
  }
  if (relative(file) === 'frontend/src/features/ops/components/CodeEditor.vue' && tag === 'textarea') return {
    decision: 'retain', reason: 'Monaco移动端/加载失败降级编辑器；nativeEditor依赖selection/setSelectionRange等原生接口。',
  }
  if (foundation(file)) return { decision: 'foundation_implementation', reason: '精确命中基础组件目录；组件实现中的原生元素不算业务遗漏。' }
  return { decision: 'review', reason: '只记录源码候选；需判断业务语义、可访问性与组件契约，不能仅按原生标签判错。' }
}
function addImport(file, specifier, line, form, names = []) {
  const record = nodes.get(file)
  const resolved = resolveImport(file, specifier)
  record.imports.push({ source: specifier, resolved: resolved ? relative(resolved) : null, line, form, names, asset: Boolean(resolved && !knownFiles.has(resolved)) })
  if (resolved && knownFiles.has(resolved)) graph.get(file).add(resolved)
  else if (!resolved && (specifier.startsWith('@/') || specifier.startsWith('.'))) record.unresolved_local_imports.push({ source: specifier, line })
  for (const name of names) {
    if (legacyNames.has(name.imported) || legacyNames.has(name.local)
      || /\/(UiCard(?:Content|Header|Footer|Title|Description)?|UiBadge|UiField|UiSeparator|UiSkeleton)\.vue$/.test(specifier)) {
      record.legacy_imports.push({ source: specifier, line, ...name })
    }
  }
}
function analyzeScript(file, code, baseLine = 1, language = 'ts') {
  const record = nodes.get(file)
  const source = ts.createSourceFile(file, code, ts.ScriptTarget.Latest, true,
    language === 'tsx' ? ts.ScriptKind.TSX : language === 'jsx' ? ts.ScriptKind.JSX : ts.ScriptKind.TS)
  const lineOf = node => baseLine + source.getLineAndCharacterOfPosition(node.getStart(source)).line
  const stringValue = node => node && (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) ? node.text : undefined
  const renderFunctions = new Set(['h', 'createVNode', 'createElementVNode'])
  for (const statement of source.statements) {
    if (ts.isImportDeclaration(statement) && statement.moduleSpecifier.text === 'vue') {
      const bindings = statement.importClause?.namedBindings
      if (bindings && ts.isNamedImports(bindings)) for (const item of bindings.elements) {
        if (renderFunctions.has(item.propertyName?.text || item.name.text)) renderFunctions.add(item.name.text)
      }
    }
  }
  function visit(node) {
    if (ts.isImportDeclaration(node) && !node.importClause?.isTypeOnly) {
      const bindings = node.importClause?.namedBindings
      if (!(!node.importClause?.name && bindings && ts.isNamedImports(bindings) && bindings.elements.length && bindings.elements.every(item => item.isTypeOnly))) {
        const names = []
        if (node.importClause?.name) names.push({ imported: 'default', local: node.importClause.name.text })
        if (bindings && ts.isNamedImports(bindings)) for (const item of bindings.elements) {
          if (!item.isTypeOnly) names.push({ imported: item.propertyName?.text || item.name.text, local: item.name.text })
        }
        addImport(file, node.moduleSpecifier.text, lineOf(node), 'import', names)
      }
    } else if (ts.isExportDeclaration(node) && node.moduleSpecifier && !node.isTypeOnly) {
      addImport(file, node.moduleSpecifier.text, lineOf(node), 're-export')
    } else if (ts.isCallExpression(node)) {
      if (node.expression.kind === ts.SyntaxKind.ImportKeyword && stringValue(node.arguments[0])) {
        addImport(file, stringValue(node.arguments[0]), lineOf(node), 'dynamic-import')
      }
      if (ts.isIdentifier(node.expression) && renderFunctions.has(node.expression.text)) {
        const tag = stringValue(node.arguments[0])
        const attributes = {}
        const props = node.arguments[1]
        if (props && ts.isObjectLiteralExpression(props)) for (const item of props.properties) {
          if (ts.isPropertyAssignment(item)) attributes[item.name.getText(source).replace(/^['"]|['"]$/g, '')] = stringValue(item.initializer)
        }
        if (nativeTags.has(tag)) record.native_controls.push({ tag, line: lineOf(node), origin: 'render_function', attributes, ...retention(file, tag, attributes) })
        if (semanticRoles.has(attributes.role) || tag === 'dialog') record.manual_semantics.push({ tag, role: attributes.role || 'dialog', line: lineOf(node), origin: 'render_function' })
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  for (const diagnostic of source.parseDiagnostics) record.parse_errors.push({ origin: 'script', message: ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n') })
}
function analyzeTemplate(file, block) {
  const record = nodes.get(file)
  const ast = parseTemplate(block.content, { comments: false, onError: error => record.parse_errors.push({ origin: 'template', message: error.message }) })
  function visit(node) {
    if (node.type === 1) {
      const attributes = {}
      for (const prop of node.props) {
        if (prop.type === 6) attributes[prop.name] = prop.value?.content ?? ''
        if (prop.type === 7 && prop.name === 'bind' && prop.arg?.isStatic) {
          const literal = /^(['"])(.*)\1$/.exec(prop.exp?.content || '')
          if (literal) attributes[prop.arg.content] = literal[2]
          else attributes[`:${prop.arg.content}`] = prop.exp?.content || ''
        }
      }
      const line = block.loc.start.line + node.loc.start.line - 1
      if (nativeTags.has(node.tag)) record.native_controls.push({ tag: node.tag, line, origin: 'template', attributes, ...retention(file, node.tag, attributes) })
      if (semanticRoles.has(attributes.role) || node.tag === 'dialog') record.manual_semantics.push({ tag: node.tag, role: attributes.role || 'dialog', line, origin: 'template' })
      if (attributes[':role']) {
        const literalRoles = [...attributes[':role'].matchAll(/['"]([^'"]+)['"]/g)].map(match => match[1])
        if (!literalRoles.length || literalRoles.some(role => semanticRoles.has(role))) record.manual_semantics.push({ tag: node.tag, role_expression: attributes[':role'], line, origin: 'template', requires_manual_resolution: true })
      }
      if (legacyByTag.has(node.tag)) record.legacy_template_usages.push({ name: legacyByTag.get(node.tag), line })
      if (node.tag === 'component') record.dynamic_components.push({ line, is: attributes.is || attributes[':is'] || null })
    }
    for (const child of node.children || []) visit(child)
  }
  visit(ast)
}
for (const file of codeFiles) {
  const code = fs.readFileSync(file, 'utf8')
  nodes.get(file).source_sha256 = createHash('sha256').update(code).digest('hex')
  if (file.endsWith('.vue')) {
    const { descriptor, errors } = parseSfc(code, { filename: file })
    for (const error of errors) nodes.get(file).parse_errors.push({ origin: 'sfc', message: String(error.message || error) })
    for (const block of [descriptor.script, descriptor.scriptSetup].filter(Boolean)) analyzeScript(file, block.content, block.loc.start.line, block.lang)
    if (descriptor.template) analyzeTemplate(file, descriptor.template)
  } else analyzeScript(file, code, 1, path.extname(file).slice(1))
}

function reach(file) {
  const seen = new Set([file]), groups = new Set(), pending = [...graph.get(file)]
  while (pending.length) {
    const current = pending.pop()
    if (seen.has(current)) continue
    seen.add(current)
    if (foundation(current)) groups.add(foundation(current))
    for (const next of graph.get(current) || []) pending.push(next)
  }
  return [...groups].sort()
}
for (const file of vueFiles) {
  const record = nodes.get(file)
  record.direct_foundation_groups = [...new Set([...graph.get(file)].map(foundation).filter(Boolean))].sort()
  record.reachable_foundation_groups = reach(file)
  record.reference_class = record.direct_foundation_groups.length ? 'direct'
    : record.reachable_foundation_groups.length ? 'indirect_only' : 'no_static_foundation_reference'
  if (record.kind !== 'primitive' && record.reference_class === 'no_static_foundation_reference') {
    const reviewed = reviewedNoReference[record.file]
    record.no_reference_review = reviewed && reviewed.sha256 === record.source_sha256
      ? { decision: 'retain', reason: reviewed.reason, source_fingerprint_matches: true }
      : { decision: 'review', reason: reviewed ? '源码已改变，原保留判断需复核。' : '尚未人工复核；无静态引用不自动等于遗漏。' }
  }
}
const ignored = spawnSync('git', ['check-ignore', '--stdin'], { cwd: root, input: vueFiles.map(relative).join('\n'), encoding: 'utf8' })
const ignoredFiles = ignored.status === 0 ? ignored.stdout.trim().split(/\r?\n/).filter(Boolean) : []
const vueRecords = vueFiles.map(file => nodes.get(file))
const outside = [...nodes.values()].filter(item => item.kind !== 'primitive')
const collect = (records, field) => records.flatMap(record => record[field].map(item => ({ file: record.file, ...item })))
const counts = (records, field) => Object.fromEntries([...new Set(records.map(item => item[field]))].sort().map(value => [value, records.filter(item => item[field] === value).length]))
const nativeOutside = collect(outside, 'native_controls')
const semanticsOutside = collect(outside, 'manual_semantics')
const legacyOutside = collect(outside, 'legacy_template_usages')
const output = {
  schema_version: 1,
  generated_at: new Date().toISOString(),
  command: 'node tools/audit_shadcn_foundations.mjs',
  methodology: {
    traversal: 'Filesystem recursive traversal of frontend/src; includes git-ignored files, tests and all Vue SFCs.',
    parsing: 'Vue compiler SFC/template AST; TypeScript AST for runtime imports/re-exports/literal dynamic imports and h/createVNode native controls.',
    foundation_exclusion: 'Only the exact named directories under shared/components/ui. ui/app and top-level UI adapters remain in business/shared candidates.',
    reachability: 'File-level static runtime import/export graph. Re-export barrels over-approximate which bindings render; direct/indirect means reference reachability, not execution or visual coverage.',
    limits: ['No browser, runtime rendering, accessibility, responsive, or permission verification.',
      'Non-literal dynamic imports, runtime global components and dynamic component names are not resolved.',
      'v-html, Markdown-generated HTML and HTML strings produced at runtime are not counted as static native controls.',
      'File-level barrel edges may count unused exports. Render functions are recognized by known helper names, not full semantic binding/type resolution.',
      'Native controls and hand-written roles are review candidates; counts are not defects or migration-completion percentages.',
      'Foundation inventory includes local extension directories; registry provenance/version is not inferred.'],
    compiler_versions: { sfc: require('@vue/compiler-sfc/package.json').version, typescript: ts.version },
  },
  summary: {
    vue_files: vueRecords.length, code_files: codeFiles.length, vue_by_category: counts(vueRecords, 'kind'),
    feature_vue_counts: Object.fromEntries([...new Set(vueRecords.filter(item => item.kind === 'feature').map(item => item.file.split('/')[3]))].sort().map(name => [name, vueRecords.filter(item => item.file.startsWith(`frontend/src/features/${name}/`)).length])),
    reference_classes_all_vue: counts(vueRecords, 'reference_class'),
    reference_classes_non_primitive_vue: counts(vueRecords.filter(item => item.kind !== 'primitive'), 'reference_class'),
    native_controls_outside_primitives: Object.fromEntries([...nativeTags].map(tag => [tag, nativeOutside.filter(item => item.tag === tag).length])),
    native_controls_retained: nativeOutside.filter(item => item.decision === 'retain').length,
    native_controls_unresolved: nativeOutside.filter(item => item.decision === 'review').length,
    manual_semantics_outside_primitives: semanticsOutside.length,
    handwritten_semantics_role_counts: counts(semanticsOutside.map(item => ({ role: item.role || (item.role_expression?.includes("'tabpanel'") ? 'tabpanel' : 'unresolved_expression') })), 'role'),
    legacy_template_usages_outside_primitives: legacyOutside.length,
    no_reference_components_unreviewed: vueRecords.filter(item => item.no_reference_review?.decision === 'review').length,
    unresolved_local_vue_imports: vueRecords.reduce((sum, item) => sum + item.unresolved_local_imports.length, 0),
    parse_errors: [...nodes.values()].reduce((sum, item) => sum + item.parse_errors.length, 0),
  },
  exact_foundation_directories: [...foundationGroups].sort().map(group => uiPrefix + group + '/'),
  business_adapter_ui_subdirectories: ['app'],
  unclassified_ui_subdirectories: fs.readdirSync(path.join(root, uiPrefix), { withFileTypes: true }).filter(item => item.isDirectory() && !foundationGroups.has(item.name) && item.name !== 'app').map(item => item.name),
  git_ignored_vue_files_included: ignoredFiles,
  git_ignore_check_available: ignored.status === 0 || ignored.status === 1,
  retained_native_controls: nativeOutside.filter(item => item.decision === 'retain'),
  unresolved_native_controls: nativeOutside.filter(item => item.decision === 'review'),
  handwritten_semantics_outside_primitives: semanticsOutside,
  legacy_imports_outside_primitives: collect(outside, 'legacy_imports'),
  legacy_template_usages_outside_primitives: legacyOutside,
  no_reference_component_reviews: vueRecords.filter(item => item.no_reference_review).map(({ file, no_reference_review }) => ({ file, ...no_reference_review })),
  legacy_adapter_foundations: vueRecords.filter(item => legacyNames.has(path.basename(item.file, '.vue'))).map(item => ({ file: item.file, direct_foundation_groups: item.direct_foundation_groups })),
  vue_files: vueRecords,
  render_function_findings: [...nodes.values()].filter(item => !item.file.endsWith('.vue') && (item.native_controls.length || item.manual_semantics.length || item.legacy_imports.length)),
  parse_errors: [...nodes.values()].filter(item => item.parse_errors.length).map(({ file, parse_errors }) => ({ file, parse_errors })),
}
fs.mkdirSync(path.dirname(destination), { recursive: true })
fs.writeFileSync(destination, JSON.stringify(output, null, 2) + '\n')
console.log(JSON.stringify({ output: relative(destination), ...output.summary }, null, 2))
if (output.summary.parse_errors) process.exitCode = 1
