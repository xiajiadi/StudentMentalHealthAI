<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ArrowRight } from '@lucide/vue'
import { BookOpen } from '@lucide/vue'
import { CheckCircle2 } from '@lucide/vue'
import { Compass } from '@lucide/vue'
import { MessageCircle } from '@lucide/vue'
import { RotateCcw } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppPageHeader from '@/components/app/AppPageHeader.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { frontendApi, MockApiError } from '@/services/mock-api'
import type { StudentHomeViewModel } from '@/types/view-models'
import { useRouter } from 'vue-router'

const router = useRouter()
const state = ref<'loading' | 'ready' | 'empty' | 'error'>('loading')
const data = ref<StudentHomeViewModel | null>(null)
const errorMessage = ref('')

const iconFor = (icon: 'book' | 'message' | 'compass') => ({ book: BookOpen, message: MessageCircle, compass: Compass }[icon])

const load = async () => {
  state.value = 'loading'
  errorMessage.value = ''
  try {
    const response = await frontendApi.getStudentHome()
    data.value = response.data
    state.value = response.data ? 'ready' : 'empty'
  } catch (error) {
    state.value = 'error'
    errorMessage.value = error instanceof MockApiError ? error.message : '页面暂时没有准备好，请稍后重试。'
  }
}

const startAssessment = () => void router.push('/student/assessment')
const viewReport = () => void router.push(`/student/result/${data.value?.recent.reportId || 'REPORT_demo_student_001'}`)

onMounted(load)
</script>

<template>
  <div class="content-wrap content-wrap--student student-home">
    <div v-if="state === 'loading'" class="student-loading" aria-busy="true" aria-label="正在加载学生首页">
      <div class="skeleton skeleton--short"></div>
      <div class="skeleton skeleton--title"></div>
      <div class="skeleton skeleton--body"></div>
      <div class="student-loading__grid"><div class="skeleton skeleton--panel"></div><div class="skeleton skeleton--panel"></div></div>
    </div>

    <template v-else-if="state === 'error'">
      <AppStatusCallout tone="critical" title="学生首页暂时无法加载" :body="errorMessage">
        <AppButton variant="secondary" size="sm" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新加载</AppButton>
      </AppStatusCallout>
    </template>

    <template v-else-if="state === 'empty'">
      <AppPageHeader eyebrow="学生空间" title="从今天的一个小步骤开始" intro="这里会放置你已授权查看的支持参考。完成一次合成测评后，可以回到这里查看下一步。" fixture-label="合成演示案例" />
      <AppCard class="student-empty" raised>
        <div class="student-empty__mark" aria-hidden="true"><Compass :size="23" /></div>
        <h2>还没有可查看的记录</h2>
        <p>先完成一次测评流程，页面会在完成后展示结构化的支持参考。</p>
        <AppButton @click="startAssessment">开始一次测评 <ArrowRight :size="17" aria-hidden="true" /></AppButton>
      </AppCard>
    </template>

    <template v-else-if="data">
      <AppPageHeader eyebrow="学生空间" :title="data.greeting" intro="把最近的状态整理成一个可行动的下一步。" :fixture-label="data.fixtureLabel">
        <template #actions><AppBadge tone="teal" dot>支持参考已准备</AppBadge></template>
      </AppPageHeader>

      <section class="student-home__lead" aria-labelledby="student-state-title">
        <AppCard class="student-home__state" raised>
          <div class="student-home__state-top">
            <div>
              <span class="section-label">最近状态</span>
              <h2 id="student-state-title">{{ data.stateTitle }}</h2>
            </div>
            <span class="student-home__state-icon" aria-hidden="true"><CheckCircle2 :size="23" /></span>
          </div>
          <p>{{ data.stateBody }}</p>
          <div class="student-home__state-meta">
            <span><strong>已完成</strong> {{ data.recent.date }}</span>
            <RouterLink :to="`/student/result/${data.recent.reportId}`">查看最近结果 <ArrowRight :size="14" aria-hidden="true" /></RouterLink>
          </div>
        </AppCard>

        <AppCard class="student-home__next">
          <div class="student-home__next-label"><span>下一步</span><span class="student-home__index">01</span></div>
          <h2>{{ data.nextAction.title }}</h2>
          <p>{{ data.nextAction.body }}</p>
          <AppButton block @click="startAssessment">{{ data.nextAction.cta }} <ArrowRight :size="17" aria-hidden="true" /></AppButton>
        </AppCard>
      </section>

      <section class="student-home__support" aria-labelledby="support-title">
        <div class="section-heading">
          <div><span class="section-label">支持工具</span><h2 id="support-title" class="section-title">现在可以做什么</h2></div>
          <span class="section-heading__rule" aria-hidden="true"></span>
        </div>
        <div class="support-grid">
          <AppCard v-for="item in data.supportLinks" :key="item.title" class="support-item">
            <span class="support-item__icon" aria-hidden="true"><component :is="iconFor(item.icon)" :size="18" /></span>
            <div><h3>{{ item.title }}</h3><p>{{ item.body }}</p></div>
            <ArrowRight class="support-item__arrow" :size="16" aria-hidden="true" />
          </AppCard>
        </div>
      </section>

      <AppStatusCallout tone="info" title="页面边界" body="本轮页面只使用合成数据。真实部署时，显示内容由后端权限和安全披露策略共同决定。" />

      <section class="student-home__recent" aria-labelledby="recent-title">
        <div class="section-heading">
          <div><span class="section-label">最近记录</span><h2 id="recent-title" class="section-title">{{ data.recent.label }}</h2></div>
          <button class="text-link" type="button" @click="viewReport">查看详情 <ArrowRight :size="14" aria-hidden="true" /></button>
        </div>
        <AppCard class="recent-row">
          <span class="recent-row__icon" aria-hidden="true"><CheckCircle2 :size="18" /></span>
          <div class="recent-row__copy"><strong>{{ data.recent.status }}</strong><span>{{ data.recent.date }} · {{ data.recent.reportId }}</span></div>
          <AppBadge tone="teal" dot>可查看</AppBadge>
        </AppCard>
      </section>
    </template>
  </div>
