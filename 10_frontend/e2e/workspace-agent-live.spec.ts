/* global HTMLImageElement, HTMLTextAreaElement */
import { Buffer } from 'node:buffer'
import { readFile } from 'node:fs/promises'
import { URL } from 'node:url'
import { expect, test, type Page } from '@playwright/test'
import { workbook } from '../tests/fixtures/workbook'
import { readSchoolFeedbackContent } from '../src/services/school-feedback-content'

const origin = process.env.PSYNOVA_AGENT_QA_ORIGIN
const account = process.env.PSYNOVA_AGENT_QA_USERNAME
const password = process.env.PSYNOVA_AGENT_QA_PASSWORD

type Role = 'ADMIN' | 'TEACHER' | 'STUDENT' | 'PSYCHOLOGICAL_SPECIALIST'
type SchoolContext = { role: Role; school_ref: string }

test.skip(!origin || !account || !password, 'Requires an isolated synthetic school QA account')
test.use({ trace: 'off', screenshot: 'off', video: 'off' })

async function signIn(page: Page) {
  await page.goto(origin + '/login')
  await page.getByRole('textbox', { name: '账号', exact: true }).fill(account!)
  await page.getByRole('textbox', { name: '密码', exact: true }).fill(password!)
  const login = page.waitForResponse((response) => response.url().endsWith('/api/v1/auth/login'))
  await page.getByRole('button', { name: '登录', exact: true }).click()
  expect((await login).ok()).toBe(true)
}

async function chooseRole(page: Page, role: Role, workspace: string) {
  await page.goto(origin + '/api/v1/auth/public-demo')
  const session = await page.request.get(origin + '/api/v1/auth/me')
  const contexts = (await session.json()).data.available_contexts as SchoolContext[]
  const context = contexts.find((entry) => entry.role === role && entry.school_ref.startsWith('PUBLICDEMO_'))
  expect(Boolean(context), 'The chosen role must belong to a synthetic school').toBe(true)
  const token = await page.request.get(origin + '/api/v1/auth/csrf')
  const response = await page.request.post(origin + '/api/v1/auth/active-context', {
    headers: { Origin: origin!, 'X-CSRF-Token': (await token.json()).data.csrf_token },
    data: { role, school_ref: context!.school_ref },
  })
  expect(response.ok()).toBe(true)
  await page.goto(origin + workspace)
}

async function ask(page: Page, prompt: string, label: string, consentRequired = true) {
  await page.locator('#workspace-agent-input').fill(prompt)
  const pending = page.waitForResponse((response) => response.url().endsWith('/workspace-agent/conversation/turn'), {
    timeout: 40_000,
  })
  await page.getByRole('button', { name: label }).click()
  if (consentRequired) {
    await page.getByRole('button', { name: '同意并发送' }).click({ timeout: 10_000 })
  }
  const response = await pending
  expect(response.ok()).toBe(true)
  await expect(page.getByRole('button', { name: '取消任务' })).toHaveCount(0, { timeout: 100_000 })
  const history = await page.request.get(origin + '/api/v1/workspace-agent/conversation')
  expect(history.ok()).toBe(true)
  const { events } = (await history.json()).data
  const newestRun = events.at(-1)?.run_id
  return events.filter((event: { run_id: string }) => event.run_id === newestRun)
}

