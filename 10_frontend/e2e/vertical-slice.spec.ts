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

test('登录 → 学生测评 → 结果 → 教师 → 人工复核垂直切片', async ({ page }) => {
  test.setTimeout(120_000)
  await loginAs(page, 'student')
  await expect(page.getByRole('heading', { name: '先看见现在，再决定下一步' })).toBeVisible()

  await page.getByRole('button', { name: /开始一次测评/ }).click()
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
  await expect(page).toHaveURL(/\/student\/result\//)
  await expect(page.getByRole('heading', { name: '你的支持参考' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '为什么会看到这些建议' })).toBeVisible()
  await expect(page.locator('body')).not.toContainText('theta')

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

test('登录错误会提供可识别的恢复提示', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('演示密码').fill('wrong')
  await page.getByRole('button', { name: '进入工作区' }).click()
  await expect(page.getByRole('alert')).toContainText('账号或密码不正确')
  await page.getByLabel('演示密码').fill('network')
  await page.getByRole('button', { name: '进入工作区' }).click()
  await expect(page.getByRole('alert')).toContainText('无法连接到演示服务')
})
