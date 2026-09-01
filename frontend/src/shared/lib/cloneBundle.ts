/**
 * 克隆包（`CloneBundle`）→ 本地战法 upsert payload（`ScreenSkillUpsertPayload`）。
 *
 * 克隆包是别人导出、经由 JSON 交换过来的一份战法。旧策略广场已经整体下线，如今唯一的
 * 入口是工坊「战法」Tab 的【从克隆包导入】——用户自己把那段 JSON 贴进来。
 * 类型定义因此**落在本模块**：它不再是某个远端上下文的响应契约，而是这条导入链路
 * 自己的输入格式。
 *
 * 为什么需要这一层「换算」而不是直接塞：**克隆包里根本没有 `ScreenSkillManifest`**。
 * 导出侧只把 `backtest` 证据写进版本清单，所以 `bundle.manifest` 里除了 `backtest`
 * 什么都没有：`schema_version` / `min_bars` / 参数定义 / `output.signal` / `factors`
 * 全部缺席。
 *
 * 缺的东西只能靠**推断 + 保守默认**补，推断出来的每一项都必须让用户看见（`warnings`），
 * 否则用户会以为导进来的战法和原作者那份一模一样——它不是。
 *
 * 本模块是纯函数、无副作用、不碰网络与 DOM，可直接单测（`cloneBundle.test.ts`）。
 */

/**
 * 克隆包里冻结的回测证据。字段随导出方而定，故留自由键。
 */
export interface CloneBacktestEvidence {
  trades?: number
  start?: string
  end?: string
  commission_bps?: number | null
  stamp_duty_bps?: number | null
  slippage_bps?: number | null
  [key: string]: unknown
}

/** 版本清单。实际只保证 `backtest` 一项，其余键一律当自由字段。 */
export interface CloneVersionManifest {
  backtest?: CloneBacktestEvidence
  [key: string]: unknown
}

/** 一份可导入的战法包。`source_text` 是战法正文，缺了就没法导入。 */
export interface CloneBundle {
  publish_id: string
  slug: string
  title: string
  summary: string
  kind: string
  entry_timing: string
  owner_name: string
  version: number
  source_text: string
  params: Record<string, unknown>
  manifest: CloneVersionManifest
  content_sha256: string
  /** 导出方标识。老包里可能是任意字符串；解析不到时填 `unknown`。 */
  imported_from: string
}
import type {
  EntryTiming,
  ScreenSkillDialect,
  ScreenSkillManifest,
  ScreenSkillParamDef,
  ScreenSkillRuntime,
  ScreenSkillUpsertPayload,
} from '@/shared/types/screenSkill'

/** 与 `EntryTiming` 同源；用来判断 bundle 带过来的字符串是否合法。 */
const ENTRY_TIMINGS: readonly EntryTiming[] = ['open', 'close', 'next_open', 'next_dip']

/** 非法 / 缺失入场时点的降级值：与后端 `ScreenSkillManifestModel.entry_timing` 的默认值一致。 */
export const CLONE_FALLBACK_ENTRY_TIMING: EntryTiming = 'next_open'

/**
 * `min_bars` 的保守默认。
 *
 * 依据：仓内两条自动建稿路径（`src/strategy/application/screen_skill_generation.py:97`
 * 与 `:137`，公式稿与 Python 稿）在同样「不知道真实窗口」的处境下都写 120。
 * 取大不取小是因为公式编译器会拿它跟推导值比对
 * （`src/formula/domain/screen_formula_compiler.py:441` 的 `E_MIN_BARS_DECLARED`：
 * 声明值**小于**推导值直接编译失败）——宁可多要历史，也不要导入即报错。
 */
export const CLONE_DEFAULT_MIN_BARS = 120

/**
 * 输出信号名的兜底。
 *
 * 依据：后端 `src/strategy/api/screen_skill_schemas.py:23`
 * （`ScreenSkillManifestOutputModel.signal` 默认 `PICK`），以及
 * `screen_skill_generation.py:139` 的 Python 稿同样写 `PICK`。仓内惯用值是 `PICK`，
 * 不是字面量 `signal`。
 */
