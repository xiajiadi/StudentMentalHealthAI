<script setup lang="ts">
import { LogOut } from '@lucide/vue'
import { useRouter } from 'vue-router'
import AppLogo from '@/components/app/AppLogo.vue'
import AppBadge from '@/components/app/AppBadge.vue'
import { useSessionStore } from '@/stores/session'

const router = useRouter()
const session = useSessionStore()

const logout = () => {
  session.signOut()
  void router.push('/login')
}
</script>

<template>
  <div class="student-layout app-shell">
    <header class="student-header">
      <div class="student-header__inner">
        <RouterLink to="/student/home" class="student-header__brand" aria-label="心桥学生首页"><AppLogo /></RouterLink>
        <nav class="student-header__nav" aria-label="学生导航">
          <RouterLink to="/student/home" exact-active-class="student-header__link--active">我的支持</RouterLink>
          <RouterLink to="/student/result/REPORT_demo_student_001" exact-active-class="student-header__link--active">最近结果</RouterLink>
        </nav>
        <div class="student-header__account">
          <AppBadge tone="blue" dot>演示环境</AppBadge>
          <span class="student-header__avatar" aria-hidden="true">{{ session.user?.initials || '学' }}</span>
          <button class="student-header__logout" type="button" aria-label="退出演示" @click="logout">
            <LogOut :size="16" aria-hidden="true" />
          </button>
        </div>
      </div>
    </header>
    <main><slot /></main>
  </div>
</template>

<style scoped>
.student-header { position: sticky; z-index: 30; top: 0; border-bottom: 1px solid rgb(228 231 236 / 88%); background: rgb(247 248 250 / 94%); backdrop-filter: blur(12px); }
.student-header__inner { display: flex; align-items: center; width: min(100% - 40px, 1120px); min-height: 68px; margin: 0 auto; gap: 28px; }
.student-header__brand { color: var(--color-text-primary); }
.student-header__nav { display: flex; align-items: center; gap: 4px; margin-right: auto; }
.student-header__nav a { position: relative; display: inline-flex; align-items: center; min-height: 42px; padding: 0 12px; border-radius: 6px; color: var(--color-text-secondary); font-size: 13px; font-weight: 700; transition: color var(--motion-fast) ease, background-color var(--motion-fast) ease; }
.student-header__nav a:hover { color: var(--color-primary); background: var(--color-info-wash); }
.student-header__link--active { color: var(--color-primary) !important; }
.student-header__link--active::after { position: absolute; right: 12px; bottom: 1px; left: 12px; height: 2px; content: ""; background: var(--color-primary); }
.student-header__account { display: flex; align-items: center; gap: 10px; }
.student-header__avatar { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 50%; color: var(--color-primary); background: var(--color-info-wash); font-size: 13px; font-weight: 800; }
.student-header__logout { display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border: 0; border-radius: 7px; color: var(--color-text-secondary); background: transparent; cursor: pointer; }
.student-header__logout:hover { color: var(--color-primary); background: var(--color-info-wash); }

@media (max-width: 600px) {
  .student-header__inner { width: min(100% - 28px, 1120px); min-height: 60px; gap: 10px; }
  .student-header__nav { gap: 0; overflow-x: auto; margin: 0; }
  .student-header__nav a { padding: 0 8px; font-size: 12px; white-space: nowrap; }
  .student-header__account .app-badge { display: none; }
}
</style>
