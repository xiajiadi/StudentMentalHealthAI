import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import router from '@/router'
import { useSessionStore } from '@/stores/session'

describe('角色路由守卫', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    useSessionStore().signOut()
    await router.push('/login')
  })

  it('未登录访问受保护页面会回到登录并保留目标地址', async () => {
    await router.push('/teacher/overview')
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/teacher/overview')
  })

  it('角色不能跨越自己的工作区', async () => {
    useSessionStore().signIn({ userId: 'USER_demo_teacher', role: 'teacher', subjectId: null, displayName: '演示教师', initials: '师' })
    await router.push('/reviewer/queue')
    expect(router.currentRoute.value.name).toBe('teacher-overview')
  })

  it('允许复核员进入安全复核队列', async () => {
    useSessionStore().signIn({ userId: 'USER_demo_reviewer', role: 'reviewer', subjectId: null, displayName: '演示复核员', initials: '复' })
    await router.push('/reviewer/queue')
    expect(router.currentRoute.value.name).toBe('reviewer-queue')
  })
})