</template>

<style scoped>
.student-home { animation: page-in 260ms ease both; }
.section-label { color: var(--color-text-muted); font-size: 11px; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; }
.student-home__lead { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(280px, 0.65fr); gap: 16px; }
.student-home__state, .student-home__next { padding: 25px; }
.student-home__state { position: relative; overflow: hidden; border-color: rgb(37 99 235 / 16%); background: var(--color-surface); }
.student-home__state::before { position: absolute; top: 0; bottom: 0; left: 0; width: 4px; content: ""; background: var(--color-primary); }
.student-home__state-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.student-home__state h2 { max-width: 500px; margin: 10px 0 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: clamp(22px, 3vw, 30px); letter-spacing: -0.04em; line-height: 1.35; }
.student-home__state p { max-width: 560px; margin: 14px 0 27px; color: var(--color-text-secondary); font-size: 14px; line-height: 1.8; }
.student-home__state-icon { display: inline-flex; align-items: center; justify-content: center; width: 42px; height: 42px; border-radius: 50%; color: var(--color-support); background: var(--color-support-wash); }
.student-home__state-meta { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding-top: 14px; border-top: 1px solid var(--color-border); color: var(--color-text-muted); font-size: 12px; }
.student-home__state-meta strong { color: var(--color-support); }
.student-home__state-meta a { display: inline-flex; align-items: center; gap: 5px; color: var(--color-primary); font-weight: 700; }
.student-home__state-meta a:hover { text-decoration: underline; text-underline-offset: 3px; }
.student-home__next { display: flex; flex-direction: column; justify-content: space-between; border-color: rgb(15 118 110 / 16%); background: var(--color-support-wash); }
.student-home__next-label { display: flex; justify-content: space-between; color: var(--color-support); font-size: 11px; font-weight: 800; letter-spacing: 0.1em; text-transform: uppercase; }
.student-home__index { font-family: var(--font-mono); opacity: 0.66; }
.student-home__next h2 { margin: 36px 0 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: 21px; line-height: 1.45; }
.student-home__next p { margin: 9px 0 25px; color: var(--color-text-secondary); font-size: 13px; line-height: 1.7; }
.student-home__support { margin-top: 45px; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 18px; margin-bottom: 14px; }
.section-heading__rule { display: block; width: 100px; height: 1px; margin-bottom: 5px; background: var(--color-border-strong); }
.support-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.support-item { display: flex; align-items: flex-start; gap: 12px; min-height: 104px; padding: 17px; transition: border-color var(--motion-fast) ease, transform var(--motion-fast) ease, box-shadow var(--motion-fast) ease; }
.support-item:hover { border-color: rgb(37 99 235 / 30%); box-shadow: var(--shadow-raised); transform: translateY(-2px); }
.support-item__icon { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; flex: 0 0 32px; border-radius: 7px; color: var(--color-primary); background: var(--color-info-wash); }
.support-item h3 { margin: 1px 0 4px; color: var(--color-text-primary); font-size: 13px; font-weight: 800; }
.support-item p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.support-item__arrow { align-self: center; margin-left: auto; color: var(--color-text-muted); }
.student-home > .status-callout { margin-top: 27px; }
.student-home__recent { margin-top: 39px; }
.text-link { display: inline-flex; align-items: center; gap: 5px; border: 0; color: var(--color-primary); background: transparent; cursor: pointer; font-size: 12px; font-weight: 700; }
.text-link:hover { text-decoration: underline; text-underline-offset: 3px; }
.recent-row { display: flex; align-items: center; gap: 13px; padding: 15px 17px; }
.recent-row__icon { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; flex: 0 0 32px; border-radius: 50%; color: var(--color-support); background: var(--color-support-wash); }
.recent-row__copy { display: grid; flex: 1; gap: 3px; min-width: 0; }
.recent-row__copy strong { overflow: hidden; color: var(--color-text-primary); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.recent-row__copy span { overflow: hidden; color: var(--color-text-muted); font-family: var(--font-mono); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.student-empty { display: grid; justify-items: center; padding: 55px 24px; text-align: center; }
.student-empty__mark { display: inline-flex; align-items: center; justify-content: center; width: 52px; height: 52px; border: 1px solid rgb(37 99 235 / 18%); border-radius: 12px; color: var(--color-primary); background: var(--color-info-wash); }
.student-empty h2 { margin: 18px 0 7px; font-family: var(--font-display); font-size: 22px; }
.student-empty p { max-width: 400px; margin: 0 0 22px; color: var(--color-text-secondary); font-size: 13px; line-height: 1.7; }
.student-loading { padding-top: 18px; }
.skeleton { position: relative; overflow: hidden; border-radius: 7px; background: var(--color-surface-skeleton); }
.skeleton::after { position: absolute; inset: 0; content: ""; background: linear-gradient(90deg, transparent, rgb(255 255 255 / 58%), transparent); animation: shimmer 1.4s infinite; transform: translateX(-100%); }
.skeleton--short { width: 110px; height: 13px; }
.skeleton--title { width: min(480px, 70%); height: 35px; margin-top: 17px; }
.skeleton--body { width: min(620px, 90%); height: 16px; margin-top: 13px; }
.student-loading__grid { display: grid; grid-template-columns: 1.35fr 0.65fr; gap: 16px; margin-top: 32px; }
.skeleton--panel { height: 210px; }

@keyframes page-in { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
@keyframes shimmer { to { transform: translateX(100%); } }

@media (max-width: 760px) {
  .student-home__lead, .student-loading__grid { grid-template-columns: 1fr; }
  .support-grid { grid-template-columns: 1fr; }
  .student-home__state, .student-home__next { padding: 20px; }
  .student-home__next h2 { margin-top: 24px; }
}

@media (max-width: 480px) {
  .student-home__state-meta { display: grid; justify-content: stretch; gap: 9px; }
  .recent-row { align-items: flex-start; }
  .recent-row .app-badge { align-self: center; }
}
</style>
