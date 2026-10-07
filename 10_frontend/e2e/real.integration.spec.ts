import { expect, test, type Page } from '@playwright/test'

test.skip(process.env.VITE_API_MODE !== 'real', '仅在 VITE_API_MODE=real 时运行真实接口浏览器验收')

async function loginAsSyntheticStudent(page: Page) {
  await page.goto('/login')
  await page.getByRole('radio', { name: '学生' }).click()
  await page.getByLabel('演示账号').fill('student_a')
  await page.getByLabel('演示密码').fill('synthetic-student-a')
  await page.getByRole('button', { name: '进入工作区' }).click()
  await expect(page).toHaveURL(/\/student\/home$/)
}

async function createBrowserCrisisSupport(page: Page) {
  return page.evaluate(async ({ backendUrl }) => {
    type Envelope<T> = { data: T }
    type AssessmentState = {
      assessment_id: string
      can_complete: boolean
      current_item: { item_id: string; options?: Array<{ value: string }> } | null
    }
    type CurrentActor = { subject_id: string | null }
    type SupportResult = {
      status: string
      safety_action: string
      normal_generation: boolean
      content: unknown
      review_reference: string | null
      integration_labels: Record<string, string>
    }

    const request = async <T>(
      path: string,
      init: RequestInit = {},
    ): Promise<{ response: Response; body: Envelope<T> }> => {
      const response = await fetch(`${backendUrl}${path}`, {
        ...init,
        credentials: 'include',
      })
      const body = (await response.json()) as Envelope<T>
      if (!response.ok) {
        throw new Error(`${init.method ?? 'GET'} ${path} -> ${response.status}`)
      }
      return { response, body }
    }

    const csrfResponse = await request<{ csrf_token: string }>('/api/v1/auth/csrf')
    const csrf = csrfResponse.body.data.csrf_token
    const actorResponse = await request<CurrentActor>('/api/v1/auth/me')
    const subjectId = actorResponse.body.data.subject_id
    if (!subjectId) throw new Error('Authenticated student has no bound subject')
    const keyPrefix = `browser-crisis-${crypto.randomUUID()}`
    const jsonHeaders = (idempotencyKey: string) => ({
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrf,
      'Idempotency-Key': idempotencyKey,
    })
    const created = await request<{ assessment_id: string }>('/api/v1/assessments', {
      method: 'POST',
      headers: jsonHeaders(`${keyPrefix}-create`),
      body: JSON.stringify({
        subject_id: subjectId,
        instrument_id: 'CURRENT_SYNTHETIC_GRM',
        instrument_version: 'synthetic_item_bank.v1 / demo.v1',
      }),
    })
    const assessmentId = created.body.data.assessment_id

    for (let index = 0; index < 12; index += 1) {
      const stateResponse = await request<AssessmentState>(
        `/api/v1/assessments/${assessmentId}/state`,
      )
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
    return support.body.data
  }, { backendUrl: 'http://127.0.0.1:8080' })
}

test('真实接口：登录 → CAT → 结果 → 支持报告 → 刷新后历史可见', async ({ page }) => {
  test.setTimeout(180_000)
  await loginAsSyntheticStudent(page)
  await expect(page.getByText('还没有测评记录。开始后，记录会由服务端保存。')).toBeVisible()

  await page.getByRole('button', { name: '开始测评' }).click()
  await expect(page.getByText('第 1 题 · 测评进行中')).toBeVisible()

  const completeButton = page.getByRole('button', { name: /完成并查看结构/ })
  for (let index = 0; index < 8; index += 1) {
    if (await completeButton.isVisible()) break
    await page.getByRole('radio').first().click()
    await page.getByRole('button', { name: /保存并继续/ }).click()
    if (await completeButton.isVisible()) break
    await expect(page.locator('.assessment-meta p')).toContainText(new RegExp(`第 ${index + 2} 题|测评项目已完成`))
  }

  await expect(completeButton).toBeEnabled({ timeout: 10_000 })
  await completeButton.click()
  await expect(page).toHaveURL(/\/student\/assessment\/ASSESS_.*\/result/, { timeout: 120_000 })
  await expect(page.getByRole('heading', { name: '本次合成测评已完成' })).toBeVisible({ timeout: 120_000 })
  await expect(page.locator('body')).not.toContainText('theta')
  await page.getByRole('button', { name: /进入 AI 支持对话/ }).click()
  await page.getByLabel('你的问题').fill('请给我一个今天可以开始的教育支持小步骤。')
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page.getByText('服务端回答')).toBeVisible({ timeout: 120_000 })
  await expect(page.locator('.support-turn__citations a').first()).toBeVisible()
  await expect(page.locator('.support-turn__saved')).toContainText('记录已返回')
  await page.reload()
  await expect(page.getByText('报告与对话历史')).toBeVisible()
  await expect(page.getByText(/REPORT_/).first()).toBeVisible()
})

test('真实接口：浏览器上下文危机路由保留 CSRF 与安全边界', async ({ page }) => {
  test.setTimeout(180_000)
  await loginAsSyntheticStudent(page)

  const result = await createBrowserCrisisSupport(page)
  expect(result.status).toBe('needs_review')
  expect(result.safety_action).toBe('CRISIS_ROUTE')
  expect(result.normal_generation).toBe(false)
  expect(result.content).toBeNull()
  expect(result.review_reference).toMatch(/^REVIEW_/)
  expect(result.integration_labels).toEqual({
    CAT: 'REAL_HTTP',
    RAG: 'REAL_HTTP',
    LLM_RUNTIME: 'REAL_HTTP',
    SAFETY: 'REAL_HTTP',
  })
})

test('真实接口：Safety 不可用时页面保留可恢复的错误状态', async ({ page }) => {
  test.skip(process.env.VITE_RUN_SAFETY_DOWN !== '1', '仅在 Safety-down 专项环境运行')
  test.setTimeout(60_000)
  await loginAsSyntheticStudent(page)
  await page.getByRole('button', { name: '开始测评' }).click()
  await expect(page.getByText('第 1 题 · 测评进行中')).toBeVisible()

  const completeButton = page.getByRole('button', { name: /完成并查看结构/ })
  for (let index = 0; index < 8; index += 1) {
    if (await completeButton.isVisible()) break
    await page.getByRole('radio').first().click()
    await page.getByRole('button', { name: /保存并继续/ }).click()
    if (await completeButton.isVisible()) break
    await expect(page.locator('.assessment-meta p')).toContainText(new RegExp(`第 ${index + 2} 题|测评项目已完成`))
  }

  await expect(completeButton).toBeEnabled({ timeout: 10_000 })
  await completeButton.click()
  await expect(page).toHaveURL(/\/student\/assessment\/ASSESS_.*\/result/, { timeout: 120_000 })
  await page.getByRole('button', { name: /进入 AI 支持对话/ }).click()
  await page.getByLabel('你的问题').fill('请提供一个演示支持建议。')
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page.getByText('请求或历史记录未能加载')).toBeVisible({ timeout: 10_000 })
})