function textPdf(text: string): Buffer {
  const stream = `BT /F1 12 Tf 72 700 Td (${text}) Tj ET\n`
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}endstream`,
  ]
  let pdf = '%PDF-1.4\n'
  const offsets = objects.map((object, index) => {
    const offset = Buffer.byteLength(pdf)
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`
    return offset.toString().padStart(10, '0') + ' 00000 n \n'
  })
  const start = Buffer.byteLength(pdf)
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.join('')}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`
  return Buffer.from(pdf)
}

test('the public learner and teacher use live tools under their own roles', async ({ page }) => {
  test.setTimeout(180_000)
  await signIn(page)
  await chooseRole(page, 'STUDENT', '/student/workspace')
  const liveTasks = await page.request.get(origin + '/api/v1/school/tasks/student')
  expect(liveTasks.ok()).toBe(true)
  const actualTaskCount = (await liveTasks.json()).data.length
  const student = await ask(page, '查一下我现在能做的测评任务。', '发送消息')
  expect(student.find((event) => event.view?.kind === 'student_tasks')?.view.total).toBe(actualTaskCount)
  await expect(page.getByText(/我的测评任务 · /).last()).toBeVisible()
  await page.reload()
  await expect(page.getByText(/我的测评任务 · /).last()).toBeVisible()
  await chooseRole(page, 'TEACHER', '/teacher/workspace')
  const teacher = await ask(page, '查一下授权班级已有的测评以及完成进度。', '发送任务')
  expect(teacher.some((event) => event.view?.kind === 'class_progress')).toBe(true)
  expect(teacher.some((event) => event.view?.kind === 'student_tasks')).toBe(false)
  await expect(page.getByText(/授权班级测评进度 · /).last()).toBeVisible()
})

test('the learner retrieves published education on demand and keeps arithmetic independent', async ({ page }) => {
  test.setTimeout(180_000)
  await signIn(page)
  await chooseRole(page, 'STUDENT', '/student/workspace')
  const education = await ask(page, '学习压力这方面，PsyNova 有哪篇科普可以看看？', '发送消息')
  expect(education.find((event) => event.view?.kind === 'education_articles')?.view.topics).toContain('stress')
  const summary = page.getByText('忙不过来时，先找一个能做的小步骤', { exact: true }).last()
  await summary.click()
  await expect(page.getByRole('link', { name: '世界卫生组织｜压力', exact: true }).last())
    .toHaveAttribute('href', 'https://www.who.int/zh/news-room/questions-and-answers/item/stress')
  await page.reload()
  await expect(summary).toBeVisible()
  const math = await ask(page, '算一下 23 加 19，直接给出答案', '发送消息')
  expect(math.some((event) => event.view?.kind === 'education_articles')).toBe(false)
  expect(math.find((event) => event.type === 'answer')?.text).toContain('42')
})

test('the teacher combines verified class counts and education material in a classroom task', async ({ page }) => {
  test.setTimeout(180_000)
  await signIn(page)
  await chooseRole(page, 'TEACHER', '/teacher/workspace')
  const rawProgress = await page.request.get(origin + '/api/v1/school/teacher/task-progress')
  expect(rawProgress.ok()).toBe(true)
  const tasks = (await rawProgress.json()).data as { completed_count: number; active_enrollment_count: number }[]
  const completions = tasks.reduce((sum, task) => sum + task.completed_count, 0)
  const enrollments = tasks.reduce((sum, task) => sum + task.active_enrollment_count, 0)
  const report = await ask(page,
    '请给我可下载的班级测评进度简报，再参考平台关于学习压力的科普，另做一个五分钟班会活动的 Markdown 文件',
    '发送任务',
  )
  const progress = report.find((event) => event.view?.kind === 'class_progress')?.view
  expect(progress?.total).toBe(tasks.length)
  expect(progress?.artifact?.markdown).toContain(`已提交人次：${completions}\n`)
  expect(progress?.artifact?.markdown).toContain(`有效参测人次：${enrollments}\n`)
  expect(report.find((event) => event.view?.kind === 'education_articles')?.view.topics).toContain('stress')
  const activity = report.find((event) => event.view?.kind === 'markdown')?.view
  expect(activity?.markdown).toMatch(/班会|活动/)
  expect(activity?.markdown).toContain('世界卫生组织')
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: `下载 ${activity.filename}`, exact: true }).last().click()
  const document = await download
  expect(await readFile(await document.path(), 'utf8')).toBe(activity.markdown)
})

test('cancelling a live task releases the conversation and lets the teacher retry', async ({ page }) => {
  test.setTimeout(180_000)
  await signIn(page)
  await chooseRole(page, 'TEACHER', '/teacher/workspace')
  const progress = await page.request.get(origin + '/api/v1/school/teacher/task-progress')
  expect(progress.ok()).toBe(true)
  const expectedTasks = (await progress.json()).data.length
  await page.locator('#workspace-agent-input').fill('查一下我有权限查看的班级测评进度')
  await page.getByRole('button', { name: '发送任务', exact: true }).click()
  await page.getByRole('button', { name: '同意并发送' }).click()
  await expect(page.getByRole('status').filter({ hasText: /正在检查输入|正在处理任务/ })).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: '取消任务' }).click()

  const readHistory = async () => {
    const response = await page.request.get(origin + '/api/v1/workspace-agent/conversation')
    expect(response.ok()).toBe(true)
    return (await response.json()).data
  }
  await expect.poll(async () => {
    const history = await readHistory()
    return { active: history.active, status: history.events.at(-1)?.status }
  }, { timeout: 20_000 }).toEqual({ active: false, status: 'interrupted' })
  const interruptedRun = (await readHistory()).events.at(-1).run_id
  await page.getByRole('button', { name: '重试任务' }).click()
  await expect.poll(async () => {
    const history = await readHistory()
    const latest = history.events.at(-1)
    return latest?.run_id !== interruptedRun && latest?.type === 'end' && latest.status
  }, { timeout: 100_000 }).toBe('completed')
  const history = await readHistory()
  const finishedRun = history.events.at(-1).run_id
  const result = history.events.find((event) => event.run_id === finishedRun && event.view?.kind === 'class_progress')
  expect(result?.view.total).toBe(expectedTasks)
})

test('a teacher reconnects to the same live run after reloading the workplace', async ({ page }) => {
  test.setTimeout(180_000)
  await signIn(page)
  await chooseRole(page, 'TEACHER', '/teacher/workspace')
  const progress = await page.request.get(origin + '/api/v1/school/teacher/task-progress')
  expect(progress.ok()).toBe(true)
  const expectedTasks = (await progress.json()).data.length
  let starts = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/workspace-agent/conversation/turn')) starts += 1
  })
  const readHistory = async () => {
    const response = await page.request.get(origin + '/api/v1/workspace-agent/conversation')
    expect(response.ok()).toBe(true)
    return (await response.json()).data
  }
  await page.locator('#workspace-agent-input').fill('核对我当前班级测评任务的完成进度，给我业务查询结果')
  await page.getByRole('button', { name: '发送任务', exact: true }).click()
  await page.getByRole('button', { name: '同意并发送' }).click()
  await expect(page.getByRole('status').filter({ hasText: /正在检查输入|正在处理任务/ })).toBeVisible({ timeout: 30_000 })
  const running = await readHistory()
  expect(running.active).toBe(true)
  expect(running.active_run_id).toMatch(/^[0-9a-f]{32}$/)

  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect.poll(async () => {
    const state = await readHistory()
    return state.events.at(-1)
  }, { timeout: 100_000 }).toMatchObject({ type: 'end', status: 'completed', run_id: running.active_run_id })
  await expect(page.getByText(`授权班级测评进度 · ${expectedTasks} 项`, { exact: true }).last()).toBeVisible()
  await expect(page.getByRole('button', { name: '取消任务' })).toHaveCount(0, { timeout: 100_000 })
  const finished = await readHistory()
  const runId = running.active_run_id
  expect(finished.active_run_id).toBeNull()
  expect(finished.events.at(-1)).toMatchObject({ type: 'end', status: 'completed', run_id: runId })
  const results = finished.events.filter((event) => event.run_id === runId && event.view?.kind === 'class_progress')
  expect(results).toHaveLength(1)
  expect(results[0].view.total).toBe(expectedTasks)
  expect(starts).toBe(1)
})

test('an urgent synthetic learner message goes through school safety before any model tool', async ({ page }) => {
  test.setTimeout(180_000)
  await signIn(page)
  await chooseRole(page, 'STUDENT', '/student/workspace')
  const message = '我现在想自杀，已经有了具体计划'
  const events = await ask(page, message, '发送消息')
  expect(events.at(-1)).toMatchObject({ type: 'end', status: 'blocked' })
  expect(events.some((event) => event.type === 'safety' && event.support)).toBe(true)
  expect(events.some((event) => ['user', 'answer', 'tool_started', 'tool_result'].includes(event.type))).toBe(false)
  expect(JSON.stringify(events)).not.toContain(message)
  await expect(page.getByRole('button', { name: '打开学生支持对话' }).last()).toBeVisible()
})

test('published school feedback is read in the learner conversation over the private route', async ({ page }) => {
  test.skip(process.env.PSYNOVA_AGENT_QA_FEEDBACK !== '1', 'Requires an approved fixture in the synthetic learner account')
  test.setTimeout(180_000)
  await signIn(page)
  await chooseRole(page, 'STUDENT', '/student/workspace')
  const list = await page.request.get(origin + '/api/v1/school/feedback/student')
  expect(list.ok()).toBe(true)
  const available = (await list.json()).data
  expect(available.total).toBeGreaterThan(0)
  const current = available.items[0]
  expect(current.status).toBe('PUBLISHED')
  const completed = await page.request.get(origin + '/api/v1/school/tasks/student/history')
  expect(completed.ok()).toBe(true)
  const task = (await completed.json()).data.find((row: { assessment_id: string }) => row.assessment_id === current.assessment_ref)
  expect(task?.task_ref).toBeTruthy()
  const taskPath = '/api/v1/workspace-agent/conversation/task-feedback/' + task.task_ref
  const linked = await page.request.get(origin + taskPath)
  expect(linked.ok()).toBe(true)
  expect(linked.headers()['cache-control']).toBe('no-store')
  expect((await linked.json()).data).toEqual({ feedback_ref: current.feedback_ref })
  const reviewed = readSchoolFeedbackContent(current.body)
  if (process.env.PSYNOVA_AGENT_QA_FEEDBACK_STEPS === '1') expect(reviewed.nextSteps).toBeTruthy()
  const tasks = await ask(page, '查一下已发布的学校反馈，打开最新的一份', '发送消息')
  const resultKinds = tasks.map((event) => event.view?.kind ?? event.code ?? event.type)
  expect(resultKinds).toContain('feedback_picker')
  expect(tasks.find((event) => event.view?.kind === 'feedback_picker')?.view.feedback_ref).toBe(current.feedback_ref)
  await page.reload()
  const history = await page.request.get(origin + '/api/v1/workspace-agent/conversation')
  expect(history.ok()).toBe(true)
  const savedText = await history.text()
  expect(savedText).not.toContain(current.title)
  expect(savedText).not.toContain(current.body)
  const privateRead = page.waitForResponse((reply) => reply.url().endsWith('/school/feedback/student/' + current.feedback_ref))
  await page.getByRole('button', { name: '在会话中阅读反馈' }).last().click()
  const result = await privateRead
  expect(result.ok()).toBe(true)
  expect(result.headers()['cache-control']).toBe('no-store')
  await expect(page.getByRole('heading', { name: current.title, exact: true })).toBeVisible()
  await expect(page.getByText(reviewed.body, { exact: true })).toBeVisible()
  await expect(page).toHaveURL(origin + '/student/workspace')
  await page.getByText('怎么读这份反馈', { exact: true }).click()
  if (reviewed.nextSteps) {
    await expect(page.getByRole('heading', { name: '老师建议的下一步' })).toBeVisible()
    await expect(page.getByText(reviewed.nextSteps, { exact: true })).toBeVisible()
  }
  const guidePath = '/api/v1/workspace-agent/conversation/feedback-guide/' + current.feedback_ref
  const verifyGuide = process.env.PSYNOVA_AGENT_QA_FEEDBACK_GUIDE === '1'
  const measurementPath = '/api/v1/workspace-agent/conversation/feedback-measurement/' + current.feedback_ref
  const verifyMeasurement = process.env.PSYNOVA_AGENT_QA_FEEDBACK_MEASUREMENT === '1'
  if (verifyMeasurement) {
    await page.setViewportSize({ width: 390, height: 840 })
    const official = await page.request.get(origin + '/api/v1/assessments/' + current.assessment_ref)
    expect(official.ok()).toBe(true)
    const stored = (await official.json()).data
    const transcript = (await (await page.request.get(origin + '/api/v1/workspace-agent/conversation')).json()).data.events
    const response = page.waitForResponse((reply) => reply.url().endsWith(measurementPath))
    await page.getByRole('button', { name: '查看本次测量记录' }).click()
    const reply = await response
    expect(reply.ok()).toBe(true)
    expect(reply.request().method()).toBe('GET')
    expect(reply.headers()['cache-control']).toBe('private, no-store')
    const projection = (await reply.json()).data
    const dimensions = Object.entries(stored.dimensions as Record<string, {
      theta: number | null; se: number | null; score: number | null; interpretation_status: string
    }>)
    expect(dimensions.some(([, value]) => value.interpretation_status === 'estimated')).toBe(true)
    expect(dimensions.every(([, value]) => value.score === null)).toBe(true)
    expect(projection).toEqual({
      status: 'engineering',
      completed_at: stored.timestamps.completed_at,
      answered_count: stored.response_summary.items_answered,
      item_bank_version: stored.provenance.item_bank_version,
      dimensions: dimensions.map(([label, value]) => ({
        label,
        estimate: value.interpretation_status === 'estimated' ? value.theta : null,
        standard_error: value.interpretation_status === 'estimated' && value.theta !== null ? value.se : null,
      })),
    })
    await expect(page.getByRole('heading', { name: '本次测量记录', exact: true })).toBeVisible()
    for (const item of projection.dimensions) {
      const result = page.locator('.feedback-measurement__dimension').filter({
        has: page.getByText(item.label, { exact: true }),
      })
      await expect(result.getByText(String(item.estimate ?? '数据不足'), { exact: true }).first()).toBeVisible()
      await expect(result.getByText(String(item.standard_error ?? '记录未提供'), { exact: true }).first()).toBeVisible()
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391)
    const afterMeasurement = await page.request.get(origin + '/api/v1/workspace-agent/conversation')
    expect((await afterMeasurement.json()).data.events).toEqual(transcript)
    const absent = await page.request.get(origin + measurementPath + '_missing')
    expect(absent.status()).toBe(404)
  }
  if (verifyGuide) {
    await page.setViewportSize({ width: 390, height: 840 })
    const writes: string[] = []
    page.on('request', (request) => {
      if (request.method() === 'POST') writes.push(new URL(request.url()).pathname)
    })
    const question = '想请学校老师解释，我该从哪里联系'
    await page.getByRole('button', { name: '在这份反馈里查找' }).click()
    const field = page.getByRole('textbox', { name: '你想确认什么' })
    const lookup = async (query: string) => {
      await field.fill(query)
      const response = page.waitForResponse((reply) => reply.url().endsWith(guidePath))
      await page.getByRole('button', { name: '查找相关原文' }).click()
      const result = await response
      expect(result.ok()).toBe(true)
      expect(result.headers()['cache-control']).toContain('no-store')
      expect(result.request().postDataJSON()).toEqual({ content_revision: current.content_revision, question: query })
      return (await result.json()).data
    }
    const found = await lookup(question)
    expect(found.status).toBe('matched')
    expect(found.excerpts.length).toBeGreaterThan(0)
    expect(found.excerpts[0].source).toBe('next_steps')
    expect(reviewed.nextSteps).toContain(found.excerpts[0].text)
    expect(found.excerpts.every((item: { text: string }) => current.body.includes(item.text))).toBe(true)
    await expect(page.getByText('老师建议原文', { exact: true })).toBeVisible()

    expect(await lookup('三角形的面积公式是什么')).toEqual({ status: 'unmatched', excerpts: [] })
    await expect(page.getByText('这份反馈没有找到能直接对应你问题的原句')).toBeVisible()
    expect(await lookup('我现在想自杀，已经有了具体计划')).toEqual({ status: 'needs_support', excerpts: [] })
    await expect(page.getByText('可以请学校心理教师继续协助你')).toBeVisible()
    expect(writes).toEqual([guidePath, guidePath, guidePath])
    const afterGuide = await page.request.get(origin + '/api/v1/workspace-agent/conversation')
    const transcript = await afterGuide.text()
    expect(transcript).not.toContain(question)
    expect(transcript).not.toContain(JSON.stringify(current.body).slice(1, -1))
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391)
  }
  await page.getByRole('button', { name: '查看学校支持' }).click()
  await expect(page.getByRole('heading', { name: '提交求助请求' })).toBeVisible()
  await expect(page).toHaveURL(origin + '/student/workspace')
  await chooseRole(page, 'TEACHER', '/teacher/workspace')
  const denied = await page.request.get(origin + '/api/v1/school/feedback/student/' + current.feedback_ref)
  expect(denied.status()).toBe(403)
  expect((await page.request.get(origin + taskPath)).status()).toBe(403)
  if (verifyMeasurement) expect((await page.request.get(origin + measurementPath)).status()).toBe(403)
  if (verifyGuide) {
    const csrf = await page.request.get(origin + '/api/v1/auth/csrf')
    const forbidden = await page.request.post(origin + guidePath, {
      headers: { Origin: origin!, 'X-CSRF-Token': (await csrf.json()).data.csrf_token },
      data: { content_revision: current.content_revision, question: '查找已发布反馈原文' },
    })
    expect(forbidden.status()).toBe(403)
  }
  if (verifyMeasurement) {
    await chooseRole(page, 'PSYCHOLOGICAL_SPECIALIST', '/specialist/workspace')
    expect((await page.request.get(origin + measurementPath)).status()).toBe(403)
  }
})

test('a learner asks the school to clarify the exact published feedback revision', async ({ page }) => {
  test.skip(process.env.PSYNOVA_AGENT_QA_WRITE !== '1' || process.env.PSYNOVA_AGENT_QA_FEEDBACK !== '1', 'Requires a dedicated synthetic school and published feedback')
  test.setTimeout(200_000)
  await signIn(page)
  await chooseRole(page, 'STUDENT', '/student/workspace')
  const published = await page.request.get(origin + '/api/v1/school/feedback/student')
  expect(published.ok()).toBe(true)
  const feedback = (await published.json()).data.items[0]
  expect(feedback.status).toBe('PUBLISHED')
  const endpoint = '/api/v1/school/support/feedback-questions/' + feedback.feedback_ref
  const csrfHeaders = async (key: string) => {
    const csrf = await page.request.get(origin + '/api/v1/auth/csrf')
    return { Origin: origin!, 'X-CSRF-Token': (await csrf.json()).data.csrf_token, 'Idempotency-Key': key }
  }
  const question = `合成流程核对 ${Date.now()}，请说明我应该如何理解老师写的下一步`
  const badRevision = await page.request.post(origin + endpoint, {
    headers: await csrfHeaders(`qa-feedback-version-${Date.now()}`),
    data: { content_revision: feedback.content_revision + 1, question },
  })
  expect(badRevision.status()).toBe(409)

  const events = await ask(page, '请打开最新的已发布测评反馈，我想问学校老师该怎么理解', '发送消息')
  expect(events.find((event) => event.view?.kind === 'feedback_picker')?.view.feedback_ref).toBe(feedback.feedback_ref)
  await page.getByRole('button', { name: '在会话中阅读反馈' }).last().click()
  await page.getByText('怎么读这份反馈', { exact: true }).click()
  let writes = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith(endpoint)) writes += 1
  })
  await page.getByRole('button', { name: '请心理教师说明' }).click()
  const field = page.getByRole('textbox', { name: '你想确认什么' })
  await field.fill(question)
  expect(writes).toBe(0)
  const resultPromise = page.waitForResponse((response) => response.url().endsWith(endpoint))
  await page.getByRole('button', { name: '提交说明请求' }).click()
  const result = await resultPromise
  expect(result.status()).toBe(201)
  expect(result.headers()['cache-control']).toContain('no-store')
  expect(writes).toBe(1)
  const receipt = (await result.json()).data
  expect(receipt).toMatchObject({ source: 'STUDENT_REQUEST', status: 'SUBMITTED' })
  const payload = { content_revision: feedback.content_revision, question }
  expect(result.request().postDataJSON()).toEqual(payload)
  await expect(page.getByRole('status').filter({ hasText: '已提交说明请求' })).toBeVisible()
  const requestKey = (await result.request().allHeaders())['idempotency-key']
  expect(requestKey).toBeTruthy()
  const replay = await page.request.post(origin + endpoint, { headers: await csrfHeaders(requestKey), data: payload })
  expect(replay.status()).toBe(201)
  expect((await replay.json()).data.case_ref).toBe(receipt.case_ref)

  const casePath = '/api/v1/school/support/cases/' + receipt.case_ref
  const stored = await page.request.get(origin + casePath)
  expect(stored.status()).toBe(200)
  const exactQuestion = `请说明测评反馈第 ${feedback.content_revision} 版\n反馈编号 ${feedback.feedback_ref}\n\n${question}`
  expect((await stored.json()).data.content).toBe(exactQuestion)
  expect(exactQuestion).not.toContain(feedback.body)
  const history = await page.request.get(origin + '/api/v1/workspace-agent/conversation')
  const saved = await history.text()
  expect(saved).not.toContain(question)
  expect(saved).not.toContain(feedback.body)

  await chooseRole(page, 'TEACHER', '/teacher/workspace')
  expect((await page.request.get(origin + casePath)).status()).toBe(404)
  expect((await page.request.post(origin + endpoint, {
    headers: await csrfHeaders(`qa-feedback-teacher-${Date.now()}`), data: payload,
  })).status()).toBe(403)

  await chooseRole(page, 'PSYCHOLOGICAL_SPECIALIST', '/specialist/workspace')
  const available = await page.request.get(origin + casePath)
  expect(available.ok()).toBe(true)
  expect((await available.json()).data).toMatchObject({ status: 'SUBMITTED', content: null })
  const triaged = await page.request.post(origin + casePath + '/transitions', {
    headers: await csrfHeaders(`qa-feedback-accept-${Date.now()}`),
    data: { expected_version: receipt.state_version, target_status: 'TRIAGED' },
  })
  expect(triaged.ok()).toBe(true)
  expect((await triaged.json()).data).toMatchObject({ status: 'TRIAGED', content: exactQuestion })
})

test('a learner reads a synthetic worksheet image locally and asks the model about its text', async ({ page }) => {
  test.setTimeout(180_000)
  await signIn(page)
  await chooseRole(page, 'STUDENT', '/student/workspace')
  const image = await page.evaluate(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 820
    canvas.height = 340
    const context = canvas.getContext('2d')!
    context.fillStyle = 'white'
    context.fillRect(0, 0, canvas.width, canvas.height)
    context.fillStyle = 'black'
    context.font = '72px Arial'
    context.fillText('7 + 8', 80, 185)
    return canvas.toDataURL('image/png').split(',')[1]
  })
  const imageBuffer = Buffer.from(image, 'base64')
  const writes: string[] = []
  const workerRequests: string[] = []
  page.context().on('request', (request) => {
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) writes.push(new URL(request.url()).pathname)
    if (request.url().includes('/assets/ocr-v7/')) workerRequests.push(request.url())
  })
  await page.locator('#workspace-agent-composer input[type="file"]').setInputFiles({
    name: 'synthetic-worksheet.png', mimeType: 'image/png', buffer: imageBuffer,
  })
  const preview = page.getByRole('dialog', { name: '图片文字预览' })
  await expect(preview).toBeVisible({ timeout: 60_000 })
  await expect(preview.getByRole('textbox', { name: '识别出的文字' })).toHaveValue(/7\s*\+\s*8/)
  expect(writes).toEqual([])
  expect(workerRequests.some((url) => url.endsWith('/worker.min.js'))).toBe(true)
  expect(workerRequests.every((url) => new URL(url).origin === origin)).toBe(true)
  const composer = page.locator('#workspace-agent-input')
  await preview.getByRole('button', { name: '插入到输入框' }).click()
  const text = await composer.inputValue()
  const sent = page.waitForRequest((request) => request.url().endsWith('/workspace-agent/conversation/turn'))
  const reply = await ask(page, `给出这道算式的结果\n\n${text}`, '发送消息')
  expect((await sent).postDataJSON()).toEqual({ text: `给出这道算式的结果\n\n${text}`, synthetic_only: true })
  expect(reply.find((event) => event.type === 'answer')?.text).toMatch(/\b15\b|十五/)
})

test('a learner reads bar heights from an uploaded chart and sends only the reviewed estimates', async ({ page }) => {
  test.setTimeout(180_000)
  await signIn(page)
  await chooseRole(page, 'STUDENT', '/student/workspace')
  await page.setViewportSize({ width: 390, height: 840 })

  const writes: string[] = []
  page.context().on('request', (request) => {
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) writes.push(new URL(request.url()).pathname)
  })
  const uploadChart = async (includeZero: boolean) => {
    const image = await page.evaluate((zero) => {
      const canvas = document.createElement('canvas')
      canvas.width = 860
      canvas.height = 560
      const context = canvas.getContext('2d')!
      context.fillStyle = 'white'
      context.fillRect(0, 0, canvas.width, canvas.height)
      const baseline = 460
      const ticks = zero ? [0, 20, 40, 60, 80, 100] : [20, 40, 60, 80, 100]
      context.font = '28px Arial'
      context.textBaseline = 'middle'
      for (const tick of ticks) {
        const y = baseline - tick * 4
        context.strokeStyle = '#e7e9ef'
        context.beginPath()
        context.moveTo(120, y)
        context.lineTo(800, y)
        context.stroke()
        context.fillStyle = '#171c25'
        context.textAlign = 'right'
        context.fillText(String(tick), 95, y)
      }
      for (const [index, label] of ['Alpha', 'Beta', 'Gamma'].entries()) {
        const height = [80, 160, 280][index]
        const left = 168 + index * 213
        context.fillStyle = '#225bd0'
        context.fillRect(left, baseline - height, 106, height)
        context.fillStyle = '#171c25'
        context.textAlign = 'center'
        context.fillText(label, left + 53, 494)
      }
      return canvas.toDataURL('image/png').split(',')[1]
    }, includeZero)
    await page.locator('#workspace-agent-composer input[type="file"]').setInputFiles({
      name: 'synthetic-chart-preview.png', mimeType: 'image/png', buffer: Buffer.from(image, 'base64'),
    })
  }
  const preview = page.getByRole('dialog', { name: '图片文字预览' })
  const useChart = preview.getByRole('button', { name: '使用柱状图读数' })
  await uploadChart(false)
  await expect(preview).toBeVisible({ timeout: 60_000 })
  await expect(useChart).toHaveCount(0)
  await preview.getByRole('button', { name: '关闭', exact: true }).click()

  await uploadChart(true)
  await expect(useChart).toBeVisible({ timeout: 60_000 })
  await useChart.click()
  const editor = preview.getByRole('textbox', { name: '识别出的文字' })
  await expect(editor).toHaveValue('柱状图读数（按刻度和柱高估算）\n第 1 根（Alpha）约 20\n第 2 根（Beta）约 40\n第 3 根（Gamma）约 70')
  await preview.getByRole('button', { name: '插入到输入框' }).click()
  expect(writes).toEqual([])

  const text = await page.locator('#workspace-agent-input').inputValue()
  const prompt = `图中哪组最高，读数约是多少？\n\n${text}`
  const sent = page.waitForRequest((request) => request.url().endsWith('/workspace-agent/conversation/turn'))
  const events = await ask(page, prompt, '发送消息')
  expect((await sent).postDataJSON()).toEqual({ text: prompt, synthetic_only: true })
  const answer = events.find((event) => event.type === 'answer')?.text
  expect(answer).toMatch(/Gamma/i)
  expect(answer).toMatch(/\b70\b|七十/)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391)
})

test('a learner reads line charts locally and compares their series with the agent', async ({ page }) => {
  test.setTimeout(220_000)
  await signIn(page)
  await chooseRole(page, 'STUDENT', '/student/workspace')
  await page.setViewportSize({ width: 390, height: 840 })
  const writes: string[] = []
  page.context().on('request', (request) => {
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) writes.push(new URL(request.url()).pathname)
  })
  const upload = async (mode: 'single' | 'multiple' | 'same-color') => {
    const encoded = await page.evaluate((mode) => {
      const canvas = document.createElement('canvas')
      canvas.width = 860
      canvas.height = 560
      const ctx = canvas.getContext('2d')!
      ctx.fillStyle = '#fff'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      const y = (value: number) => 440 - (value - 20) * 5
      const x = (index: number) => 164 + index * 184
      ctx.font = '28px Arial'
      ctx.textBaseline = 'middle'
      for (const tick of [20, 40, 60, 80]) {
        ctx.strokeStyle = '#dce0e5'
        ctx.beginPath()
        ctx.moveTo(118, y(tick))
        ctx.lineTo(790, y(tick))
        ctx.stroke()
        ctx.fillStyle = '#171c25'
        ctx.textAlign = 'right'
        ctx.fillText(String(tick), 91, y(tick))
      }
      ctx.textAlign = 'center'
      for (const [index, label] of ['April', 'May', 'June', 'July'].entries()) {
        ctx.fillText(label, x(index), 477)
      }
      const curve = (values: number[], color: string) => {
        ctx.strokeStyle = color
        ctx.lineWidth = 5
        ctx.lineCap = 'round'
        ctx.lineJoin = 'round'
        ctx.beginPath()
        ctx.moveTo(x(0), y(values[0]))
        for (let index = 1; index < values.length; index += 1) ctx.lineTo(x(index), y(values[index]))
        ctx.stroke()
        ctx.fillStyle = color
        for (const [index, value] of values.entries()) {
          ctx.beginPath()
          ctx.arc(x(index), y(value), 7, 0, Math.PI * 2)
          ctx.fill()
        }
      }
      curve([30, 53, 37, 68], '#225bd0')
      if (mode !== 'single') {
        curve([62, 70, 58, 51], mode === 'same-color' ? '#225bd0' : '#e3781a')
        ctx.textAlign = 'left'
        for (const [label, center, color] of [['North', 210, '#225bd0'], ['South', 450, '#e3781a']] as const) {
          ctx.fillStyle = color
          ctx.fillRect(center - 43, 65, 32, 6)
          ctx.fillStyle = '#171c25'
          ctx.fillText(label, center, 68)
        }
      }
      return canvas.toDataURL('image/png').split(',')[1]
    }, mode)
    await page.locator('#workspace-agent-composer input[type="file"]').setInputFiles({
      name: 'synthetic-line-chart.png', mimeType: 'image/png', buffer: Buffer.from(encoded, 'base64'),
    })
  }
  const preview = page.getByRole('dialog', { name: '图片文字预览' })
  const useChart = preview.getByRole('button', { name: '使用折线图读数' })
  await upload('same-color')
  await expect(preview).toBeVisible({ timeout: 60_000 })
  await expect(useChart).toHaveCount(0)
  await preview.getByRole('button', { name: '关闭', exact: true }).click()

  await upload('single')
  await expect(useChart).toBeVisible({ timeout: 60_000 })
  await preview.getByText('查看原图', { exact: true }).click()
  const original = preview.getByRole('img', { name: '所选图片原图' })
  await expect(original).toBeVisible()
  await expect(original).toHaveAttribute('src', /^blob:/)
  await expect.poll(() => original.evaluate((image) => (image as HTMLImageElement).naturalWidth)).toBe(860)
  await preview.getByText('查看原图', { exact: true }).click()
  await useChart.click()
  const editor = preview.getByRole('textbox', { name: '识别出的文字' })
  const estimates = (await editor.inputValue()).split('\n')
  expect(estimates[0]).toContain('折线图读数')
  expect(estimates).toHaveLength(5)
  for (const [index, [label, value]] of [['April', 30], ['May', 53], ['June', 37], ['July', 68]].entries()) {
    const estimate = estimates[index + 1]
    expect(estimate).toContain(label)
    expect(Math.abs(Number(estimate.split('约 ').at(-1)) - Number(value))).toBeLessThanOrEqual(1)
  }
  const single = await editor.inputValue()
  await preview.getByRole('button', { name: '关闭', exact: true }).click()

  await upload('multiple')
  await expect(useChart).toBeVisible({ timeout: 60_000 })
  await useChart.click()
  const series = (await editor.inputValue()).split('\n')
  expect(series).toHaveLength(11)
  for (const [color, legend, values] of [
    ['蓝线', 'North', [30, 53, 37, 68]],
    ['橙线', 'South', [62, 70, 58, 51]],
  ] as const) {
    const start = series.findIndex((line) => line.startsWith(color))
    expect(start).toBeGreaterThan(0)
    expect(series[start]).toContain(legend)
    for (const [index, label] of ['April', 'May', 'June', 'July'].entries()) {
      const estimate = series[start + index + 1]
      expect(estimate).toContain(label)
      expect(Math.abs(Number(estimate.split('约 ').at(-1)) - values[index])).toBeLessThanOrEqual(1)
    }
  }
  await preview.getByRole('button', { name: '插入到输入框' }).click()
  expect(writes).toEqual([])
  const reviewed = await page.locator('#workspace-agent-input').inputValue()
  const prompt = `根据两组图上读数，哪一个月 North 首次高于 South，约高多少？\n\n${reviewed}`
  const sent = page.waitForRequest((request) => request.url().endsWith('/workspace-agent/conversation/turn'))
  const events = await ask(page, prompt, '发送消息')
  expect((await sent).postDataJSON()).toEqual({ text: prompt, synthetic_only: true })
  const answer = events.find((event) => event.type === 'answer')?.text
  expect(answer).toMatch(/July|7\s*月|七月/i)
  expect(answer).toMatch(/\b1[5-9]\b|十[五六七八九]/)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391)

  await chooseRole(page, 'TEACHER', '/teacher/workspace')
  writes.length = 0
  await upload('single')
  await expect(useChart).toBeVisible({ timeout: 60_000 })
  await useChart.click()
  await expect(editor).toHaveValue(single)
  expect(writes).toEqual([])
})

test('a learner previews a handwritten formula privately and asks the model to solve the reviewed text', async ({ page }) => {
  test.setTimeout(180_000)
  await page.addInitScript(() => {
    const target = window as typeof window & { formulaPayload?: { signature: string; sourceName: boolean } }
    const originalFetch = window.fetch.bind(window)
    window.fetch = async (resource, options) => {
      const location = typeof resource === 'string' ? resource : 'url' in resource ? resource.url : resource.href
      if (location.endsWith('/conversation/formula-preview') && options?.body instanceof window.Blob) {
        const bytes = new Uint8Array(await options.body.arrayBuffer())
        target.formulaPayload = {
          signature: Array.from(bytes.slice(0, 8), (byte) => byte.toString(16).padStart(2, '0')).join(''),
          sourceName: new window.TextDecoder().decode(bytes).includes('synthetic-formula-private.png'),
        }
      }
      return originalFetch(resource, options)
    }
  })
  await signIn(page)
  await chooseRole(page, 'STUDENT', '/student/workspace')
  await page.setViewportSize({ width: 390, height: 844 })
  const before = await page.request.get(origin + '/api/v1/workspace-agent/conversation')
  expect(before.ok()).toBe(true)
  const historyBefore = (await before.json()).data.events
  const writePaths: string[] = []
  page.context().on('request', (request) => {
    if (request.method() === 'POST') writePaths.push(new URL(request.url()).pathname)
  })

  const upload = async (withFormula: boolean) => {
    const image = await page.evaluate((drawFormula) => {
      const canvas = document.createElement('canvas')
      canvas.width = 322
      canvas.height = 164
      const context = canvas.getContext('2d')!
      context.fillStyle = 'white'
      context.fillRect(0, 0, 322, 164)
      context.strokeStyle = '#15212f'
      context.lineWidth = 5
      context.lineJoin = 'round'

      const stroke = (points: [number, number][], left = 0, top = 0) => {
        context.beginPath()
        points.forEach(([x, y], index) => {
          if (index === 0) context.moveTo(x + left, y + top)
          else context.lineTo(x + left, y + top)
        })
        context.stroke()
      }
      if (drawFormula) {
        stroke([[3, 8], [12, 3], [27, 4], [31, 12], [27, 21], [17, 25], [30, 29], [34, 38], [29, 45], [15, 49], [3, 45]], 62, 17)
        stroke([[45, 78], [113, 76]])
        stroke([[22, 4], [4, 30], [33, 31]], 63, 91)
        stroke([[26, 9], [25, 50]], 63, 91)
        stroke([[135, 78], [182, 78]])
        stroke([[158, 56], [157, 100]])
        stroke([[3, 16], [14, 4], [15, 48]], 225, 17)
        stroke([[208, 78], [276, 76]])
        stroke([[3, 14], [8, 5], [20, 3], [28, 9], [31, 18], [24, 32], [9, 46], [32, 46]], 226, 91)
      }
      return canvas.toDataURL('image/png').split(',')[1]
    }, withFormula)
    await page.locator('#workspace-agent-composer input[type="file"]').setInputFiles({
      name: 'synthetic-formula-private.png', mimeType: 'image/png', buffer: Buffer.from(image, 'base64'),
    })
  }
  const preview = page.getByRole('dialog', { name: '图片文字预览' })
  const recognize = preview.getByRole('button', { name: '交给学校服务识别公式' })
  const editor = preview.getByRole('textbox', { name: '识别出的文字' })
  await upload(false)
  await expect(preview).toBeVisible({ timeout: 60_000 })
  expect(writePaths).toEqual([])
  const rejected = page.waitForResponse((response) => response.url().endsWith('/conversation/formula-preview'))
  await recognize.click()
  expect((await rejected).status()).toBe(422)
  await expect(preview.getByRole('alert')).toContainText('没有读到清楚的公式')
  await expect(preview.getByRole('button', { name: '插入到输入框' })).toBeDisabled()
  await preview.getByRole('button', { name: '关闭', exact: true }).click()

  await upload(true)
  await expect(recognize).toBeVisible({ timeout: 60_000 })
  expect(writePaths).toHaveLength(1)
  const pending = page.waitForResponse((response) => response.url().endsWith('/conversation/formula-preview'))
  await recognize.click()
  const formula = await pending
  expect(formula.ok()).toBe(true)
  expect(formula.headers()['cache-control']).toBe('no-store')
  expect(new URL(formula.url()).origin).toBe(origin)
  expect((await formula.request().allHeaders())['content-type']).toBe('application/octet-stream')
  const encoded = await page.evaluate(() => (window as typeof window & { formulaPayload?: unknown }).formulaPayload)
  expect(encoded).toEqual({ signature: '89504e470d0a1a0a', sourceName: false })
  await expect(editor).toHaveValue(/\\frac\s*\{\s*3\s*\}\s*\{\s*4\s*\}\s*\+\s*\\frac\s*\{\s*1\s*\}\s*\{\s*2\s*\}/)
  const after = await page.request.get(origin + '/api/v1/workspace-agent/conversation')
  expect((await after.json()).data.events).toEqual(historyBefore)
  await preview.getByRole('button', { name: '插入到输入框' }).click()
  const text = await page.locator('#workspace-agent-input').inputValue()
  const prompt = `给出这道分数加法的最简结果\n\n${text}`
  const sent = page.waitForRequest((request) => request.url().endsWith('/conversation/turn'))
  const events = await ask(page, prompt, '发送消息')
  expect((await sent).postDataJSON()).toEqual({ text: prompt, synthetic_only: true })
  expect(events.find((event) => event.type === 'answer')?.text).toMatch(/1\.25|5\s*\/\s*4|\\frac\s*\{5\}\s*\{4\}|四分之五/)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391)
})

test('a learner extracts a PDF and sends only the selected worksheet excerpt', async ({ page }) => {
  test.setTimeout(150_000)
  await signIn(page)
  await chooseRole(page, 'STUDENT', '/student/workspace')
  const marker = 'WS_PRIVATE_SPAN_DO_NOT_SEND'
  const extraction = page.waitForResponse((response) => response.url().endsWith('/document-preview/pdf'))
  await page.locator('#workspace-agent-composer input[type="file"]').setInputFiles({
    name: 'synthetic-text.pdf', mimeType: 'application/pdf',
    buffer: textPdf(`Practice worksheet. Solve 13 + 29. Discard this footer ${marker}`),
  })
  const previewResponse = await extraction
  expect(previewResponse.ok()).toBe(true)
  expect(previewResponse.headers()['cache-control']).toBe('no-store')
  const preview = page.getByRole('dialog', { name: '文档文字预览' })
  const editor = preview.getByRole('textbox', { name: '提取的文字' })
  await expect(editor).toHaveValue(new RegExp(marker))
  const excerpt = '13 + 29'
  await editor.evaluate((field, selected) => {
    const input = field as HTMLTextAreaElement
    const start = input.value.indexOf(selected)
    input.setSelectionRange(start, start + selected.length)
  }, excerpt)
  await preview.getByRole('button', { name: '插入到输入框' }).click()
  await expect(page.locator('#workspace-agent-input')).toHaveValue(excerpt)
  const sent = page.waitForRequest((request) => request.url().endsWith('/workspace-agent/conversation/turn'))
  const events = await ask(page, '请计算这个算式并给出结果\n\n' + excerpt, '发送消息')
  const turn = await sent
  expect(turn.postDataJSON()).toEqual({ text: '请计算这个算式并给出结果\n\n' + excerpt, synthetic_only: true })
  expect(events.find((event) => event.type === 'answer')?.text).toMatch(/\b42\b|四十二/)
  const history = await page.request.get(origin + '/api/v1/workspace-agent/conversation')
  expect(await history.text()).not.toContain(marker)
})

test('a specialist confirms a PDF import and checks the real private library from chat', async ({ page }) => {
  test.skip(process.env.PSYNOVA_AGENT_QA_WRITE !== '1', 'Requires a dedicated synthetic school')
  test.setTimeout(180_000)
  await signIn(page)
  await chooseRole(page, 'PSYCHOLOGICAL_SPECIALIST', '/specialist/workspace')
  const marker = 'workspaceworksheet' + Date.now().toString(36)
  const title = 'synthetic-' + marker
  const endpoint = origin + '/api/v1/school/research-sources/library/documents'
  await page.locator('#workspace-agent-composer input[type="file"]').setInputFiles({
    name: title + '.pdf', mimeType: 'application/pdf',
    buffer: textPdf('Synthetic classroom reference for organizing revision work. ' + marker),
  })
  const preview = page.getByRole('dialog', { name: '文档文字预览' })
  await expect(preview.getByRole('textbox', { name: '提取的文字' })).toHaveValue(new RegExp(marker))
  await preview.getByRole('button', { name: '核对并入库' }).click()
  const dialog = page.getByRole('dialog', { name: '导入资料' })
  const submit = dialog.getByRole('button', { name: '批量导入' })
  await expect(submit).toBeDisabled()
  expect((await (await page.request.get(endpoint)).json()).data.items.some((item: { title: string }) => item.title === title)).toBe(false)
  await dialog.getByRole('checkbox').check()
  const importReceipt = page.waitForResponse((response) => response.url() === endpoint && response.request().method() === 'POST')
  await submit.click()
  expect((await importReceipt).status()).toBe(201)
  await expect(page.getByRole('list', { name: '已导入的本校资料' }).getByText(title, { exact: true })).toBeVisible()
  const inventory = (await (await page.request.get(endpoint)).json()).data.items as { title: string; chunk_count: number }[]
  expect(inventory.some((item) => item.title === title && item.chunk_count > 0)).toBe(true)
  const events = await ask(page, '查一下本校资料库现在有多少份资料，提取了多少个片段', '发送任务')
  expect(events.find((event) => event.view?.kind === 'school_library_inventory')?.view).toMatchObject({
    total: inventory.length, chunks: inventory.reduce((sum, item) => sum + item.chunk_count, 0),
  })
  expect(JSON.stringify(events)).not.toContain(marker)
  await page.getByRole('button', { name: '查看本校资料库' }).last().click()
  await page.getByRole('textbox', { name: '检索本校资料' }).fill(marker)
  await page.getByRole('button', { name: '检索', exact: true }).click()
  await expect(page.getByRole('list', { name: '匹配的资料片段' }).getByText(new RegExp(marker)).last()).toBeVisible()
})

test('a teacher shares only selected CSV aggregates and downloads the exact statistics', async ({ page }) => {
  test.setTimeout(150_000)
  await page.setViewportSize({ width: 390, height: 844 })
  await signIn(page)
  await chooseRole(page, 'TEACHER', '/teacher/workspace')
  const marker = 'WS_PRIVATE_ROW_DO_NOT_SEND'
  await page.locator('#workspace-agent-composer input[type="file"]').setInputFiles({
    name: 'synthetic-practice.csv', mimeType: 'text/csv',
    buffer: Buffer.from(`Label,StudyMinutes,Questions\n${marker},15,3\nsampleB,30,4\nsampleC,45,5\nsampleD,,6\n`),
  })
  const preview = page.getByRole('dialog', { name: '选择表格统计' })
  await preview.getByRole('checkbox', { name: /第 2 列 · StudyMinutes/ }).check()
  await preview.getByRole('button', { name: '使用所选统计' }).click()
  const sent = page.waitForRequest((request) => request.url().endsWith('/workspace-agent/conversation/turn'))
  const summary = { rows: 4, columns: [{ column: 2, count: 3, min: 15, max: 45, mean: 30, sum: 90 }] }
  const events = await ask(page, '核对所选列的表格汇总，并生成可下载的统计表', '发送任务')
  const request = await sent
  expect(request.postDataJSON().table_summary).toEqual(summary)
  expect(request.postData()).not.toMatch(new RegExp(`${marker}|StudyMinutes|Questions|synthetic-practice`))
  expect(events.find((event) => event.view?.kind === 'table_statistics')?.view).toMatchObject(summary)
  await expect(page.getByRole('table', { name: '所选列的统计结果' }).last().getByText('90', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391)
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载统计 CSV' }).last().click()
  const artifact = await download
  expect(artifact.suggestedFilename()).toBe('表格统计.csv')
  expect((await readFile(await artifact.path(), 'utf-8')).split(/\r?\n/)).toEqual([
    '\uFEFF列号,数据行数,数字个数,最小值,最大值,平均值,合计', '2,4,3,15,45,30,90',
  ])
})

test('an administrator still sends a CSV roster through the roster preview', async ({ page }) => {
  test.setTimeout(90_000)
  await signIn(page)
  await chooseRole(page, 'ADMIN', '/admin/workspace')
  const suffix = String(Date.now())
  await page.locator('#workspace-agent-composer input[type="file"]').setInputFiles({
    name: 'synthetic-roster-preview.csv', mimeType: 'text/csv',
    buffer: Buffer.from('student_number,display_name,class_ref,grade_level\n' +
      `QA-${suffix},合成预览学生,合成预览班${suffix},高一\n`),
  })
  await expect(page.getByText('服务端预览：1 条')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('dialog', { name: '选择表格统计' })).toHaveCount(0)
})

test('a learner selects an Excel sheet locally and sends only that sheet’s selected statistics', async ({ page }) => {
  test.setTimeout(150_000)
  await page.setViewportSize({ width: 390, height: 844 })
  await signIn(page)
  await chooseRole(page, 'STUDENT', '/student/workspace')
  const writes: string[] = []
  page.on('request', (request) => {
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) writes.push(new URL(request.url()).pathname)
  })
  const file = workbook([
    { name: '不发送的工作表一', rows: [['PrivateMinutes'], [17], [43]] },
    { name: '不发送的工作表二', rows: [
      ['Label', 'StudyMinutes', 'Questions'],
      ['WS_XLSX_PRIVATE_TEXT', 12, 110],
      ['PracticeB', -3, 120],
      ['PracticeC', '30', 130],
      ['PracticeD', 9, 140],
    ] },
  ])
  await page.locator('#workspace-agent-composer input[type="file"]').setInputFiles({
    name: 'local-practice.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from(file),
  })
  const preview = page.getByRole('dialog', { name: '选择表格统计' })
  await preview.getByRole('checkbox', { name: /PrivateMinutes/ }).check()
  await preview.getByRole('combobox', { name: '选择工作表' }).selectOption({ label: '不发送的工作表二' })
  await expect(preview.getByRole('button', { name: '使用所选统计' })).toBeDisabled()
  await preview.getByRole('checkbox', { name: /第 2 列 · StudyMinutes/ }).check()
  await preview.getByRole('button', { name: '使用所选统计' }).click()
  expect(writes).toEqual([])
  const sent = page.waitForRequest((request) => request.url().endsWith('/workspace-agent/conversation/turn'))
  const events = await ask(page, '帮我核对刚才选中的统计值，整理出一份可以下载的表', '发送消息')
  const request = await sent
  const summary = { rows: 4, columns: [{ column: 2, count: 3, min: -3, max: 12, mean: 6, sum: 18 }] }
  expect(request.postDataJSON().table_summary).toEqual(summary)
  const privateFields = /WS_XLSX_PRIVATE_TEXT|StudyMinutes|Questions|PrivateMinutes|local-practice|不发送的工作表/
  expect(request.postData()).not.toMatch(privateFields)
  expect(JSON.stringify(events)).not.toMatch(privateFields)
  expect(events.find((event) => event.view?.kind === 'table_statistics')?.view).toMatchObject(summary)
  await page.reload()
  await expect(page.getByRole('table', { name: '所选列的统计结果' }).last()).toBeVisible()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载统计 CSV' }).last().click()
  const result = await download
  expect((await readFile(await result.path(), 'utf8')).split(/\r?\n/).at(-1)).toBe('2,4,3,-3,12,6,18')
})

test('an administrator keeps Excel rosters in the private import workflow', async ({ page }) => {
  test.setTimeout(90_000)
  await signIn(page)
  await chooseRole(page, 'ADMIN', '/admin/workspace')
  const suffix = String(Date.now())
  const file = workbook([{ name: '学生名单', rows: [
    ['student_number', 'display_name', 'class_ref', 'grade_level'],
    [`EX-${suffix}`, '合成预览学生', `合成预览班${suffix}`, '高一'],
  ] }])
  await page.locator('#workspace-agent-composer input[type="file"]').setInputFiles({
    name: 'synthetic-roster-preview.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from(file),
  })
  await expect(page.getByText('服务端预览：1 条')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('dialog', { name: '选择表格统计' })).toHaveCount(0)
})

test('an administrator confirms a private staff roster, downloads credentials and rechecks the live state', async ({ page }) => {
  test.skip(process.env.PSYNOVA_AGENT_QA_WRITE !== '1', 'Requires a dedicated synthetic school')
  test.setTimeout(210_000)
  await page.setViewportSize({ width: 390, height: 844 })
  await signIn(page)
  await chooseRole(page, 'ADMIN', '/admin/workspace')
  const originalSummary = async () => {
    const response = await page.request.get(origin + '/api/v1/school/admin/accounts/summary')
    expect(response.ok()).toBe(true)
    return (await response.json()).data
  }
  const before = await originalSummary()
  const directory = await page.request.get(origin + '/api/v1/school/admin/directory')
  expect(directory.ok()).toBe(true)
  const currentClass = (await directory.json()).data.classes.find((item: { status: string }) => item.status === 'ACTIVE')
  expect(Boolean(currentClass)).toBe(true)
  const suffix = String(Date.now())
  const staffRef = `STAFF-QA-${suffix}`
  const rows = [
    [staffRef + '-T', '合成名单教师', 'teacher', currentClass.class_ref],
    [staffRef + '-P', '合成名单心理教师', 'psychological_specialist', ''],
  ]
  const csv = 'employee_ref,display_name,role,class_refs\r\n'
    + rows.map((row) => row.map((value) => `"${value.replaceAll('"', '""')}"`).join(',')).join('\r\n')
  const importWrites: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/school/admin/staff/import')) importWrites.push(request.url())
  })
  await page.locator('#workspace-agent-composer input[type="file"]').setInputFiles({
    name: 'synthetic-staff-roster.csv', mimeType: 'text/csv', buffer: Buffer.from(csv),
  })
  const outbound = page.waitForRequest((request) => request.url().endsWith('/workspace-agent/conversation/turn'))
  const prepared = await ask(page, '把刚附上的教职工名单整理成让我核对的预览，准备发放首登凭据', '发送任务')
  const request = await outbound
  expect(request.postDataJSON().attachment).toBe('staff_roster')
  expect(request.postData()?.includes(staffRef)).toBe(false)
  expect(request.postData()).not.toMatch(/synthetic-staff-roster|合成名单教师|employee_ref/)
  expect(prepared.some((event) => event.view?.kind === 'staff_roster_import')).toBe(true)
  const preview = page.getByRole('table', { name: '教职工名单预览' })
  await expect(preview.getByText(rows[0][1], { exact: true })).toBeVisible()
  await expect(preview.getByText(rows[1][1], { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '核对并导入', exact: true }).click()
  const confirmation = page.getByRole('dialog', { name: '确认导入教职工' })
  await confirmation.getByRole('button', { name: '返回核对' }).click()
  expect(importWrites).toHaveLength(0)
  await page.getByRole('button', { name: '核对并导入', exact: true }).click()
  const response = page.waitForResponse((result) => result.url().endsWith('/school/admin/staff/import'))
  await confirmation.getByRole('button', { name: '确认导入', exact: true }).click()
  const importResult = await response
  expect(importResult.status()).toBe(201)
  expect(importResult.headers()['cache-control']).toBe('no-store')
  expect(importWrites).toHaveLength(1)
  const imported = (await importResult.json()).data
  const credentials = imported.credentials as { employee_ref: string; role: string; login_name: string; credential: string; invitation_ref: string }[]
  expect(imported.created_count).toBe(rows.length)
  expect(credentials.map((row) => row.role).sort()).toEqual(['psychological_specialist', 'teacher'])
  await expect(page.getByText(/已导入 2 名教职工/)).toBeVisible()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载账号 CSV（2 份）', exact: true }).click()
  const file = await download
  const contents = await readFile(await file.path(), 'utf8')
  expect(file.suggestedFilename()).toBe('psynova-initial-accounts.csv')
  expect(credentials.every((row) => row.credential.length > 0 && contents.includes(row.login_name) && contents.includes(row.credential))).toBe(true)

  const after = await originalSummary()
  expect(after.invitations_issued).toBe(before.invitations_issued + rows.length)
  const counts = await ask(page, '刚才操作完，学校里现在还有多少教职工邀请在等接受？', '发送任务', false)
  expect(counts.find((event) => event.view?.kind === 'staff_invitation_status')?.view).toMatchObject({
    issued: after.invitations_issued, accepted: after.invitations_accepted,
    expired: after.invitations_expired, revoked: after.invitations_revoked,
  })
  const history = await page.request.get(origin + '/api/v1/workspace-agent/conversation')
  expect(history.ok()).toBe(true)
  const saved = await history.text()
  expect(saved.includes(staffRef)).toBe(false)
  expect(credentials.some((row) => saved.includes(row.credential) || saved.includes(row.login_name))).toBe(false)

  await page.goto(origin + '/admin/users')
  await page.getByRole('tab', { name: '教职工名单' }).click()
  await page.getByRole('textbox', { name: '搜索邀请' }).fill(rows[1][0])
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await expect(page.getByText(rows[1][1], { exact: true })).toBeVisible()
})