export const CLONE_DEFAULT_SIGNAL = 'PICK'

/** Python 运行时的默认入口，与 `src/strategy/application/screen_python.py:282` 一致。 */
export const CLONE_PYTHON_ENTRYPOINT = 'strategy.py:compute'

/**
 * `schema_version` 固定 1。
 *
 * API 层 `Literal[1, 2]` 两个都收，但公式编译器
 * `src/formula/domain/screen_formula_types.py:160` 只认 1（`E_SCHEMA_VERSION`），
 * 而重建出来的 manifest 绝大多数会走公式运行时，所以取两边的交集。
 */
const CLONE_SCHEMA_VERSION = 1

/** 后端 `ScreenSkillDraftModel` 的字段上限，超了会 422，所以在前端就截断。 */
const MAX_SLUG = 64
const MAX_NAME = 80
const MAX_DESCRIPTION = 240
/** 留出 `-999` 这样的去重后缀空间。 */
const MAX_SLUG_BASE = MAX_SLUG - 4

/**
 * 公式里的信号名探测，移植自 `screen_skill_generation.py:10`（`_SIGNAL_PATTERN`）：
 * 行首 `NAME:`（但不是 `NAME:=`，那是因子赋值）。
 *
 * 为什么要探测而不是一律写 `PICK`：公式编译器要求 `manifest.output.signal` 真的是
 * 源码里定义过的名字，写死 `PICK` 会让绝大多数公式克隆包在保存那一刻 422。
 */
const SIGNAL_PATTERN = /^[ \t]*([A-Za-z_][A-Za-z0-9_]*)[ \t]*:(?!=)/m

export interface BundleImportPlan {
  payload: ScreenSkillUpsertPayload
  /** 展示给用户看的「这些东西没跟过来 / 这些是猜的」。顺序稳定，可直接渲染成列表。 */
  warnings: string[]
  slugRenamed: boolean
}

/** 粘贴模式的解析结果。失败时 `error` 必须说清「错在哪一步」，不能只说「格式不对」。 */
export type CloneBundleParse = { ok: true; bundle: CloneBundle } | { ok: false; error: string }

/** 一个克隆包最少得有这几样，缺了就没法导入（`source_text` 是战法正文，后端要求非空）。 */
const REQUIRED_BUNDLE_FIELDS = ['slug', 'title', 'source_text'] as const

/** JSON 里的「普通对象」：不是 null、不是数组。 */
function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

/**
 * 把用户粘进来的文本解析成 `CloneBundle`。
 *
 * 失败分三档，分别对应三种真实误操作：粘空了 / 粘的不是 JSON（常见是漏了首尾大括号，
 * 或把整段带提示语一起复制了）/ 粘了个别的对象（比如只粘了 `manifest` 那一块）。
 */
