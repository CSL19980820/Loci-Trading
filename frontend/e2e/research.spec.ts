import { expect, test, type Locator, type Page } from '@playwright/test'

const researchCatalog = {
  version: 'research-catalog-v1',
  dimensions: [],
  sources: [],
  market_adapters: [],
  quality_values: ['full', 'partial', 'missing', 'error'],
  budgets: [],
  guardrails: {
    production_signal: false,
    static_scores_are_not_facts: true,
    missing_data_stays_missing: true,
    market_health_gate: true,
  },
}

const manifestSha256 = 'a'.repeat(64)
const timestamp = '2026-08-05T00:00:00Z'

type RunStatus = 'running' | 'awaiting_human_review' | 'completed' | 'stale' | 'failed' | 'rejected'
type JobStatus = 'queued' | 'running' | 'completed' | 'failed'

function backtestRun(
  runId: string,
  options: {
    status?: RunStatus
    validationStatus?: string
    manifest?: string
    strictPit?: boolean
    dataSnapshot?: Record<string, unknown>
    sourceEvidence?: Record<string, unknown>[]
  } = {},
) {
  const manifest = options.manifest ?? manifestSha256
  return {
    contract_version: 'research-run-card-v1',
    run_id: runId,
    strategy_slug: 'sanyuan-tail-v1',
    strategy_revision: 'builtin:sanyuan-tail-v2',
    version: 'v2',
    hypothesis_id: null,
    hypothesis_revision: null,
    requested_as_of: '2025-12-31',
    actual_as_of: '2025-12-31',
    market_revision: 'market-r1',
    universe: {},
    universe_funnel: {},
    params: {},
    backtest_config: { hold_days: 3 },
    data_snapshot: options.dataSnapshot ?? { frozen_input_sha256: 'frozen-input-r1' },
    source_evidence: options.sourceEvidence ?? [],
    metrics: { trades: 12 },
    validation: { status: options.validationStatus ?? 'passed', strict_pit: options.strictPit ?? false },
    risk_xray: {},
    conclusion: null,
    artifact_manifest: [],
    status: options.status ?? 'awaiting_human_review',
    created_at: timestamp,
    updated_at: timestamp,
    input_sha256: 'input-r1',
    artifact_manifest_sha256: manifest,
    manifest_sha256: manifest,
    error: '',
  }
}

function workflow(runId: string, status: 'awaiting_human_review' | 'completed' | 'failed' = 'awaiting_human_review') {
  return {
    contract_version: 'research-workflow-v1',
    workflow_id: `workflow-${runId}`,
    run_id: runId,
    max_retries: 1,
    status,
    stages: {},
    events: [],
  }
}

function backtestJob(
  id: string,
  status: JobStatus,
  options: { runId?: string; error?: string } = {},
) {
  return {
    id,
    status,
    request: {},
    run_id: options.runId ?? '',
    error: options.error ?? '',
    created_at: timestamp,
    updated_at: timestamp,
  }
}

async function installBaseRoutes(page: Page): Promise<void> {
  await page.route('**/api/**', async (route) => {
    const { pathname } = new URL(route.request().url())
    if (pathname === '/api/auth/session' || pathname === '/api/auth/login') {
      return route.fulfill({ json: { authenticated: true, username: 'research-e2e' } })
    }
    if (pathname === '/api/health' || pathname === '/api/') {
      return route.fulfill({ json: { status: 'ok' } })
    }
    if (pathname === '/api/research/catalog') return route.fulfill({ json: researchCatalog })
    if (pathname === '/api/research/backtest-runs') return route.fulfill({ json: { items: [], total: 0 } })
    if (pathname === '/api/research/hypotheses') return route.fulfill({ json: { items: [], total: 0 } })
    if (pathname === '/api/research/membership-snapshots') return route.fulfill({ json: { items: [], total: 0 } })
    if (pathname === '/api/research/point-in-time-facts') return route.fulfill({ json: { items: [], total: 0 } })
    if (pathname === '/api/skills' || pathname === '/api/jobs') return route.fulfill({ json: [] })
    if (pathname === '/api/strategies') {
      return route.fulfill({ json: [{ slug: 'sanyuan-tail-v1', name: '三源尾盘' }] })
    }
    return route.fulfill({ status: 200, json: {} })
  })
}

function getBacktestPanel(page: Page): Locator {
  return page.locator('section[aria-label="可审计研究回测"]')
}

function backtestFormItem(panel: Locator, label: string): Locator {
  return panel.locator('.backtest-form .el-form-item').filter({ hasText: label })
}