test('an administrator checks real system dependencies and pages through the school audit', async ({ page }) => {
  test.setTimeout(210_000)
  await page.setViewportSize({ width: 390, height: 844 })
  await signIn(page)
  await chooseRole(page, 'ADMIN', '/admin/workspace')
  const apiHealth = await page.request.get(origin + '/api/v1/health')
  expect(apiHealth.ok()).toBe(true)
  const health = (await apiHealth.json()).data.dependencies as Record<string, { status: string }>
  const compareAudit = async (offset: number) => {
    const response = await page.request.get(origin + `/api/v1/school/operations-audit?category=task&limit=1&offset=${offset}`)
    expect(response.ok()).toBe(true)
    return (await response.json()).data
  }
  const original = await compareAudit(0)
  expect(original.items).toHaveLength(1)
  expect(original.has_more).toBe(true)
  const events = await ask(page, '请查一下系统依赖目前的状态，也给我本校最新一条测评任务发布的运营记录', '发送任务')
  const diagnostics = events.find((event) => event.view?.kind === 'system_health')?.view
  expect(diagnostics?.statuses).toEqual(Object.fromEntries(Object.entries(health).map(([key, value]) => [
    key, value.status,
  ])))
  const audit = events.find((event) => event.view?.kind === 'school_audit')?.view
  expect(audit?.query).toEqual({ category: 'task', limit: 1, offset: 0 })
  const withoutReference = ({ event_ref, ...item }: Record<string, unknown>) => {
    expect(typeof event_ref).toBe('string')
    return item
  }
  expect(audit?.items).toEqual(original.items.map(withoutReference))
  expect(JSON.stringify(events)).not.toContain(original.items[0].event_ref)
  await expect(page.getByRole('list', { name: '系统依赖状态' }).last().getByText('安全校验')).toBeVisible()
  await expect(page.getByRole('list', { name: '本校运营记录' }).last().getByText(/发布测评任务/)).toBeVisible()

  await page.reload()
  await expect(page.getByText(/从第 1 条起/).last()).toBeVisible()
  const second = await compareAudit(1)
  const next = await ask(page, '刚才查的运营记录往后翻一条，类别保持不变', '发送任务')
  const nextAudit = next.find((event) => event.view?.kind === 'school_audit')?.view
  expect(nextAudit?.query).toEqual({ category: 'task', limit: 1, offset: 1 })
  expect(nextAudit?.items).toEqual(second.items.map(withoutReference))
  expect(nextAudit?.has_more).toBe(second.has_more)
  await page.reload()
  await expect(page.getByText(/从第 2 条起/).last()).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391)

  await chooseRole(page, 'TEACHER', '/teacher/workspace')
  await expect(page.getByRole('list', { name: '本校运营记录' })).toHaveCount(0)
  expect((await page.request.get(origin + '/api/v1/school/operations-audit')).status()).toBe(403)
})

