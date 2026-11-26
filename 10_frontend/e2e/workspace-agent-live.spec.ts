import { Buffer } from 'node:buffer'
import { readFile } from 'node:fs/promises'
import { expect, test, type Page } from '@playwright/test'

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

test('the public learner and teacher use live tools under their own roles', async ({ page }) => {
  test.setTimeout(180_000)
  await signIn(page)
  await chooseRole(page, 'STUDENT', '/student/workspace')
  const student = await ask(page, '查一下我现在能做的测评任务。', '发送消息')
  expect(student.some((event) => event.view?.kind === 'student_tasks')).toBe(true)
  await expect(page.getByText(/我的测评任务 · /).last()).toBeVisible()
  await page.reload()
  await expect(page.getByText(/我的测评任务 · /).last()).toBeVisible()
  await chooseRole(page, 'TEACHER', '/teacher/workspace')
  const teacher = await ask(page, '查一下授权班级已有的测评以及完成进度。', '发送任务')
  expect(teacher.some((event) => event.view?.kind === 'class_progress')).toBe(true)
  expect(teacher.some((event) => event.view?.kind === 'student_tasks')).toBe(false)
  await expect(page.getByText(/授权班级测评进度 · /).last()).toBeVisible()
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
  await expect(page.getByText(current.body, { exact: true })).toBeVisible()
  await expect(page).toHaveURL(origin + '/student/workspace')
  await page.getByText('怎么读这份反馈', { exact: true }).click()
  await page.getByRole('button', { name: '查看学校支持' }).click()
  await expect(page.getByRole('heading', { name: '提交求助请求' })).toBeVisible()
  await expect(page).toHaveURL(origin + '/student/workspace')
  await chooseRole(page, 'TEACHER', '/teacher/workspace')
  const denied = await page.request.get(origin + '/api/v1/school/feedback/student/' + current.feedback_ref)
  expect(denied.status()).toBe(403)
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

test('a synthetic learner resumes and submits a real assessment inside the conversation', async ({ page }) => {
  test.skip(process.env.PSYNOVA_AGENT_QA_WRITE !== '1', 'Requires a dedicated synthetic school')
  test.setTimeout(270_000)
  await signIn(page)
  await chooseRole(page, 'STUDENT', '/student/workspace')
  const listed = await ask(page, '看看我现在还有哪些测评待做', '发送消息')
  const tasks = listed.find((event) => event.view?.kind === 'student_tasks')?.view.rows
  expect(tasks?.some((row: { status: string }) => ['created', 'in_progress', 'not_started'].includes(row.status))).toBe(true)
  const selected = await ask(page, '继续刚才查到的测评，已有进度的优先，否则打开最早截止的一项', '发送消息', false)
  const taskRef = selected.find((event) => event.view?.kind === 'assessment_picker')?.view.task_ref
  expect(taskRef).toBeTruthy()
  await page.reload()
  await page.getByRole('button', { name: '阅读说明并打开测评' }).last().click()
  const started = page.waitForResponse((response) => response.url().endsWith(`/school/tasks/${taskRef}/start`))
  await page.getByRole('button', { name: '我已阅读，开始或继续' }).click()
  const startResponse = await started
  expect(startResponse.ok()).toBe(true)
  const initial = (await startResponse.json()).data
  const { assessment_id: assessmentId } = initial
  const assessment = page.locator('.assessment-page--embedded')
  await expect(assessment).toBeVisible()
  const finish = assessment.getByRole('button', { name: /^(完成|完成测评)$/ })
  await expect(assessment.getByRole('radio').first().or(finish).first()).toBeVisible()
  let saved = 0
  while (!(await finish.isVisible()) && saved < (initial.max_items ?? 30)) {
    const response = page.waitForResponse((reply) => reply.url().endsWith(`/assessments/${assessmentId}/responses`))
    await assessment.getByRole('radio').first().click()
    await assessment.getByRole('button', { name: '下一题' }).click()
    expect((await response).ok()).toBe(true)
    saved += 1
    await expect(assessment.getByText(`已记录 ${initial.answered_count + saved} 项`, { exact: true })).toBeVisible()
  }
  const completion = page.waitForResponse((response) => response.url().endsWith(`/assessments/${assessmentId}/complete`))
  await finish.click()
  const completed = await completion
  expect(completed.ok()).toBe(true)
  expect((await completed.json()).data).toMatchObject({ assessment_id: assessmentId, status: 'completed' })
  await expect(assessment.getByText('已保存测评作答')).toBeVisible()
  await expect(page.getByRole('button', { name: '查看已发布反馈' })).toBeVisible()
  const history = await page.request.get(origin + '/api/v1/school/tasks/student/history')
  expect(history.ok()).toBe(true)
  expect((await history.json()).data).toContainEqual(expect.objectContaining({
    task_ref: taskRef, assessment_id: assessmentId, assessment_status: 'completed',
  }))
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

test('a specialist approves a synthetic CAT plan and an administrator publishes it', async ({ page }) => {
  const className = process.env.PSYNOVA_AGENT_QA_CLASS
  test.skip(process.env.PSYNOVA_AGENT_QA_WRITE !== '1' || !className, 'Requires a dedicated synthetic class')
  test.setTimeout(240_000)
  await signIn(page)
  await chooseRole(page, 'PSYCHOLOGICAL_SPECIALIST', '/specialist/workspace')
  const bank = new URL('../../01_cat-engine/fixtures/synthetic_item_bank.v1.json', import.meta.url)
  const configuration = new URL('../../01_cat-engine/fixtures/demo_cat_config.v1.json', import.meta.url)
  const [bankText, configText] = await Promise.all([readFile(bank, 'utf8'), readFile(configuration, 'utf8')])
  const plan = '合成工程验证' + Date.now().toString(36)
  const due = new Date(Date.now() + 7 * 24 * 60 * 60 * 1_000)
  due.setUTCHours(12, 0, 0, 0)
  const dueDate = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'long' }).format(due)
  await page.locator('#workspace-agent-composer input[type="file"]').setInputFiles({
    name: 'synthetic-cat.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify({ bank_document: JSON.parse(bankText), config_document: JSON.parse(configText) })),
  })
  const results = await ask(page, `请检查合成题库并使用附件配置准备方案。方案名称是 ${plan}，班级是 ${className}，截止时间是北京时间${dueDate}晚上八点。`, '发送任务')
  expect(results.map((event) => event.view?.kind ?? event.code ?? event.type)).toContain('cat_inspection')
  const draft = results.find((event) => event.view?.kind === 'cat_draft')?.view
  expect(draft).toMatchObject({ plan_name: plan, configuration: 'attachment', state: 'PREVIEW' })
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
  expect(new Date(task.due_at).toISOString()).toBe(due.toISOString())
  const index = await page.request.get(origin + '/api/v1/school/admin/task-index')
  expect(index.ok()).toBe(true)
  expect((await index.json()).data).toContainEqual(expect.objectContaining({
    task_ref: task.task_ref, activation_ref: task.activation_ref, class_ref: task.class_ref, status: task.status,
  }))
  await expect(card).toContainText('已发布')
  await page.reload()
  await expect(card).toContainText('已发布')
})
