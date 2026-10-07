import { createRouter, createWebHistory } from 'vue-router'
import type { Role } from '@/types/contracts'
import { useSessionStore } from '@/stores/session'
import { frontendApi } from '@/services/mock-api'

declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean
    roles?: Role[]
    layout?: 'auth' | 'student' | 'teacher' | 'reviewer' | 'focus'
  }
}

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior: (to, _from, savedPosition) => savedPosition ?? (to.hash ? { el: to.hash, behavior: 'smooth' } : { top: 0 }),
  routes: [
    { path: '/', redirect: '/login' },
    { path: '/login', name: 'login', component: () => import('@/views/auth/LoginView.vue'), meta: { public: true, layout: 'auth' } },
    { path: '/student', redirect: '/student/home' },
    { path: '/student/home', name: 'student-home', component: () => import('@/views/student/StudentHomeView.vue'), meta: { roles: ['student'], layout: 'student' } },
    { path: '/student/assessment', name: 'student-assessment', component: () => import('@/views/student/AssessmentView.vue'), meta: { roles: ['student'], layout: 'focus' } },
    { path: '/student/assessment/:id', name: 'student-assessment-resume', component: () => import('@/views/student/AssessmentView.vue'), meta: { roles: ['student'], layout: 'focus' } },
    { path: '/student/assessment/:id/result', name: 'student-assessment-result', component: () => import('@/views/student/AssessmentResultView.vue'), meta: { roles: ['student'], layout: 'student' } },
    { path: '/student/support', name: 'student-support', component: () => import('@/views/student/SupportChatView.vue'), meta: { roles: ['student'], layout: 'student' } },
    { path: '/student/history', name: 'student-history', component: () => import('@/views/student/StudentHomeView.vue'), meta: { roles: ['student'], layout: 'student' } },
    { path: '/student/reports/:id', name: 'student-report-detail', component: () => import('@/views/student/StudentResultView.vue'), meta: { roles: ['student'], layout: 'student' } },
    { path: '/student/result/:id', name: 'student-result', component: () => import('@/views/student/StudentResultView.vue'), meta: { roles: ['student'], layout: 'student' } },
    { path: '/teacher', redirect: '/teacher/overview' },
    { path: '/teacher/overview', name: 'teacher-overview', component: () => import('@/views/teacher/TeacherOverviewView.vue'), meta: { roles: ['teacher'], layout: 'teacher' } },
    { path: '/teacher/students', name: 'teacher-students', component: () => import('@/views/teacher/TeacherStudentsView.vue'), meta: { roles: ['teacher'], layout: 'teacher' } },
    { path: '/teacher/students/:id', name: 'teacher-student-detail', component: () => import('@/views/teacher/TeacherStudentDetailView.vue'), meta: { roles: ['teacher'], layout: 'teacher' } },
    { path: '/reviewer', redirect: '/reviewer/queue' },
    { path: '/reviewer/queue', name: 'reviewer-queue', component: () => import('@/views/reviewer/ReviewQueueView.vue'), meta: { roles: ['reviewer'], layout: 'reviewer' } },
    { path: '/reviewer/cases/:id', name: 'reviewer-detail', component: () => import('@/views/reviewer/ReviewDetailView.vue'), meta: { roles: ['reviewer'], layout: 'reviewer' } },
    { path: '/404', name: 'not-found', component: () => import('@/views/NotFoundView.vue'), meta: { public: true } },
    { path: '/:pathMatch(.*)*', redirect: '/404' },
  ],
})

router.beforeEach(async (to) => {
  const session = useSessionStore()
  if (to.meta.public) return true
  if (!session.isAuthenticated) {
    try {
      const restored = (await frontendApi.getCurrentUser()).data
      if (restored) session.signIn(restored)
    } catch {
      // The guard below gives the user a sign-in path when the local session cannot be restored.
    }
  }
  if (!session.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  const allowedRoles = to.meta.roles
  if (allowedRoles && session.role && !allowedRoles.includes(session.role)) {
    return session.role === 'student' ? { name: 'student-home' } : session.role === 'teacher' ? { name: 'teacher-overview' } : { name: 'reviewer-queue' }
  }
  return true
})

export default router