test('a synthetic learner resumes and submits a real assessment inside the conversation', async ({ page }) => {
  test.skip(process.env.PSYNOVA_AGENT_QA_WRITE !== '1', 'Requires a dedicated synthetic school')
  test.setTimeout(270_000)
  await signIn(page)
  await chooseRole(page, 'STUDENT', '/student/workspace')
  const assigned = await page.request.get(origin + '/api/v1/school/tasks/student')
  expect(assigned.ok()).toBe(true)
  const openTasks = ((await assigned.json()).data as {
    task_ref: string; assessment_status: string | null; due_at: string | null
  }[]).filter((task) => [null, 'created', 'in_progress'].includes(task.assessment_status))
  const expectedTask = openTasks.sort((first, second) => {
    const dueTime = (task: typeof first) => task.due_at ? Date.parse(task.due_at) : Number.MAX_SAFE_INTEGER
    return Number(second.assessment_status === 'in_progress') - Number(first.assessment_status === 'in_progress')
      || dueTime(first) - dueTime(second)
      || first.task_ref.localeCompare(second.task_ref)
  })[0]
  expect(expectedTask, 'A dedicated synthetic learner needs an open assessment').toBeTruthy()
  const listed = await ask(page, '看看我现在还有哪些测评待做', '发送消息')
  const tasks = listed.find((event) => event.view?.kind === 'student_tasks')?.view.rows
  expect(tasks?.some((row: { status: string }) => ['created', 'in_progress', 'not_started'].includes(row.status))).toBe(true)
  const selected = await ask(page, '继续刚才查到的测评，已有进度的优先，否则打开最早截止的一项', '发送消息', false)
  const taskRef = selected.find((event) => event.view?.kind === 'assessment_picker')?.view.task_ref
  expect(taskRef).toBe(expectedTask.task_ref)
  const picker = page.getByRole('button', { name: '阅读说明并打开测评' }).last()
  const confirmStart = page.getByRole('button', { name: '我已阅读，开始或继续' })
  const startTask = async () => {
    await picker.click()
    const started = page.waitForResponse((response) => response.url().endsWith(`/school/tasks/${taskRef}/start`))
    await confirmStart.click()
    const response = await started
    expect(response.ok()).toBe(true)
    return (await response.json()).data
  }
  await page.reload()
  const initial = await startTask()
  const { assessment_id: assessmentId } = initial
  const assessment = page.locator('.assessment-page--embedded')
  await expect(assessment).toBeVisible()
  const finish = assessment.getByRole('button', { name: /^(完成|完成测评)$/ })
  const choice = assessment.getByRole('radio').first()
  await expect(choice.or(finish).first()).toBeVisible()
  let progress = initial.answered_count
  const saveAnswer = async () => {
    const response = page.waitForResponse((reply) => reply.url().endsWith(`/assessments/${assessmentId}/responses`))
    await choice.click()
    await assessment.getByRole('button', { name: '下一题' }).click()
    expect((await response).ok()).toBe(true)
    progress += 1
    await expect(assessment.getByText(`已记录 ${progress} 项`, { exact: true })).toBeVisible()
  }
  if (await choice.isVisible()) await saveAnswer()
  expect(progress).toBeGreaterThan(0)
  await page.reload()
  expect(await startTask()).toMatchObject({ assessment_id: assessmentId, answered_count: progress })
  await expect(assessment.getByText(`已记录 ${progress} 项`, { exact: true })).toBeVisible()
  while (!(await finish.isVisible()) && progress < (initial.max_items ?? 30)) await saveAnswer()

  const completion = page.waitForResponse((response) => response.url().endsWith(`/assessments/${assessmentId}/complete`))
  await finish.click()
  const completed = await completion
  expect(completed.ok()).toBe(true)
  expect((await completed.json()).data).toMatchObject({ assessment_id: assessmentId, status: 'completed' })
  await expect(page.getByText('已保存测评作答')).toBeVisible()
  await expect(page.getByRole('button', { name: '查看本次测评反馈' })).toBeVisible()
  const history = await page.request.get(origin + '/api/v1/school/tasks/student/history')
  expect(history.ok()).toBe(true)
  expect((await history.json()).data).toContainEqual(expect.objectContaining({
    task_ref: taskRef, assessment_id: assessmentId, assessment_status: 'completed',
  }))

  await page.reload()
  const assessmentWrites: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/(?:school\/tasks|assessments)\//.test(request.url())) assessmentWrites.push(request.url())
  })
  await picker.click()
  await expect(page.getByText('已保存测评作答')).toBeVisible()
  await expect(page.getByRole('button', { name: '查看本次测评反馈' })).toBeVisible()
  await expect(confirmStart).toHaveCount(0)
  expect(assessmentWrites).toEqual([])
})

