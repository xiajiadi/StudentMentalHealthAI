/* global HTMLTextAreaElement */
import { Buffer } from 'node:buffer'
import { readFile } from 'node:fs/promises'
import { URL } from 'node:url'
import { expect, test, type Page } from '@playwright/test'
import { workbook } from '../tests/fixtures/workbook'

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
  await expect(page.getByRole('status').filter({ hasText: '正在检查输入' })).toBeVisible({ timeout: 30_000 })
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
  await expect(page.getByRole('button', { name: '查看已发布反馈' })).toBeVisible()
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
  await expect(page.getByRole('button', { name: '查看已发布反馈' })).toBeVisible()
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
  await expect(page.getByRole('button', { name: '查看已发布反馈' })).toBeVisible()
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
  const events = await ask(page, '整理我当前指派的待处理复核记录，按测评任务查看数量', '发送任务')
  const resultKinds = events.map((event) => event.view?.kind ?? event.code ?? event.type)
  expect(resultKinds).toContain('professional_review_queue')
  const queue = events.find((event) => event.view?.kind === 'professional_review_queue')?.view
  expect(queue.open_count + queue.in_review_count).toBeGreaterThan(0)
  const task = queue.tasks[0]
  const work = '/api/v1/school/professional-reviews/tasks/' + encodeURIComponent(task.task_ref)
  let open = 0
  let reviewing = 0
  for (let offset = 0; ; offset += 50) {
    const list = await page.request.get(origin + work + `/cases?offset=${offset}&limit=50`)
    expect(list.ok()).toBe(true)
    const { items, total } = (await list.json()).data
    open += items.filter((item: { status: string }) => item.status === 'OPEN').length
    reviewing += items.filter((item: { status: string }) => item.status === 'IN_REVIEW').length
    if (offset + 50 >= total) break
  }
  expect(task).toMatchObject({ open_count: open, in_review_count: reviewing })
  const cases = page.waitForResponse((response) => response.url().startsWith(origin + work + '/cases?'))
  const buttons = page.getByRole('button', { name: '查看该任务复核记录' })
  await buttons.nth(await buttons.count() - queue.tasks.length).click()
  expect((await cases).ok()).toBe(true)
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
