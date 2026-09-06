import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { expect, test, type Page } from '@playwright/test'

const viewports = [375, 768, 1024, 1440]
const artifactRoot = path.resolve('reports/artifacts/visual')

async function loginAs(page: Page, role: 'student' | 'teacher' | 'reviewer') {
  await page.goto('/login')
  const roleLabel = role === 'student' ? '学生' : role === 'teacher' ? '教师' : '复核员'
  await page.getByRole('radio', { name: roleLabel }).click()
  await page.getByLabel('演示账号').fill('demo')
  await page.getByLabel('演示密码').fill('demo')
  await page.getByRole('button', { name: '进入工作区' }).click()
  await expect(page).toHaveURL(new RegExp(`/${role === 'student' ? 'student/home' : role === 'teacher' ? 'teacher/overview' : 'reviewer/queue'}$`))
}

async function expectNoHorizontalOverflow(page: Page) {
  const metrics = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth + 1)
}

test('保存四档代表性页面视口证据', async ({ browser }) => {
  test.setTimeout(120_000)
  await Promise.all(viewports.map((width) => mkdir(path.join(artifactRoot, String(width)), { recursive: true })))

  for (const width of viewports) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce' })
    const page = await context.newPage()

    await page.goto('/login')
    await expectNoHorizontalOverflow(page)
    await page.screenshot({ path: path.join(artifactRoot, String(width), 'login.png'), fullPage: true })
    await loginAs(page, 'student')
    await expect(page.getByRole('heading', { name: '先看见现在，再决定下一步' })).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await page.screenshot({ path: path.join(artifactRoot, String(width), 'student-home.png'), fullPage: true })
    await page.getByRole('button', { name: /开始一次测评/ }).click()
    await expect(page.getByText('第 1 题 · 测评进行中')).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await page.screenshot({ path: path.join(artifactRoot, String(width), 'cat-focus.png'), fullPage: true })
    await page.getByRole('button', { name: /暂停并离开/ }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.getByRole('button', { name: '离开测评' }).click()
    await expect(page.getByRole('heading', { name: '先看见现在，再决定下一步' })).toBeVisible()
    await page.getByRole('button', { name: /查看详情/ }).click()
    await expect(page.getByRole('heading', { name: '你的支持参考' })).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await page.screenshot({ path: path.join(artifactRoot, String(width), 'student-result.png'), fullPage: true })
    await context.close()

    const teacherContext = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce' })
    const teacherPage = await teacherContext.newPage()
    await loginAs(teacherPage, 'teacher')
    await expect(teacherPage.getByRole('heading', { name: '工作概览' })).toBeVisible()
    await expectNoHorizontalOverflow(teacherPage)
    await teacherPage.screenshot({ path: path.join(artifactRoot, String(width), 'teacher-overview.png'), fullPage: true })
    await teacherContext.close()

    const reviewerContext = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce' })
    const reviewerPage = await reviewerContext.newPage()
    await loginAs(reviewerPage, 'reviewer')
    await expect(reviewerPage.getByRole('heading', { name: '复核队列' })).toBeVisible()
    await expectNoHorizontalOverflow(reviewerPage)
    await reviewerPage.screenshot({ path: path.join(artifactRoot, String(width), 'review-queue.png'), fullPage: true })
    await reviewerPage.getByTestId('review-case-REVIEW_demo_001').click()
    await expect(reviewerPage.getByText('普通生成已暂停，等待人工复核')).toBeVisible()
    await expectNoHorizontalOverflow(reviewerPage)
    await reviewerPage.screenshot({ path: path.join(artifactRoot, String(width), 'review-detail.png'), fullPage: true })
    await reviewerContext.close()

  }
})