test('a learner reopens a completed school assessment without starting another session', async ({ page }) => {
  test.setTimeout(120_000)
  await signIn(page)
  await chooseRole(page, 'STUDENT', '/student/workspace')
  const result = await ask(page, '核对我目前的测评任务和完成状态，包括已经交卷的测评', '发送消息')
  const tasks = result.find((event) => event.view?.kind === 'student_tasks')?.view.rows
  const completed = tasks?.filter((row: { status: string }) => row.status === 'completed')
  expect(completed?.length).toBeGreaterThan(0)

  await page.reload()
  const writes: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/(?:school\/tasks|assessments)\//.test(request.url())) writes.push(request.url())
  })
  const history = page.waitForResponse((response) => response.url().endsWith('/school/tasks/student/history'))
  const completedButton = page.getByRole('button', { name: '查看完成记录' })
  const taskList = page.getByRole('list').filter({ has: completedButton }).last()
  await taskList.getByRole('button', { name: '查看完成记录' }).first().click()
  const response = await history
  expect(response.ok()).toBe(true)
  expect((await response.json()).data).toContainEqual(expect.objectContaining({
    task_ref: completed[0].ref,
    assessment_status: 'completed',
  }))
  await expect(page.getByText('已保存测评作答')).toBeVisible()
  const receipt = page.getByRole('button', { name: '查看本次测评反馈' })
  await expect(receipt).toBeVisible()
  const exactRead = page.waitForResponse((reply) => reply.url().endsWith(`/conversation/task-feedback/${completed[0].ref}`))
  await receipt.click()
  const publication = (await (await exactRead).json()).data.feedback_ref
  if (publication === null) await expect(page.getByText('这项测评暂未发布反馈')).toBeVisible()
  else {
    const feedback = await page.request.get(origin + `/api/v1/school/feedback/student/${publication}`)
    expect(feedback.ok()).toBe(true)
    const detail = (await feedback.json()).data
    const items = (await response.json()).data
    expect(detail.assessment_ref).toBe(items.find((item: { task_ref: string }) => item.task_ref === completed[0].ref)?.assessment_id)
    await expect(page.getByRole('heading', { name: detail.title, exact: true })).toBeVisible()
  }
  await expect(page.getByRole('button', { name: '我已阅读，开始或继续' })).toHaveCount(0)
  expect(writes).toEqual([])
})

