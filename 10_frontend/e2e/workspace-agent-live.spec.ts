import { Buffer } from 'node:buffer'
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

async function ask(page: Page, prompt: string, label: string) {
  await page.locator('#workspace-agent-input').fill(prompt)
  const pending = page.waitForResponse((response) => response.url().endsWith('/workspace-agent/conversation/turn'), {
    timeout: 40_000,
  })
  await page.getByRole('button', { name: label }).click()
  await page.getByRole('button', { name: '同意并发送' }).click({ timeout: 10_000 })
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
