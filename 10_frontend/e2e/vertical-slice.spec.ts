import { expect, test, type Page } from '@playwright/test'

async function loginAs(page: Page, role: 'student' | 'teacher' | 'reviewer') {
  await page.goto('/login')
  const roleLabel = role === 'student' ? '学生' : role === 'teacher' ? '教师' : '复核员'
  await page.getByRole('radio', { name: roleLabel }).click()
  await page.getByLabel('演示账号').fill('demo')
  await page.getByLabel('演示密码').fill('demo')
  await page.getByRole('button', { name: '进入工作区' }).click()
  const target = role === 'student' ? '/student/home' : role === 'teacher' ? '/teacher/overview' : '/reviewer/queue'
  await expect(page).toHaveURL(new RegExp(`${target.replaceAll('/', '\\/')}$`))
}

test('Mock UI 流程：登录 → 学生测评 → 结果 → 支持报告 → 教师复核', async ({ page }) => {
  test.setTimeout(120_000)
  await loginAs(page, 'student')
  await expect(page.getByRole('heading', { name: '合成演示工作区' })).toBeVisible()

  await page.getByRole('button', { name: '开始测评' }).click()
  await expect(page.getByText('第 1 题 · 测评进行中')).toBeVisible()
  for (let index = 0; index < 3; index += 1) {
    await page.getByRole('radio').first().click()
    const saveButton = page.getByRole('button', { name: /保存并继续/ })
    await expect(saveButton).toBeEnabled()
    await saveButton.click()
    await expect(page.locator('.assessment-meta p')).toContainText(`第 ${index + 2} 题`)
  }
  await expect(page.getByText('系统已返回可以结束流程的状态。')).toBeVisible()
  await expect(page.getByRole('button', { name: /完成并查看结构/ })).toBeEnabled()
  await page.getByRole('button', { name: /完成并查看结构/ }).click()
  await expect(page).toHaveURL(/\/student\/assessment\/ASSESS_.*\/result/)
  await expect(page.getByRole('heading', { name: '本次合成测评已完成' })).toBeVisible()
  await expect(page.getByText('教育用途 · 非诊断')).toBeVisible()
  await expect(page.locator('body')).not.toContainText('theta')

  await page.getByRole('button', { name: /进入 AI 支持对话/ }).click()
  await page.getByLabel('你的问题').fill('帮我整理一个今天可以开始的小步骤')
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page.getByText('服务端回答')).toBeVisible()
  await expect(page.getByText('来源', { exact: true })).toBeVisible()
  await expect(page.getByText('报告与对话历史')).toBeVisible()

  await page.getByRole('button', { name: '退出演示' }).click()
  await loginAs(page, 'teacher')
  await expect(page.getByRole('heading', { name: '工作概览' })).toBeVisible()
  await expect(page.getByText('待关注流程')).toBeVisible()

  await page.getByRole('button', { name: '退出演示' }).click()
  await loginAs(page, 'reviewer')
  await expect(page.getByRole('heading', { name: '复核队列' })).toBeVisible()
  await page.getByTestId('review-case-REVIEW_demo_001').click()
  await expect(page.getByText('普通生成已暂停，等待人工复核')).toBeVisible()
  await expect(page.getByRole('button', { name: /生成/ })).toHaveCount(0)
  await page.getByRole('button', { name: '通过' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('button', { name: '确认通过' }).click()
  await expect(page.getByText('本次复核已完成')).toBeVisible()
})

test('Mock UI 登录错误会提供可识别的恢复提示', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('演示密码').fill('wrong')
  await page.getByRole('button', { name: '进入工作区' }).click()
  await expect(page.getByRole('alert')).toContainText('账号或密码不正确')
  await page.getByLabel('演示密码').fill('network')
  await page.getByRole('button', { name: '进入工作区' }).click()
  await expect(page.getByRole('alert')).toContainText('无法连接到演示服务')
})

test('Mock UI 学生测评在窄屏下可用键盘操作且不产生横向滚动', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await loginAs(page, 'student')
  const hasHorizontalOverflow = () => page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)
  expect(await hasHorizontalOverflow()).toBe(false)

  await page.getByRole('button', { name: '开始测评' }).click()
  const firstOption = page.getByRole('radio').first()
  await firstOption.focus()
  await page.keyboard.press('Space')
  await expect(firstOption).toHaveAttribute('aria-checked', 'true')
  expect(await hasHorizontalOverflow()).toBe(false)

  const pauseButton = page.getByRole('button', { name: /暂停并离开/ })
  await pauseButton.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: '关闭对话框' })).toBeFocused()
  await page.keyboard.press('Tab')
  const continueButton = page.getByRole('button', { name: '继续测评' })
  await expect(continueButton).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog')).toHaveCount(0)
})