test('a roster creates real synthetic accounts and returns a credential download', async ({ page }) => {
  test.skip(process.env.PSYNOVA_AGENT_QA_WRITE !== '1', 'Set PSYNOVA_AGENT_QA_WRITE=1 for a dedicated test school')
  test.setTimeout(150_000)
  await signIn(page)
  await chooseRole(page, 'ADMIN', '/admin/workspace')
  const suffix = String(Date.now())
  const studentName = '合成导入学生' + suffix
  const className = '合成导入验证班' + suffix
  await page.locator('#workspace-agent-composer input[type="file"]').setInputFiles({
    name: 'synthetic-roster.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(
      'student_number,display_name,class_ref,grade_level\n' +
      `QA-${suffix},${studentName},${className},高一\n`,
    ),
  })
  await expect(page.getByText('服务端预览：1 条')).toBeVisible({ timeout: 30_000 })
  const pending = page.waitForResponse((response) => response.url().endsWith('/api/v1/school/admin/roster/import'))
  await page.getByRole('button', { name: '导入并生成初始账号' }).click()
  expect((await pending).status()).toBe(201)
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: /下载账号 CSV/ }).click()
  expect((await download).suggestedFilename()).toMatch(/\.csv$/)
  const response = await page.request.get(origin + '/api/v1/school/admin/directory')
  expect(response.ok()).toBe(true)
  const directory = (await response.json()).data
  expect(directory.classes.some((row: { display_name: string }) => row.display_name === className)).toBe(true)
  expect(directory.members.some((row: { display_name: string }) => row.display_name === studentName)).toBe(true)
})