export function parseCloneBundleText(raw: string): CloneBundleParse {
  const text = String(raw ?? '').trim()
  if (!text) {
    return { ok: false, error: '粘贴框是空的。把克隆时复制到剪贴板的那一整段 JSON 贴进来。' }
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch (caught) {
    const reason = caught instanceof Error ? caught.message : String(caught)
    const hint = text.startsWith('{')
      ? '看起来开头有 `{`，多半是**没粘全**（结尾的 `}` 丢了）。'
      : '克隆包是一整个以 `{` 开头、`}` 结尾的对象，别只粘中间某几行，也别带上页面提示语。'
    return { ok: false, error: `这段不是合法 JSON：${reason}。${hint}` }
  }
  if (Array.isArray(parsed)) {
    return {
      ok: false,
      error: '粘进来的是一个数组，克隆包应该是单个对象（`{ "publish_id": … }`）。',
    }
  }
  if (!parsed || typeof parsed !== 'object') {
    return {
      ok: false,
      error: `粘进来的是 ${typeName(parsed)}，克隆包应该是单个对象（\`{ "publish_id": … }\`）。`,
    }
  }
  const row = parsed as Record<string, unknown>
  const missing = REQUIRED_BUNDLE_FIELDS.filter((field) => {
    const value = row[field]
    return value == null || String(value).trim() === ''
  })
  if (missing.length) {
    return {
      ok: false,
      error:
        `这个对象缺少克隆包必备字段：${missing.join('、')}。`
        + '你可能只粘了克隆包里的一小块（比如单独的 manifest 或 params），'
        + '让导出方重新导一份完整的克隆包给你。',
    }
  }
  const manifest = row.manifest
  const params = row.params
  const bundle: CloneBundle = {
    publish_id: String(row.publish_id ?? ''),
    slug: String(row.slug ?? ''),
    title: String(row.title ?? ''),
    summary: String(row.summary ?? ''),
    kind: String(row.kind ?? ''),
    entry_timing: String(row.entry_timing ?? ''),
    owner_name: String(row.owner_name ?? ''),
    version: Number(row.version ?? 0) || 0,
    source_text: String(row.source_text ?? ''),
    params: isPlainObject(params) ? (params as Record<string, unknown>) : {},
    manifest: isPlainObject(manifest) ? (manifest as CloneBundle['manifest']) : {},
    content_sha256: String(row.content_sha256 ?? ''),
    imported_from: String(row.imported_from ?? 'unknown'),
  }
  return { ok: true, bundle }
}

/** 洗成后端 slug 正则 `^[a-z0-9][a-z0-9._-]{0,63}$` 的子集：小写字母 / 数字 / 连字符。 */
function slugify(raw: string): string {
  const cleaned = String(raw ?? '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, MAX_SLUG_BASE)
    .replace(/-+$/g, '')
  return cleaned || 'cloned-skill'
}

/** slug 已存在就递增后缀，**绝不覆盖本地同名战法**。 */
function dedupeSlug(base: string, taken: ReadonlySet<string>): string {
  if (!taken.has(base)) return base
  for (let n = 2; n <= 999; n += 1) {
    const candidate = `${base}-${n}`
    if (!taken.has(candidate)) return candidate
  }
  // 999 个同名战法这种事不该发生；真发生了也得给个唯一值，而不是静默覆盖。
  return `${base}-${Date.now().toString(36)}`
}

/**
 * 运行时推断。克隆包没有 runtime 字段，只能看正文长什么样：
 * 有 `def ` / `import ` / `from … import ` 的行 → Python，否则当公式。
 */
function looksLikePython(sourceText: string): boolean {
  return String(sourceText ?? '')
    .split(/\r?\n/)
    .some((line) => {
      const text = line.trim()
      return (
        text.startsWith('def ') || text.startsWith('import ') || /^from\s+\S+\s+import\s/.test(text)
      )
    })
}

/** 值的中文类型名，只用于 warnings 文案。 */
function typeName(value: unknown): string {
  if (value === null) return 'null'
  if (Array.isArray(value)) return '数组'
  const kind = typeof value
  if (kind === 'string') return '字符串'
  if (kind === 'object') return '对象'
  if (kind === 'undefined') return '空值'
  if (kind === 'number') return '数字'
  return kind
}

/** 简短地把丢弃掉的原值放进提示里，别刷屏。 */
function preview(value: unknown): string {
  let text: string
  try {
    text = JSON.stringify(value) ?? String(value)
  } catch {
    text = String(value)
  }
  return text.length > 40 ? `${text.slice(0, 40)}…` : text
}

/**
 * `bundle.params` 是**运行时的值**（`Record<string, unknown>`），
 * `manifest.params` 要的是**参数定义**（`{ type, default, … }`）。只能从值反推类型；
 * 反推不出来的（字符串 / 数组 / 对象 / null / NaN）一律丢弃并逐个告警——
 * 猜一个假的类型定义比丢掉更危险。
 */
function inferParams(
  raw: Record<string, unknown> | null | undefined,
  warnings: string[],
): Record<string, ScreenSkillParamDef> {
  const params: Record<string, ScreenSkillParamDef> = {}
  const entries = raw && typeof raw === 'object' ? Object.entries(raw) : []
  for (const [key, value] of entries) {
    if (typeof value === 'boolean') {
      params[key] = { type: 'bool', default: value }
      continue
    }
    if (typeof value === 'number' && Number.isFinite(value)) {
      params[key] = { type: Number.isInteger(value) ? 'int' : 'float', default: value }
      continue
    }
    warnings.push(
      `参数「${key}」的值是${typeName(value)}（${preview(value)}），`
        + '战法参数只支持 int / float / bool 三种，已丢弃；需要的话去策稿台手工补上。',
    )
  }
  return params
}

/** 回测证据里能读到的区间与笔数，用来把「没跟过来的是什么」说具体。 */
function backtestSpan(bundle: CloneBundle): string {
  const evidence = bundle.manifest?.backtest
  if (!evidence) return ''
  const start = String(evidence.start ?? '').trim()
  const end = String(evidence.end ?? '').trim()
  const trades = evidence.trades
  const span = start && end ? `${start} ~ ${end}` : ''
  const count = typeof trades === 'number' ? `${trades} 笔` : ''
  return [span, count].filter(Boolean).join('、')
}

/** `summary` + 一行来源标注，让人一年后还记得这东西哪来的。后端上限 240 字。 */
function buildDescription(bundle: CloneBundle, warnings: string[]): string {
  const owner = String(bundle.owner_name ?? '').trim() || '匿名作者'
  const title = String(bundle.title ?? '').trim() || String(bundle.slug ?? '').trim() || '未命名'
  const origin = `克隆自 @${owner} 的【${title}】v${bundle.version}`.slice(0, MAX_DESCRIPTION)
  const summary = String(bundle.summary ?? '').trim()
  if (!summary) return origin
  const room = MAX_DESCRIPTION - origin.length - 1
  if (room <= 0) return origin
  if (summary.length > room) {
    warnings.push(
      `原摘要 ${summary.length} 字，超过本地战法简介上限（${MAX_DESCRIPTION} 字，`
        + '含来源标注），已截断；完整描述去原始克隆包的 summary 里看。',
    )
    return `${summary.slice(0, room - 1)}…\n${origin}`
  }
  return `${summary}\n${origin}`
}

/**
 * 把克隆包换算成一份可以直接 `POST /api/screen-skills` 的 payload。
 *
 * @param bundle 从克隆包 JSON 解析出来的 `bundle`（`parseCloneBundleText`）
 * @param existingSlugs 本地已有战法的 slug（`getScreenSkills()`），用来去重
 */
export function planBundleImport(
  bundle: CloneBundle,
  existingSlugs: readonly string[],
): BundleImportPlan {
  const warnings: string[] = []

  // ---- slug：洗形状 + 去重，绝不覆盖本地同名战法 ----------------------------
  const original = String(bundle.slug ?? '').trim()
  const taken = new Set(existingSlugs.map((item) => String(item ?? '').trim()).filter(Boolean))
  const base = slugify(original)
  const slug = dedupeSlug(base, taken)
  const slugRenamed = slug !== original
  if (slugRenamed) {
    if (taken.has(base)) {
      warnings.push(
        `本地已经有 slug 为「${base}」的战法，为免覆盖你自己的东西，`
          + `这份克隆件改名为「${slug}」。`,
      )
    } else {
      warnings.push(
        `原 slug「${original || '（空）'}」不符合本地命名规则（只允许小写字母、数字、连字符），`
          + `已洗成「${slug}」。`,
      )
    }
  }

  // ---- runtime / dialect：猜的，必须告警 ------------------------------------
  const sourceText = String(bundle.source_text ?? '')
  const isPython = looksLikePython(sourceText)
  const runtime: ScreenSkillRuntime = isPython ? 'python' : 'formula'
  const dialect: ScreenSkillDialect = isPython ? 'python' : 'loci'
  warnings.push(
    isPython
      ? '正文里有 def / import，按 Python 脚本战法导入（runtime=python、dialect=python，'
          + `入口默认 ${CLONE_PYTHON_ENTRYPOINT}）。克隆包不携带 runtime 字段，这是猜的——`
          + '猜错了去策稿台切换运行时。'
      : '正文里没有 def / import，按公式战法导入（runtime=formula、dialect=loci）。'
          + '克隆包不携带 runtime 字段，这是猜的——若原作者写的是通达信 / 同花顺方言，'
          + '导入后去策稿台改方言再保存。',
  )
  if (!sourceText.trim()) {
    warnings.push(
      '这份克隆包的正文是空的。战法正文不能为空，直接导入会被后端拒绝，'
        + '请找导出方要一份带正文的克隆包。',
    )
  }

  // ---- entry_timing：不在合法值里就降级 ------------------------------------
  const rawTiming = String(bundle.entry_timing ?? '').trim()
  const validTiming = (ENTRY_TIMINGS as readonly string[]).includes(rawTiming)
  const entryTiming = validTiming ? (rawTiming as EntryTiming) : CLONE_FALLBACK_ENTRY_TIMING
  if (!validTiming) {
    warnings.push(
      `克隆包的入场时点「${rawTiming || '（空）'}」不是本地认得的四种`
        + `（${ENTRY_TIMINGS.join(' / ')}），已降级为 ${CLONE_FALLBACK_ENTRY_TIMING}。`,
    )
  }

  // ---- manifest：整份重建，因为 bundle 里压根没有 --------------------------
  const params = inferParams(bundle.params, warnings)
  const paramCount = Object.keys(params).length
  if (paramCount) {
    warnings.push(
      `${paramCount} 个参数是从运行时的值反推出来的定义（int / float / bool），`
        + '没有取值范围与中文标签——原作者的参数定义不在克隆包里。',
    )
  }
  const detected = runtime === 'formula' ? SIGNAL_PATTERN.exec(sourceText)?.[1] : ''
  const signal = detected ? detected.toUpperCase() : CLONE_DEFAULT_SIGNAL
  warnings.push(
    '原战法的 manifest 不在克隆包里（导出侧只冻结回测证据），下面这份是重建的：'
      + `min_bars=${CLONE_DEFAULT_MIN_BARS}（保守默认，不是原值）、`
      + `输出信号=${signal}（${detected ? '从正文首个信号定义读出' : '仓内默认值'}）、`
      + '因子列表为空。导入后请在策稿台核对，再跑一次预览。',
  )

  const manifest: ScreenSkillManifest = {
    schema_version: CLONE_SCHEMA_VERSION,
    entry_timing: entryTiming,
    min_bars: CLONE_DEFAULT_MIN_BARS,
    params,
    output: { signal },
    factors: [],
  }

  // ---- 回测证据：是**别人那一版**的证据，不进本地 manifest ------------------
  const span = backtestSpan(bundle)
  warnings.push(
    span
      ? `原作者的回测证据（${span}）没有跟过来——那是他那一版的证据，不是你这份的。`
          + '导入后要用自己的区间和成本重跑回测，别拿别人的数字当自己的。'
      : '克隆包里没有可读的回测证据。导入后要自己跑一次回测，才知道这套东西在你的口径下什么样。',
  )

  const payload: ScreenSkillUpsertPayload = {
    slug,
    name: (String(bundle.title ?? '').trim() || slug).slice(0, MAX_NAME),
    description: buildDescription(bundle, warnings),
    // 本地是全新的一份，从 0.1.0 起步；原作者的版本号记在 description 的来源标注里。
    version: '0.1.0',
    enabled: true,
    runtime,
    dialect,
    manifest,
    ...(isPython
      ? { code: sourceText, entrypoint: CLONE_PYTHON_ENTRYPOINT }
      : { formula: sourceText }),
  }

  return { payload, warnings, slugRenamed }
}