async function fillDateRange(panel: Locator, label: string, start: string, end: string): Promise<void> {
  const inputs = backtestFormItem(panel, label).locator('input')
  await inputs.nth(0).fill(start)
  await inputs.nth(1).fill(end)
  await inputs.nth(1).press('Tab')
}

async function fillCompleteBacktestForm(panel: Locator, universeId = ''): Promise<void> {
  await backtestFormItem(panel, '策略 slug').locator('input').fill('sanyuan-tail-v1')
  await fillDateRange(panel, '回测区间', '2024-01-02', '2025-12-31')
  await fillDateRange(panel, '训练区间', '2024-01-02', '2024-12-31')
  await fillDateRange(panel, 'OOS 区间', '2025-01-01', '2025-12-31')
  if (universeId) {
    await backtestFormItem(panel, '历史股票池标识').locator('input').fill(universeId)
  }
}

async function selectRun(panel: Locator, runId: string): Promise<void> {
  const row = panel.locator('tr').filter({ hasText: runId })
  await expect(row).toBeVisible()
  await row.getByRole('button', { name: '查看' }).click()
  await expect(panel.locator('.run-detail-head').getByText(runId, { exact: true })).toBeVisible()
}

test.describe('研究证据台', () => {
  test.beforeEach(async ({ page }) => {
    await installBaseRoutes(page)
  })

  test('shows the auditable research workflow on desktop', async ({ page }) => {
    await page.goto('/quant?tab=research')

    await expect(page.getByRole('heading', { name: '研究剖面' })).toBeVisible({ timeout: 30_000 })
    await expect(page.getByRole('heading', { name: '历史数据' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '研究回测' })).toBeVisible()
    const strictPitField = page.locator('.el-form-item').filter({ hasText: 'PIT 严格模式' })
    await expect(strictPitField.getByText('PIT 严格模式')).toBeVisible()
    await expect(strictPitField.locator('.el-switch')).toBeVisible()
    await expect(page.getByText('探索性 / 降级研究')).toBeVisible()
  })

  test('uses the mobile layout without document horizontal overflow', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/quant?tab=research')
    await expect(page.getByRole('heading', { name: '研究剖面' })).toBeVisible({ timeout: 30_000 })

    const layout = await page.locator('.research-head').evaluate((head) => ({
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: document.documentElement.clientWidth,
      direction: getComputedStyle(head).flexDirection,
    }))
    expect(layout.direction).toBe('column')
    expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth)
    await expect(page.getByText('探索性 / 降级研究')).toBeVisible()
  })

  test('imports historical memberships and keeps a backend 422 visible', async ({ page }) => {
    const snapshot = {
      universe_id: 'CSI300-2025',
      as_of: '2025-01-02',
      available_at: '2025-01-02',
      members: ['600519'],
      source_id: 'fixture-source',
      source_url: 'https://example.test/memberships',
      snapshot_revision: 'snapshot-r1',
      fetched_at: '2026-08-05T09:30:00Z',
      payload_sha256: manifestSha256,
      parser_revision: 'fixture-parser-r1',
    }
    const importBodies: unknown[] = []
    let importAttempts = 0

    await page.route('**/api/research/membership-snapshots**', async (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ json: { items: [snapshot], total: 1, resolved: snapshot } })
      }
      return route.fulfill({ status: 200, json: {} })
    })
    await page.route('**/api/research/membership-snapshots/import', async (route) => {
      importBodies.push(JSON.parse(route.request().postData() || '{}'))
      importAttempts += 1
      if (importAttempts === 1) return route.fulfill({ json: { items: [snapshot], total: 1 } })
      return route.fulfill({
        status: 422,
        json: { detail: 'available_at 不可见，服务端拒绝快照' },
      })
    })

    await page.goto('/quant?tab=research')
    const temporalPanel = page.locator('section[aria-label="历史研究数据"]')
    await temporalPanel.getByRole('button', { name: '导入快照' }).click()
    const dialog = page.getByRole('dialog', { name: '导入历史股票池快照' })
    await dialog.locator('textarea').fill(JSON.stringify([snapshot]))
    await dialog.getByRole('button', { name: '导入并校验' }).click()

    await expect(dialog).toBeHidden()
    expect(importBodies).toEqual([{ snapshots: [snapshot] }])
    await expect(temporalPanel.getByText('1 条', { exact: true })).toBeVisible()

    await temporalPanel.getByRole('button', { name: '导入快照' }).click()
    const rejectedDialog = page.getByRole('dialog', { name: '导入历史股票池快照' })
    await rejectedDialog.locator('textarea').fill(JSON.stringify([snapshot]))
    await rejectedDialog.getByRole('button', { name: '导入并校验' }).click()

    // 422 走的是专属文案分支（区别于 401/503），后端 detail 必须原样透出来。
    await expect(rejectedDialog.getByText('导入内容不符合研究库的格式要求')).toBeVisible()
    await expect(rejectedDialog.getByText('available_at 不可见，服务端拒绝快照')).toBeVisible()
    expect(importBodies).toEqual([{ snapshots: [snapshot] }, { snapshots: [snapshot] }])
  })

  test('blocks incomplete strict PIT locally and submits the completed request payload', async ({ page }) => {
    const submitted: unknown[] = []
    await page.route('**/api/research/backtest-jobs', async (route) => {
      submitted.push(JSON.parse(route.request().postData() || '{}'))
      return route.fulfill({ json: { job: backtestJob('job-strict-pit', 'queued') } })
    })
    await page.route('**/api/research/backtest-jobs/job-strict-pit', async (route) => {
      return route.fulfill({
        json: { job: backtestJob('job-strict-pit', 'failed', { error: 'fixture completed' }) },
      })
    })

    await page.goto('/quant?tab=research')
    const panel = getBacktestPanel(page)
    await backtestFormItem(panel, '策略 slug').locator('input').fill('sanyuan-tail-v1')
    await fillDateRange(panel, '回测区间', '2024-01-02', '2025-12-31')
    await backtestFormItem(panel, 'PIT 严格模式').locator('.el-switch').click()
    await panel.getByRole('button', { name: '提交回测' }).click()

    await expect(panel.getByText(/严格 PIT 模式要求完整训练\/OOS 区间和历史股票池标识/)).toBeVisible()
    expect(submitted).toEqual([])

    await fillDateRange(panel, '训练区间', '2024-01-02', '2024-12-31')
    await fillDateRange(panel, 'OOS 区间', '2025-01-01', '2025-12-31')
    await backtestFormItem(panel, '历史股票池标识').locator('input').fill('CSI300-2024-2025')
    const request = page.waitForRequest((candidate) => (
      candidate.method() === 'POST'
      && new URL(candidate.url()).pathname === '/api/research/backtest-jobs'
    ))
    await panel.getByRole('button', { name: '提交回测' }).click()
    await request

    expect(submitted).toHaveLength(1)
    expect(submitted).toEqual([{
      strategy: 'sanyuan-tail-v1',
      start: '2024-01-02',
      end: '2025-12-31',
      backtest_config: { hold_days: 3 },
      initial_capital: 200000,
      max_positions: 2,
      split: {
        train_start: '2024-01-02',
        train_end: '2024-12-31',
        oos_start: '2025-01-01',
        oos_end: '2025-12-31',
      },
      historical_universe_id: 'CSI300-2024-2025',
      strict_pit: true,
    }])
  })

  test('retries a failed backtest-job poll through the visible retry control', async ({ page }) => {
    let polls = 0
    await page.route('**/api/research/backtest-jobs', async (route) => {
      return route.fulfill({ json: { job: backtestJob('job-retry', 'queued') } })
    })
    await page.route('**/api/research/backtest-jobs/job-retry', async (route) => {
      polls += 1
      if (polls === 1) {
        return route.fulfill({ status: 400, json: { detail: 'fixture transient read failure' } })
      }
      return route.fulfill({
        json: { job: backtestJob('job-retry', 'failed', { error: 'fixture terminal failure' }) },
      })
    })

    await page.goto('/quant?tab=research')
    const panel = getBacktestPanel(page)
    await fillCompleteBacktestForm(panel)
    await panel.getByRole('button', { name: '提交回测' }).click()

    const retry = panel.getByRole('button', { name: '重试读取任务状态' })
    await expect(retry).toBeVisible()
    expect(polls).toBe(1)
    await retry.click()

    await expect(panel.getByText('fixture terminal failure')).toBeVisible()
    expect(polls).toBe(2)
  })

  test('renders frozen PIT provenance and backend source failures without inventing a pass state', async ({ page }) => {
    const run = backtestRun('run-evidence', {
      validationStatus: 'degraded',
      dataSnapshot: {
        frozen_input_sha256: 'frozen-input-r1',
        temporal_membership: {
          universe_id: 'CSI300-2025', as_of: '2025-01-02', available_at: '2025-01-02',
          source_id: 'fixture-membership', source_url: 'https://example.test/memberships',
          snapshot_revision: 'snapshot-r1', fetched_at: timestamp,
          payload_sha256: manifestSha256, parser_revision: 'fixture-parser-r1',
          pit_membership: false, degraded: true, survivorship_bias: true,
        },
      },
      sourceEvidence: [{
        attempts_not_observed: true,
        unresolved_codes: ['600002'],
        sources: [{ source_id: 'fixture-source', state: 'failed', error: 'upstream timeout' }],
        receipts: [{ receipt_id: 'receipt-1', code: '600002', state: 'failed', error: 'coverage missing' }],
        attempts: [{ source_id: 'fixture-source', state: 'failed', error: 'upstream timeout' }],
      }],
    })
    await page.route('**/api/research/backtest-runs**', async (route) => {
      const { pathname } = new URL(route.request().url())
      if (pathname === '/api/research/backtest-runs') return route.fulfill({ json: { items: [run], total: 1 } })
      if (pathname === '/api/research/backtest-runs/run-evidence') return route.fulfill({ json: run })
      if (pathname === '/api/research/backtest-runs/run-evidence/workflow') return route.fulfill({ json: workflow('run-evidence') })
      return route.fulfill({ json: {} })
    })

    await page.goto('/quant?tab=research')
    const panel = getBacktestPanel(page)
    await panel.getByRole('button', { name: '刷新' }).click()
    await selectRun(panel, 'run-evidence')

    await expect(panel.getByText('降级 / 探索性研究')).toBeVisible()
    await expect(panel.getByText(/不能作为假设通过、已核验证据或生产默认/)).toBeVisible()
    await expect(panel.getByText('temporal_membership.payload_sha256')).toBeVisible()
    await expect(panel.getByText('来源 attempt 未观测')).toBeVisible()
    await expect(panel.getByText('来源失败：fixture-source（upstream timeout）')).toBeVisible()
    await expect(panel.getByText('回执错误：600002（coverage missing）')).toBeVisible()
    await expect(panel.getByText('来源尝试')).toBeVisible()
  })

  test('enforces publish and reject conditions, then returns their manifest-bound payloads', async ({ page }) => {
    const blocked = backtestRun('run-blocked', { validationStatus: 'failed', manifest: '' })
    const publishable = backtestRun('run-publish', { manifest: manifestSha256 })
    const rejectable = backtestRun('run-reject', { manifest: 'b'.repeat(64) })
    const runs = {
      [blocked.run_id]: blocked,
      [publishable.run_id]: publishable,
      [rejectable.run_id]: rejectable,
    }
    let publishPayload: unknown
    let rejectPayload: unknown

    await page.route('**/api/research/backtest-runs**', async (route) => {
      const { pathname } = new URL(route.request().url())
      const method = route.request().method()
      if (method === 'GET' && pathname === '/api/research/backtest-runs') {
        return route.fulfill({ json: { items: Object.values(runs), total: 3 } })
      }
      const match = /^\/api\/research\/backtest-runs\/([^/]+)(?:\/(workflow|publish|reject))?$/.exec(pathname)
      const runId = match?.[1]
      const action = match?.[2]
      if (method === 'GET' && runId && action === 'workflow') {
        return route.fulfill({ json: workflow(runId) })
      }
      if (method === 'GET' && runId && !action) {
        return route.fulfill({ json: runs[runId as keyof typeof runs] })
      }
      if (method === 'POST' && runId === 'run-publish' && action === 'publish') {
        publishPayload = JSON.parse(route.request().postData() || '{}')
        return route.fulfill({
          json: { run_card: backtestRun(runId, { status: 'completed' }), workflow: workflow(runId, 'completed'), reused: false },
        })
      }
      if (method === 'POST' && runId === 'run-reject' && action === 'reject') {
        rejectPayload = JSON.parse(route.request().postData() || '{}')
        return route.fulfill({
          json: { run_card: backtestRun(runId, { status: 'rejected' }), workflow: workflow(runId, 'completed'), reused: false },
        })
      }
      return route.fulfill({ status: 200, json: {} })
    })

    await page.goto('/quant?tab=research')
    const panel = getBacktestPanel(page)
    await panel.getByRole('button', { name: '刷新' }).click()
    await selectRun(panel, 'run-blocked')

    await panel.getByRole('button', { name: '人工签署发布' }).click()
    const blockedPublish = page.getByRole('dialog', { name: '人工签署发布' })
    await expect(blockedPublish.getByText(/当前 run 不满足发布条件/)).toBeVisible()
    await expect(blockedPublish.getByRole('button', { name: '人工签署发布' })).toBeDisabled()
    await blockedPublish.getByRole('button', { name: '取消' }).click()

    await panel.getByRole('button', { name: '人工否决' }).click()
    const blockedReject = page.getByRole('dialog', { name: '人工否决' })
    await expect(blockedReject.getByText(/当前 run 不满足否决条件/)).toBeVisible()
    await expect(blockedReject.getByRole('button', { name: '记录人工否决' })).toBeDisabled()
    await blockedReject.getByRole('button', { name: '取消' }).click()

    await selectRun(panel, 'run-publish')
    await panel.getByRole('button', { name: '人工签署发布' }).click()
    const publishDialog = page.getByRole('dialog', { name: '人工签署发布' })
    await publishDialog.locator('input').fill('reviewer-publish')
    await publishDialog.locator('textarea').fill('人工复核通过')
    const publishRequest = page.waitForRequest((candidate) => (
      candidate.method() === 'POST'
      && new URL(candidate.url()).pathname === '/api/research/backtest-runs/run-publish/publish'
    ))
    await publishDialog.getByRole('button', { name: '人工签署发布' }).click()
    await publishRequest

    expect(publishPayload).toEqual({
      manifest_sha256: manifestSha256,
      reviewer: 'reviewer-publish',
      reason: '人工复核通过',
    })

    await selectRun(panel, 'run-reject')
    await panel.getByRole('button', { name: '人工否决' }).click()
    const rejectDialog = page.getByRole('dialog', { name: '人工否决' })
    await rejectDialog.locator('input').fill('reviewer-reject')
    await rejectDialog.locator('textarea').fill('PIT 证据缺失')
    const rejectRequest = page.waitForRequest((candidate) => (
      candidate.method() === 'POST'
      && new URL(candidate.url()).pathname === '/api/research/backtest-runs/run-reject/reject'
    ))
    await rejectDialog.getByRole('button', { name: '记录人工否决' }).click()
    await rejectRequest

    expect(rejectPayload).toEqual({
      manifest_sha256: 'b'.repeat(64),
      reviewer: 'reviewer-reject',
      reason: 'PIT 证据缺失',
    })
  })

  test('shows an explicit warning when replayed frozen execution does not match', async ({ page }) => {
    const run = backtestRun('run-replay')
    await page.route('**/api/research/backtest-runs**', async (route) => {
      const { pathname } = new URL(route.request().url())
      const method = route.request().method()
      if (method === 'GET' && pathname === '/api/research/backtest-runs') {
        return route.fulfill({ json: { items: [run], total: 1 } })
      }
      if (method === 'GET' && pathname === '/api/research/backtest-runs/run-replay') {
        return route.fulfill({ json: run })
      }
      if (method === 'GET' && pathname === '/api/research/backtest-runs/run-replay/workflow') {
        return route.fulfill({ json: workflow('run-replay') })
      }
      if (method === 'POST' && pathname === '/api/research/backtest-runs/run-replay/replay') {
        return route.fulfill({
          json: {
            run_card: run,
            workflow: workflow('run-replay'),
            comparison: {
              contract_version: 'research-replay-v1',
              run_id: 'run-replay',
              source_manifest_sha256: manifestSha256,
              input_sha256: 'input-r1',
              matches_card_metrics: true,
              execution_matches: { main: true, control: false, train: true, oos: false },
              matches_all_recomputed_execution: false,
            },
            receipt: {
              path: 'replay/receipt.json',
              sha256: 'r'.repeat(64),
              created_at: timestamp,
              size_bytes: 32,
              artifact_type: 'replay-receipt',
              metadata: {},
            },
          },
        })
      }
      return route.fulfill({ status: 200, json: {} })
    })

    await page.goto('/quant?tab=research')
    const panel = getBacktestPanel(page)
    await panel.getByRole('button', { name: '刷新' }).click()
    await selectRun(panel, 'run-replay')
    await panel.getByRole('button', { name: '重放并刷新' }).click()

    await expect(panel.getByRole('region', { name: '回放比对回执' })).toContainText('冻结执行结果不一致')
    await expect(panel.getByText('不一致项：随机对照、OOS 阶段')).toBeVisible()
    await expect(page.locator('.el-message').filter({ hasText: '回放完成，但以下结果与冻结执行不一致' })).toBeVisible()
  })
})