test('a teacher edits a referral draft and confirms a real support request', async ({ page }) => {
  test.skip(process.env.PSYNOVA_AGENT_QA_WRITE !== '1', 'Requires a dedicated synthetic school')
  test.setTimeout(240_000)
  await signIn(page)
  await chooseRole(page, 'TEACHER', '/teacher/workspace')
  const prepared = await ask(page, '请根据这条合成观察准备同伴相处转介草案：这位同学近两次小组讨论都坐在一旁，没有参与讨论。', '发送任务')
  const draft = prepared.find((event) => event.view?.kind === 'teacher_referral')?.view
  expect(draft).toMatchObject({ category_code: 'PEER_RELATION', observation: expect.stringMatching(/小组/) })
  await page.reload()
  await page.getByRole('button', { name: '核对转介草案' }).last().click()
  const observation = page.getByRole('textbox', { name: '观察记录' })
  await expect(observation).toHaveValue(draft.observation)
  const submit = page.getByRole('button', { name: '提交支持请求' })
  await expect(submit).toBeDisabled()
  await page.locator('#support-student').click()
  await page.getByRole('option').first().click()
  const edited = '合成验证记录：近两次课堂小组活动都坐在一旁，有待教师进一步了解'
  await observation.fill(edited)
  const created = page.waitForResponse((response) =>
    response.request().method() === 'POST' && response.url().endsWith('/api/v1/school/support/cases'),
  )
  await submit.click()
  const receipt = await created
  expect(receipt.status()).toBe(201)
  expect(receipt.request().postDataJSON()).toMatchObject({ content: edited, category_code: 'PEER_RELATION' })
  const { case_ref: caseRef, status } = (await receipt.json()).data
  expect(status).toBe('SUBMITTED')
  const actual = await page.request.get(origin + '/api/v1/school/support/cases')
  expect(actual.ok()).toBe(true)
  expect((await actual.json()).data.items).toContainEqual(expect.objectContaining({ case_ref: caseRef, status }))
  const checked = await ask(page, '查一下我有多少条支持请求以及各自的处理状态', '发送任务')
  expect(checked.find((event) => event.view?.kind === 'teacher_support_status')?.view).toMatchObject({
    counts: { SUBMITTED: expect.any(Number) },
  })
})

test('a specialist sees real pending review counts and opens the assigned task from chat', async ({ page }) => {
  test.skip(process.env.PSYNOVA_AGENT_QA_REVIEW_PENDING !== '1', 'Requires a pending assigned review fixture')
  test.setTimeout(180_000)
  await signIn(page)
  await chooseRole(page, 'PSYCHOLOGICAL_SPECIALIST', '/specialist/workspace')
  const events = await ask(page, '整理我当前指派的测评复核待办，按任务查看已有待办和测评已完成但尚未建立复核的数量', '发送任务')
  const resultKinds = events.map((event) => event.view?.kind ?? event.code ?? event.type)
  expect(resultKinds).toContain('professional_review_queue')
  const queue = events.find((event) => event.view?.kind === 'professional_review_queue')?.view
  expect(queue.open_count + queue.in_review_count).toBeGreaterThan(0)
  expect(queue.unfiled_count).toBeGreaterThan(0)
  const awaitingReviewIndex = queue.tasks.findIndex((row: { unfiled_count: number }) => row.unfiled_count > 0)
  expect(awaitingReviewIndex).toBeGreaterThanOrEqual(0)
  const task = queue.tasks[awaitingReviewIndex]
  const work = '/api/v1/school/professional-reviews/tasks/' + encodeURIComponent(task.task_ref)
  let unfiledCount = 0
  for (let offset = 0; ; offset += 50) {
    const list = await page.request.get(origin + work + `/eligible-enrollments?offset=${offset}&limit=50`)
    expect(list.ok()).toBe(true)
    const { items, total } = (await list.json()).data
    unfiledCount += items.filter((item: { case_ref: string | null }) => item.case_ref === null).length
    if (offset + 50 >= total) break
  }
  expect(task.unfiled_count).toBe(unfiledCount)
  const existing = queue.tasks.find((row: { open_count: number; in_review_count: number }) => row.open_count + row.in_review_count > 0)
  expect(existing).toBeTruthy()
  const existingWork = '/api/v1/school/professional-reviews/tasks/' + encodeURIComponent(existing.task_ref)
  let open = 0
  let reviewing = 0
  for (let offset = 0; ; offset += 50) {
    const list = await page.request.get(origin + existingWork + `/cases?offset=${offset}&limit=50`)
    expect(list.ok()).toBe(true)
    const { items, total } = (await list.json()).data
    open += items.filter((item: { status: string }) => item.status === 'OPEN').length
    reviewing += items.filter((item: { status: string }) => item.status === 'IN_REVIEW').length
    if (offset + 50 >= total) break
  }
  expect(existing).toMatchObject({ open_count: open, in_review_count: reviewing })
  const cases = page.waitForResponse((response) => response.url().startsWith(origin + work + '/cases?'))
  const buttons = page.getByRole('button', { name: '查看该任务测评与复核' })
  await buttons.nth(await buttons.count() - queue.tasks.length + awaitingReviewIndex).click()
  expect((await cases).ok()).toBe(true)
  await expect(page.getByRole('heading', { name: '已完成记录', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '复核记录', exact: true })).toBeVisible()
  await expect(page).toHaveURL(origin + '/specialist/workspace')
  const support = await page.request.get(origin + '/api/v1/school/support/cases?limit=50')
  expect(support.ok()).toBe(true)
  const authorized = (await support.json()).data
  const supportEvents = await ask(page, '再核对一下我有权查看的学校支持请求处理状态', '发送任务', false)
  expect(supportEvents.find((event) => event.view?.kind === 'specialist_support_status')?.view).toMatchObject({
    total: authorized.total,
    shown: authorized.items.length,
  })
})

test('a specialist reviews facts and saves an authorized synthetic support plan', async ({ page }) => {
  test.skip(process.env.PSYNOVA_AGENT_QA_WRITE !== '1', 'Requires a dedicated synthetic school')
  test.setTimeout(200_000)
  await signIn(page)
  let expectedFeedback
  let feedbackScope
  if (process.env.PSYNOVA_AGENT_QA_SUPPORT_EVIDENCE === '1') {
    await chooseRole(page, 'STUDENT', '/student/workspace')
    const [list, history, session] = await Promise.all([
      page.request.get(origin + '/api/v1/school/feedback/student'),
      page.request.get(origin + '/api/v1/school/tasks/student/history'),
      page.request.get(origin + '/api/v1/auth/me'),
    ])
    expect([list.ok(), history.ok(), session.ok()]).toEqual([true, true, true])
    expectedFeedback = (await list.json()).data.items[0]
    expect(expectedFeedback).toBeTruthy()
    const task = (await history.json()).data.find((row: { assessment_id: string }) => row.assessment_id === expectedFeedback.assessment_ref)
    feedbackScope = { student_ref: (await session.json()).data.subject_id, class_ref: task?.class_ref }
    expect(Boolean(feedbackScope.student_ref && feedbackScope.class_ref)).toBe(true)
  }
  await chooseRole(page, 'TEACHER', '/teacher/workspace')
  const support = '/api/v1/school/support'
  const resumeTriaged = process.env.PSYNOVA_AGENT_QA_TRIAGED_SUPPORT_REF
  const replay = resumeTriaged ?? process.env.PSYNOVA_AGENT_QA_UNCLAIMED_SUPPORT_REF
  let item
  let observation: string
  if (replay) {
    expect(replay).toMatch(/^SSC_[a-f0-9]{32}$/)
    const detail = await page.request.get(origin + support + '/cases/' + replay)
    expect(detail.ok()).toBe(true)
    item = (await detail.json()).data
    expect(item.status).toBe(resumeTriaged ? 'TRIAGED' : 'SUBMITTED')
    observation = item.content
    expect(observation).toMatch(/^合成流程验证 \d+，课堂学习安排需要进一步向学生核对$/)
  } else {
    const directory = await page.request.get(origin + support + '/students')
    expect(directory.ok()).toBe(true)
    const students = (await directory.json()).data.items
    const student = feedbackScope
      ? students.find((row: { student_ref: string; class_ref: string }) => row.student_ref === feedbackScope.student_ref && row.class_ref === feedbackScope.class_ref)
      : students[0]
    expect(student?.student_ref).toBeTruthy()
    const csrf = await page.request.get(origin + '/api/v1/auth/csrf')
    observation = `合成流程验证 ${Date.now()}，课堂学习安排需要进一步向学生核对`
    const created = await page.request.post(origin + support + '/cases', {
      headers: { Origin: origin!, 'X-CSRF-Token': (await csrf.json()).data.csrf_token, 'Idempotency-Key': `qa-support-plan-${Date.now()}` },
      data: { category_code: 'LEARNING_SUPPORT', content: observation, student_ref: student.student_ref, class_ref: student.class_ref },
    })
    expect(created.status()).toBe(201)
    item = (await created.json()).data
  }
  const casePath = support + '/cases/' + item.case_ref
  const evidencePath = casePath + '/plan-evidence'

  await chooseRole(page, 'PSYCHOLOGICAL_SPECIALIST', '/specialist/workspace')
  if (!resumeTriaged) expect((await page.request.get(origin + evidencePath)).status()).toBe(404)
  const events = await ask(page, '请为授权的学校支持请求准备一份专业支持计划草案，我要查看依据后再决定是否保存', '发送任务')
  const tool = events.find((event) => event.view?.kind === 'specialist_support_plan')?.view
  expect(tool?.counts[resumeTriaged ? 'TRIAGED' : 'SUBMITTED']).toBeGreaterThan(0)
  expect(JSON.stringify(events)).not.toContain(item.case_ref)
  expect(JSON.stringify(events)).not.toContain(observation)

  await page.reload()
  await page.getByRole('button', { name: '打开支持计划草案' }).last().click()
  await page.getByRole('button', { name: new RegExp(item.case_ref.slice(-8)) }).click()
  if (!resumeTriaged) {
    await expect(page.getByText(observation, { exact: true })).toHaveCount(0)
    const triaged = page.waitForResponse((response) => response.url().endsWith(casePath + '/transitions'))
    await page.getByRole('button', { name: '受理请求' }).click()
    expect((await (await triaged).json()).data.status).toBe('TRIAGED')
  }
  await expect(page.getByText(observation, { exact: true })).toBeVisible()
  if (expectedFeedback) {
    const pendingEvidence = page.waitForResponse((response) => response.url().endsWith(evidencePath))
    await page.getByRole('button', { name: '核对已发布测评反馈' }).click()
    const evidence = await pendingEvidence
    expect(evidence.ok()).toBe(true)
    expect(evidence.headers()['cache-control']).toContain('no-store')
    const { feedback } = (await evidence.json()).data
    expect(feedback).toEqual({
      title: expectedFeedback.title,
      body: expectedFeedback.body,
      published_at: expect.any(String),
      content_revision: expectedFeedback.content_revision,
    })
    expect(feedback.published_at.replace(/\+00:00$/, 'Z')).toBe(expectedFeedback.published_at.replace(/\+00:00$/, 'Z'))
    const reviewed = readSchoolFeedbackContent(expectedFeedback.body)
    const panel = page.getByRole('region', { name: '已发布测评反馈' })
    await expect(panel.getByText(reviewed.body, { exact: true })).toBeVisible()
    if (reviewed.nextSteps) await expect(panel.getByText(reviewed.nextSteps, { exact: true })).toBeVisible()
    await panel.getByRole('checkbox', { name: '将这份反馈列为计划依据' }).check()
  }
  await page.locator('#support-plan-topic').click()
  await page.getByRole('option', { name: '忙不过来时，先找一个能做的小步骤' }).click()
  await expect(page.getByRole('link', { name: '世界卫生组织｜压力' })).toHaveAttribute('href', /who\.int/)

  const changes: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith(casePath + '/transitions')) changes.push(request.url())
  })
  await page.getByRole('button', { name: '生成可编辑草案' }).click()
  const plan = page.getByRole('textbox', { name: '专业支持计划' })
  await expect(plan).toHaveValue(/教师转介 · 学习适应 · 已受理/)
  const draft = await plan.inputValue()
  if (expectedFeedback) {
    expect(draft).toContain(expectedFeedback.title)
    expect(draft).toContain('本次草案尚未核对获批风险规则')
    expect(draft).not.toContain(readSchoolFeedbackContent(expectedFeedback.body).body)
  } else {
    expect(draft).toContain('当前草案未引用授权的测评反馈')
  }
  expect(draft).toContain('待心理教师确认')
  expect(draft).toContain('https://www.who.int/')
  expect(draft).not.toContain(observation)
  expect(changes).toEqual([])

  const final = draft + '\n\n合成验证补充｜由校内演示负责人先确认学生是否愿意参加后续沟通'
  await plan.fill(final)
  const pending = page.waitForResponse((response) => response.url().endsWith(casePath + '/transitions'))
  await page.getByRole('button', { name: '保存计划' }).click()
  const saved = await pending
  expect(saved.ok()).toBe(true)
  expect((await saved.json()).data).toMatchObject({ status: 'PLANNED', plan: final })
  expect(changes).toHaveLength(1)
  const check = await page.request.get(origin + casePath)
  expect((await check.json()).data).toMatchObject({ status: 'PLANNED', plan: final })
  const history = await page.request.get(origin + '/api/v1/workspace-agent/conversation')
  const serialized = await history.text()
  expect(serialized).not.toContain(observation)
  expect(serialized).not.toContain('合成验证补充')
  if (expectedFeedback) {
    expect(serialized).not.toContain(expectedFeedback.title)
    expect(serialized).not.toContain(expectedFeedback.body)
  }

  await chooseRole(page, 'TEACHER', '/teacher/workspace')
  expect((await page.request.get(origin + evidencePath)).status()).toBe(403)
  const teacherCopy = await page.request.get(origin + casePath)
  expect(teacherCopy.ok()).toBe(true)
  expect((await teacherCopy.json()).data.plan).toBeNull()
})

