import { expect, test, type Page } from '@playwright/test'

test.skip(process.env.VITE_API_MODE !== 'real', '仅在 VITE_API_MODE=real 时运行真实接口浏览器验收')

test.describe.configure({ mode: 'serial' })

type SupportResult = {
  status: string
  safety_action: string
  normal_generation: boolean
  generation: {
    provenance: {
      retrieval_id: string
      model_id: string | null
      generation_status: string
      candidate_source: string
    }
  }
  report_id: string
  content: unknown
  citations: Array<{ citation_id: string; chunk_id?: string | null }>
  review_reference: string | null
  integration_labels: Record<string, string>
}

type BrowserCrisisResult = SupportResult & {
  request_trace: string
}

function collectBrowserDiagnostics(page: Page) {
  const errors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(`console: ${message.text()}`)
  })
  page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`))
  return errors
}

async function assertBrowserDiagnostics(errors: string[]) {
  expect(errors, `浏览器运行时错误：${errors.join(' | ')}`).toEqual([])
}

async function loginAsSynthetic(page: Page, role: 'student' | 'reviewer') {
  await page.goto('/login')
  await page.getByRole('radio', { name: role === 'student' ? '学生' : '复核员' }).click()
  await page.getByLabel('演示账号').fill(role === 'student' ? 'student_a' : 'reviewer')
  await page.getByLabel('演示密码').fill(role === 'student' ? 'synthetic-student-a' : 'synthetic-reviewer')
  await page.getByRole('button', { name: '进入工作区' }).click()
  await expect(page).toHaveURL(new RegExp(role === 'student' ? '/student/home$' : '/reviewer/queue$'))
}

async function assertSessionBoundary(page: Page) {
  const cookies = await page.context().cookies()
  const sessionCookie = cookies.find((cookie) => cookie.name === 'smhai_dev_session')
  expect(sessionCookie, '登录后应存在服务端会话 Cookie').toBeTruthy()
  expect(sessionCookie?.httpOnly, '会话 Cookie 必须保持 HttpOnly').toBe(true)
  expect(sessionCookie?.sameSite).toBe('Lax')

  const browserState = await page.evaluate(() => ({
    documentCookie: document.cookie,
    storage: Object.entries(window.localStorage).map(([key, value]) => `${key}=${value}`),
  }))
  expect(browserState.documentCookie).not.toContain('smhai_dev_session')
  expect(browserState.storage.join('\n')).not.toMatch(/session|token/i)
}

async function completeStudentAssessment(page: Page) {
  await page.getByRole('button', { name: '开始测评' }).click()
  await expect(page.getByText('第 1 题 · 测评进行中')).toBeVisible()

  const completeButton = page.getByRole('button', { name: /完成并查看结构/ })
  for (let index = 0; index < 12; index += 1) {
    if (await completeButton.isVisible()) break
    const selectedOption = page.getByRole('radio').first()
    await selectedOption.click()
    await expect(selectedOption).toBeChecked()
    const saveButton = page.getByRole('button', { name: /保存并继续/ })
    await expect(saveButton).toBeEnabled({ timeout: 10_000 })
    await saveButton.click()
    await page.waitForFunction(() => !Array.from(document.querySelectorAll('button')).some((item) => item.getAttribute('aria-busy') === 'true'))
    if (await completeButton.isVisible()) break
  }
  await expect(completeButton).toBeEnabled({ timeout: 10_000 })
  await completeButton.click()
}

async function createBrowserCrisisSupport(page: Page): Promise<BrowserCrisisResult> {
  return page.evaluate(async ({ backendUrl }) => {
    type Envelope<T> = { data: T; trace_id?: string }
    type AssessmentState = {
      assessment_id: string
      can_complete: boolean
      current_item: { item_id: string; options?: Array<{ value: string }> } | null
    }

    const request = async <T>(path: string, init: RequestInit = {}) => {
      const response = await fetch(`${backendUrl}${path}`, {
        ...init,
        credentials: 'include',
      })
      const body = (await response.json()) as Envelope<T>
      if (!response.ok) throw new Error(`${init.method ?? 'GET'} ${path} -> ${response.status}`)
      return { response, body }
    }

    const csrfResponse = await request<{ csrf_token: string }>('/api/v1/auth/csrf')
    const csrf = csrfResponse.body.data.csrf_token
    const keyPrefix = `browser-crisis-closure-${crypto.randomUUID()}`
    const jsonHeaders = (idempotencyKey: string) => ({
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrf,
      'Idempotency-Key': idempotencyKey,
    })
    const created = await request<{ assessment_id: string }>('/api/v1/assessments', {
      method: 'POST',
      headers: jsonHeaders(`${keyPrefix}-create`),
      body: JSON.stringify({
        subject_id: 'SYNTHETIC_STUDENT_DEMO',
        instrument_id: 'CURRENT_SYNTHETIC_GRM',
        instrument_version: 'synthetic_item_bank.v1 / demo.v1',
      }),
    })
    const assessmentId = created.body.data.assessment_id

    for (let index = 0; index < 12; index += 1) {
      const stateResponse = await request<AssessmentState>(`/api/v1/assessments/${assessmentId}/state`)
      const state = stateResponse.body.data
      if (!state.current_item) {
        if (state.can_complete) break
        throw new Error(`CAT stopped without can_complete at step ${index}`)
      }
      const value = state.current_item.options?.[0]?.value
      if (!value) throw new Error('CAT item has no response option')
      await request(`/api/v1/assessments/${assessmentId}/responses`, {
        method: 'POST',
        headers: jsonHeaders(`${keyPrefix}-response-${index}`),
        body: JSON.stringify({ item_id: state.current_item.item_id, response: value }),
      })
    }

    await request(`/api/v1/assessments/${assessmentId}/complete`, {
      method: 'POST',
      headers: jsonHeaders(`${keyPrefix}-complete`),
      body: JSON.stringify({}),
    })
    const support = await request<SupportResult>('/api/v1/support/requests', {
      method: 'POST',
      headers: jsonHeaders(`${keyPrefix}-support`),
      body: JSON.stringify({
        assessment_id: assessmentId,
        target_role: 'student',
        message: 'SYNTHETIC_CRISIS_SIGNAL',
        language: 'zh-CN',
        purpose: 'education_support',
      }),
    })
    return {
      ...support.body.data,
      request_trace: support.body.trace_id || '',
    }
  }, { backendUrl: 'http://127.0.0.1:8080' })
}

async function readReport(page: Page, reportId: string) {
  return page.evaluate(async ({ backendUrl, id }) => {
    const response = await fetch(`${backendUrl}/api/v1/reports/${id}`, { credentials: 'include' })
    return { status: response.status, body: await response.json() as { data: Record<string, any> } }
  }, { backendUrl: 'http://127.0.0.1:8080', id: reportId })
}

test('闭环登录：服务端会话保持 HttpOnly，前端不持有会话令牌', async ({ page }) => {
  const errors = collectBrowserDiagnostics(page)
  await loginAsSynthetic(page, 'student')
  await assertSessionBoundary(page)
  await expect(page.getByRole('heading', { name: '合成演示工作区' })).toBeVisible()
  await assertBrowserDiagnostics(errors)
})

test('闭环正常支持：真实接口返回执行来源、引用并在页面展示', async ({ page }) => {
  test.setTimeout(180_000)
  const errors = collectBrowserDiagnostics(page)
  await loginAsSynthetic(page, 'student')
  await assertSessionBoundary(page)

  const supportResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith('/api/v1/support/requests') && response.request().method() === 'POST',
    { timeout: 150_000 },
  )
  await completeStudentAssessment(page)
  await page.getByRole('button', { name: /进入 AI 支持对话/ }).click()
  await page.getByLabel('你的问题').fill('请给我一个今天可以开始的教育支持小步骤。')
  await page.getByRole('button', { name: '发送' }).click()
  const supportResponse = await supportResponsePromise
  expect(supportResponse.status()).toBe(202)
  const supportEnvelope = (await supportResponse.json()) as { data: SupportResult }
  const support = supportEnvelope.data
  expect(support.integration_labels).toEqual({
    CAT: 'REAL_HTTP',
    RAG: 'REAL_HTTP',
    LLM_RUNTIME: 'REAL_HTTP',
    SAFETY: 'REAL_HTTP',
  })
  expect(support.citations.length).toBeGreaterThanOrEqual(3)
  expect(support.generation.provenance.generation_status).toBe('EXECUTED')
  expect(support.generation.provenance.candidate_source).toBe('MODEL_EXECUTED')
  expect(support.generation.provenance.retrieval_id).toMatch(/^RETR_/)
  expect(support.generation.provenance.model_id).toMatch(/^MODEL_/)

  await expect(page).toHaveURL(/\/student\/support\?assessment=ASSESS_/, { timeout: 120_000 })
  await expect(page.getByText('服务端回答')).toBeVisible({ timeout: 120_000 })
  await expect(page.locator('.support-turn__citations a')).toHaveCount(support.citations.length)
  await expect(page.locator('body')).not.toContainText('theta')

  const report = await readReport(page, support.report_id)
  expect(report.status).toBe(200)
  expect(report.body.data.citations.length).toBe(support.citations.length)
  expect(report.body.data.generation.provenance.generation_status).toBe('EXECUTED')
  expect(report.body.data.generation.provenance.retrieval_id).toBe(support.generation.provenance.retrieval_id)
  await assertBrowserDiagnostics(errors)
})

test('闭环危机路由：安全决策后不执行普通检索和生成', async ({ page }) => {
  test.setTimeout(180_000)
  const errors = collectBrowserDiagnostics(page)
  await loginAsSynthetic(page, 'student')
  await assertSessionBoundary(page)

  const result = await createBrowserCrisisSupport(page)
  expect(result.status).toBe('needs_review')
  expect(result.safety_action).toBe('CRISIS_ROUTE')
  expect(result.normal_generation).toBe(false)
  expect(result.content).toBeNull()
  expect(result.citations).toHaveLength(0)
  expect(result.review_reference).toMatch(/^REVIEW_/)
  expect(result.integration_labels).toEqual({
    CAT: 'REAL_HTTP',
    RAG: 'REAL_HTTP',
    LLM_RUNTIME: 'REAL_HTTP',
    SAFETY: 'REAL_HTTP',
  })
  expect(result.generation.provenance.generation_status).toBe('NOT_RUN')
  expect(result.generation.provenance.candidate_source).toBe('NOT_RUN')
  expect(result.generation.provenance.retrieval_id).toBe('RETR_not_run')
  expect(result.generation.provenance.model_id).toBeNull()
  expect(result.request_trace).toMatch(/^TRACE_/)
  await assertBrowserDiagnostics(errors)
})

test('闭环复核：复核员读取危机记录并完成通过动作', async ({ page }) => {
  test.setTimeout(180_000)
  const errors = collectBrowserDiagnostics(page)
  await loginAsSynthetic(page, 'student')
  const pending = await createBrowserCrisisSupport(page)
  expect(pending.review_reference).toMatch(/^REVIEW_/)

  await loginAsSynthetic(page, 'reviewer')
  await expect(page.getByRole('heading', { name: '复核队列' })).toBeVisible()
  const caseRow = page.getByTestId(`review-case-${pending.review_reference}`)
  await expect(caseRow).toBeVisible({ timeout: 30_000 })
  await caseRow.click()
  await expect(page.getByText('当前授权范围')).toBeVisible()
  await expect(page.getByText('普通生成不是当前下一步')).toBeVisible()
  await expect(page.getByRole('button', { name: /生成/ })).toHaveCount(0)

  await page.getByRole('button', { name: '通过' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('button', { name: '确认通过' }).click()
  await expect(page.getByRole('heading', { name: '本次复核已完成' })).toBeVisible()
  await expect(page.getByText('复核已通过')).toBeVisible()

  const report = await readReport(page, pending.report_id)
  expect(report.status).toBe(200)
  expect(report.body.data.review_status).toBe('approved')
  await assertBrowserDiagnostics(errors)
})
