import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { expect, test, type Page } from '@playwright/test'

const viewports = [375, 768, 1024, 1440]
const artifactRoot = path.resolve('test-results/visual')

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

async function answerFirstOptionWithKeyboard(page: Page) {
  const option = page.getByRole('radio').first()
  await option.focus()
  if (await option.getAttribute('aria-checked') !== 'true') await page.keyboard.press('Space')
  await expect(option).toHaveAttribute('aria-checked', 'true')
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
    await expect(page.getByRole('heading', { name: '合成演示工作区' })).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await page.screenshot({ path: path.join(artifactRoot, String(width), 'student-home.png'), fullPage: true })
    await page.getByRole('button', { name: '开始测评' }).click()
    await expect(page.getByText('第 1 题，测评进行中')).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await page.screenshot({ path: path.join(artifactRoot, String(width), 'cat-focus.png'), fullPage: true })
    const completeButton = page.getByRole('button', { name: /完成并查看结构/ })
    for (let index = 0; index < 8; index += 1) {
      if (await completeButton.isVisible()) break
      await answerFirstOptionWithKeyboard(page)
      await page.getByRole('button', { name: /保存并继续/ }).click()
    }
    await expect(completeButton).toBeEnabled()
    await completeButton.click()
    await expect(page.getByRole('heading', { name: '本次合成测评已完成' })).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await page.screenshot({ path: path.join(artifactRoot, String(width), 'student-result.png'), fullPage: true })
    await page.getByRole('button', { name: /进入 AI 支持对话/ }).click()
    await page.getByLabel('你的问题').fill('请整理一个可以开始的小步骤。')
    await page.getByRole('button', { name: '发送' }).click()
    await expect(page.getByText('服务端回答')).toBeVisible()
    await expectNoHorizontalOverflow(page)
    await page.screenshot({ path: path.join(artifactRoot, String(width), 'student-support.png'), fullPage: true })
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