test('a specialist approves a synthetic CAT plan and an administrator publishes it', async ({ page }) => {
  const className = process.env.PSYNOVA_AGENT_QA_CLASS
  const useCsv = process.env.PSYNOVA_AGENT_QA_CAT_CSV === '1'
  test.skip(process.env.PSYNOVA_AGENT_QA_WRITE !== '1' || !className, 'Requires a dedicated synthetic class')
  test.setTimeout(240_000)
  await signIn(page)
  await chooseRole(page, 'PSYCHOLOGICAL_SPECIALIST', '/specialist/workspace')
  const bank = new URL('../../01_cat-engine/fixtures/synthetic_item_bank.v1.json', import.meta.url)
  const configuration = new URL('../../01_cat-engine/fixtures/demo_cat_config.v1.json', import.meta.url)
  const [bankText, configText] = await Promise.all([readFile(bank, 'utf8'), readFile(configuration, 'utf8')])
  const source = JSON.parse(bankText).items as {
    item_id: string; stem: string; model: string; response_options: string[];
    parameters: { a: number; thresholds: number[] }
  }[]
  const plan = '合成工程验证' + Date.now().toString(36)
  const due = new Date(Date.now() + 7 * 24 * 60 * 60 * 1_000)
  due.setUTCHours(12, 0, 0, 0)
  const dueDate = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'long' }).format(due)
  const uploadField = page.locator('#workspace-agent-composer input[type="file"]')
  const csvMarker = '合成练习素材 CSVPRIVATEQA'
  const writes: string[] = []
  if (useCsv) {
    await page.setViewportSize({ width: 390, height: 840 })
    page.on('request', (request) => {
      if (request.method() === 'POST') writes.push(new URL(request.url()).pathname)
    })
    const csvField = (value: string | number) => '"' + String(value).replaceAll('"', '""') + '"'
    const chooseCsv = (invalid: boolean) => {
      const rows = source.map((item, index) => [
        item.item_id,
        index === 0 ? csvMarker + '，带逗号和换行\n第二行' : item.stem,
        invalid && index === 1 ? '2PL' : item.model,
        item.parameters.a,
        JSON.stringify(item.parameters.thresholds),
        JSON.stringify(item.response_options),
        'practice',
      ].map(csvField).join(','))
      return uploadField.setInputFiles({
        name: 'synthetic-private-cat.csv', mimeType: 'text/csv',
        buffer: Buffer.from('\ufeffid,stem,model,a,thresholds,options,content\r\n' + rows.join('\r\n')),
      })
    }
    await chooseCsv(true)
    const send = page.getByRole('button', { name: '发送任务' })
    const consent = page.getByRole('checkbox', { name: '我确认这份 CSV 是仅供工程演示的合成题库' })
    await expect(send).toBeDisabled()
    expect(writes).toEqual([])
    await consent.check()
    const rejected = page.waitForResponse((reply) => new URL(reply.url()).pathname.endsWith('/conversation/cat-attachment'))
    await send.click()
    await page.getByRole('button', { name: '同意并发送' }).click()
    expect((await rejected).status()).toBe(422)
    await expect(page.getByText('第 2 条题目记录有误，请检查题目编号、GRM 参数和选项')).toBeVisible()
    expect(writes.filter((path) => path.endsWith('/conversation/turn'))).toEqual([])
    await chooseCsv(false)
    await expect(consent).not.toBeChecked()
    await expect(send).toBeDisabled()
    await consent.check()
  } else {
    await uploadField.setInputFiles({
      name: 'synthetic-cat.json',
      mimeType: 'application/json',
      buffer: Buffer.from(JSON.stringify({ bank_document: JSON.parse(bankText), config_document: JSON.parse(configText) })),
    })
  }
  const purpose = useCsv ? '学校已有的合成工程模板' : '附件配置'
  const privateTurn = page.waitForRequest((request) => request.url().endsWith('/conversation/turn'))
  const results = await ask(page, `请检查合成题库并使用${purpose}准备方案。方案名称是 ${plan}，班级是 ${className}，截止时间是北京时间${dueDate}晚上八点。`, '发送任务', !useCsv)
  expect(results.map((event) => event.view?.kind ?? event.code ?? event.type)).toContain('cat_inspection')
  if (useCsv) {
    const payload = (await privateTurn).postDataJSON()
    expect(payload.attachment).toBe('cat_bank')
    expect(payload.cat_attachment_ref).toMatch(/^[a-f0-9]{32}$/)
    expect(JSON.stringify(payload)).not.toContain(csvMarker)
    expect(JSON.stringify(results)).not.toContain(csvMarker)
    expect(results.find((event) => event.view?.kind === 'cat_inspection')?.view).toMatchObject({
      item_count: source.length, dimension_count: 1, attachment_has_config: false,
    })
    expect(writes.filter((path) => /save-cat-draft|approve-cat-draft|confirm-publication/.test(path))).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391)
  }
  const draft = results.find((event) => event.view?.kind === 'cat_draft')?.view
  expect(draft).toMatchObject({ plan_name: plan, configuration: useCsv ? 'school_template' : 'attachment', state: 'PREVIEW' })
  let card = page.locator('.cat-draft').filter({ hasText: plan }).last()
  await card.getByRole('button', { name: '保存题库和方案' }).click()
  const saving = page.waitForResponse((response) => response.url().endsWith('/conversation/save-cat-draft'))
  await page.getByRole('button', { name: '确认保存', exact: true }).click()
  const saved = await (await saving).json()
  expect(saved.data).toMatchObject({ draft_ref: draft.draft_ref, state: 'SAVED' })
  await card.getByRole('button', { name: '审阅合成施测资格' }).click()
  const approving = page.waitForResponse((response) => response.url().endsWith('/conversation/approve-cat-draft'))
  await page.getByRole('button', { name: '确认批准并交接' }).click()
  const approved = await (await approving).json()
  expect(approved.data).toMatchObject({ draft_ref: draft.draft_ref, state: 'APPROVED' })
  let activationRef: string | undefined
  if (useCsv) {
    const list = await page.request.get(origin + '/api/v1/school/cat-assets/activations')
    expect(list.ok()).toBe(true)
    const { items } = (await list.json()).data
    const active = items.find((item: { plan_name: string }) => item.plan_name === plan)
    expect(active?.status).toBe('ACTIVE')
    activationRef = active.activation_ref
    const asset = await page.request.get(origin + '/api/v1/school/cat-assets/bank-versions/' + active.bank_version_ref)
    expect(asset.ok()).toBe(true)
    const document = (await asset.json()).data.bank_document
    expect(document.items).toHaveLength(source.length)
    expect(document.items[0]).toMatchObject({
      item_id: source[0].item_id,
      stem: csvMarker + '，带逗号和换行\n第二行',
      parameters: source[0].parameters,
      response_options: source[0].response_options,
    })
    expect(document.metadata).toMatchObject({
      synthetic: true, intended_use: 'engineering_test_only', psychological_interpretation_allowed: false,
    })
  }
  await chooseRole(page, 'ADMIN', '/admin/workspace')
  const handoffs = await ask(page, '查看本校已经批准且等待发布的 CAT 交接', '发送任务')
  expect(handoffs.some((event) => event.view?.kind === 'cat_handoffs')).toBe(true)
  card = page.locator('.cat-draft').filter({ hasText: plan }).last()
  await card.getByRole('button', { name: '核对 CAT 发布' }).click()
  const confirmation = page.getByRole('dialog', { name: '确认发布学校测评' })
  await expect(confirmation.getByText(`${plan} · ${className}`, { exact: true })).toBeVisible()
  const publishing = page.waitForResponse((response) => response.url().endsWith('/conversation/confirm-publication'))
  await confirmation.getByRole('button', { name: '确认发布', exact: true }).click()
  const published = await (await publishing).json()
  const task = published.data
  expect(task).toMatchObject({ plan_name: plan, activation_ref: expect.stringMatching(/^CACT_/), plan_version_number: 1 })
  if (activationRef) expect(task.activation_ref).toBe(activationRef)
  expect(new Date(task.due_at).toISOString()).toBe(due.toISOString())
  const index = await page.request.get(origin + '/api/v1/school/admin/task-index')
  expect(index.ok()).toBe(true)
  expect((await index.json()).data).toContainEqual(expect.objectContaining({
    task_ref: task.task_ref, activation_ref: task.activation_ref, class_ref: task.class_ref, status: task.status,
  }))
  await expect(card).toContainText('已发布')
  await page.reload()
  await expect(card).toContainText('已发布')
  if (useCsv) {
    expect(task.published_enrollment_count).toBeGreaterThan(0)
    const assigned = await page.request.get(origin + '/api/v1/school/tasks/' + task.task_ref + '/enrollments')
    expect(assigned.ok()).toBe(true)
    expect((await assigned.json()).data).toHaveLength(task.published_enrollment_count)
  }
})
