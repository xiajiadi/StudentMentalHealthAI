<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Activity, ArrowRight, Building2, CircleHelp, RefreshCw, Settings2, UsersRound } from '@lucide/vue'
import type { DependencyStatusDto } from '@/api/generated/types.gen'
import AppCard from '@/components/app/AppCard.vue'
import AppPageHeader from '@/components/app/AppPageHeader.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import AdminSchoolDirectory from '@/components/school/AdminSchoolDirectory.vue'
import AdminSchoolOperations from '@/components/school/AdminSchoolOperations.vue'
import SchoolResearchManagement from '@/components/school/SchoolResearchManagement.vue'
import { readDependencyHealth } from '@/views/admin/health'
import { useSessionStore } from '@/stores/session'

const route = useRoute()
const session = useSessionStore()
const schoolScopeKey = computed(() => [
  session.user?.userId ?? '', session.role ?? '',
  session.user?.activeContext?.schoolRef ?? '', session.user?.activeContext?.role ?? '',
].join('|'))
const section = computed(() => String(route.params.section ?? 'overview'))
const healthState = ref<'loading' | 'ready' | 'error'>('loading')
const dependencies = ref<Record<string, DependencyStatusDto>>({})
const page = computed(() => ({
  overview: { eyebrow: '学校管理空间', title: '管理概览', intro: '管理班级、人员分配和测评任务，并查看本地服务能力。' },
  users: { eyebrow: '用户与角色', title: '班级与人员', intro: '管理当前学校的目录名称、合成账号和班级分配。' },
  settings: { eyebrow: '系统设置', title: '服务能力状态', intro: '以下只读信息来自 Backend 公开的依赖健康端点，不包含配置写入或管理操作。' },
}[section.value as 'overview' | 'users' | 'settings'] ?? { eyebrow: '学校管理空间', title: '管理概览', intro: '查看本地服务公开的依赖能力状态。' }))
const healthRows = computed(() => Object.entries(dependencies.value ?? {}).map(([name, value]) => ({ name, status: value.status, integration: value.integration })))
const healthLabel = (status: string) => status === 'READY' || status === 'AVAILABLE' ? '可用' : status === 'UNAVAILABLE' ? '不可用' : status === 'DEFERRED' ? '未配置' : status === 'DISABLED' ? '已关闭' : status || '未知'
const healthTone = (status: string) => status === 'READY' || status === 'AVAILABLE' ? 'health-row__status--ready' : status === 'UNAVAILABLE' ? 'health-row__status--down' : 'health-row__status--unknown'

const loadHealth = async () => {
  healthState.value = 'loading'
  try {
    const result = await readDependencyHealth()
    if (!result || typeof result !== 'object' || Array.isArray(result)) throw new Error('依赖状态响应格式无法识别。')
    dependencies.value = result
    healthState.value = 'ready'
  } catch {
    dependencies.value = {}
    healthState.value = 'error'
  }
}

watch(section, (value) => {
  if (value === 'settings') void loadHealth()
}, { immediate: true })
</script>

<template>
  <main class="content-wrap admin-workspace">
    <section class="admin-hero" aria-labelledby="admin-title">
      <img class="admin-hero__flow" :src="'/assets/heartbridge/hero-flow-original.png'" alt="" aria-hidden="true">
      <div class="admin-hero__copy">
        <span class="admin-kicker">HEARTBRIDGE · SCHOOL ADMIN</span>
        <h1 id="admin-title">清晰了解系统，<br>再管理组织事务。</h1>
        <p>组织和任务操作由服务端按当前学校权限处理。此页面不展示个人测评内容或心理判断。</p>
        <div class="admin-hero__note"><Activity :size="15" aria-hidden="true" />全链路验证仍在进行</div>
      </div>
      <figure class="admin-hero__art"><img :src="'/assets/heartbridge/card-admin-original.png'" alt="" aria-hidden="true"><figcaption>服务能力与组织管理入口</figcaption></figure>
    </section>

    <AppPageHeader class="admin-heading" :eyebrow="page.eyebrow" :title="page.title" :intro="page.intro" />

    <template v-if="section === 'overview'">
      <AppStatusCallout tone="info" title="合成演示 · 验证进行中" body="班级和任务操作受当前学校权限约束。系统其他流程仍待端到端验证；本页不开放心理内容或安全复核权限。" />
      <section class="admin-summary" aria-label="管理功能可用状态">
        <AppCard class="admin-feature"><span class="admin-feature__icon"><UsersRound :size="19" aria-hidden="true" /></span><span class="admin-feature__state">按学校授权</span><h2>班级与人员</h2><p>从同校的在用账号中分配教师和学生。</p><RouterLink to="/admin/users">管理班级人员 <ArrowRight :size="15" aria-hidden="true" /></RouterLink></AppCard>
        <AppCard class="admin-feature"><span class="admin-feature__icon admin-feature__icon--teal"><Settings2 :size="19" aria-hidden="true" /></span><span class="admin-feature__state">只读状态</span><h2>服务能力</h2><p>仅读取公开的依赖健康端点，不提供配置变更操作。</p><RouterLink to="/admin/settings">查看服务状态 <ArrowRight :size="15" aria-hidden="true" /></RouterLink></AppCard>
      </section>
      <AdminSchoolOperations :key="schoolScopeKey" />
      <SchoolResearchManagement :key="schoolScopeKey" mode="admin" />
    </template>

    <template v-else-if="section === 'users'">
      <AdminSchoolDirectory />
      <AdminSchoolOperations :key="schoolScopeKey" mode="members" />
      <AppStatusCallout tone="info" title="安全复核权限单独管理" body="学校管理员页面不展示安全复核队列或复核操作。安全复核员（REVIEWER）是独立角色，需使用其专属工作区。" />
    </template>

    <template v-else>
      <AppCard class="health-panel">
        <div class="health-panel__heading"><span class="admin-feature__icon admin-feature__icon--teal"><Activity :size="19" aria-hidden="true" /></span><div><span class="admin-kicker">Backend · GET /health/dependencies</span><h2>依赖能力状态</h2><p>只读公开端点；健康状态不代表 M0 全链路或生产就绪。</p></div><button class="health-refresh" type="button" :disabled="healthState === 'loading'" @click="loadHealth"><RefreshCw :size="15" aria-hidden="true" />刷新</button></div>
        <div v-if="healthState === 'loading'" class="health-message" aria-live="polite">正在读取服务端状态…</div>
        <div v-else-if="healthState === 'error'" class="health-message health-message--error" role="status"><CircleHelp :size="17" aria-hidden="true" />当前无法读取健康端点；状态未知，不以本地占位值代替。</div>
        <div v-else-if="healthRows.length" class="health-list" aria-label="Backend 返回的依赖状态">
          <div v-for="item in healthRows" :key="item.name" class="health-row"><span class="health-row__name">{{ item.name.replaceAll('_', ' ') }}</span><span class="health-row__integration">{{ item.integration || '未提供集成信息' }}</span><span class="health-row__status" :class="healthTone(item.status)"><i aria-hidden="true"></i>{{ healthLabel(item.status) }}</span></div>
        </div>
        <div v-else class="health-message" role="status">端点未返回依赖条目；状态未知。</div>
      </AppCard>
      <AppCard class="health-disclosure"><Building2 :size="18" aria-hidden="true" /><p>组织设置、账号权限和系统配置的读写操作尚不可用。依赖状态属于工程能力信息，不含学生数据或心理判断。</p></AppCard>
    </template>
  </main>
</template>

<style scoped>
.admin-workspace { padding-top: 26px; padding-bottom: 56px; animation: page-in 220ms ease both; }.admin-hero { position: relative; display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(225px, .8fr); align-items: center; min-height: 300px; overflow: hidden; padding: clamp(23px, 4vw, 42px); border: 1px solid #dbe8ef; border-radius: 20px; background: linear-gradient(112deg, #eef5fa 0%, #f7f9fb 56%, #eaf1f7 100%); }.admin-hero__flow { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: .12; pointer-events: none; }.admin-hero__copy { position: relative; z-index: 1; max-width: 570px; }.admin-kicker { color: #54809c; font-size: 10px; font-weight: 800; letter-spacing: .1em; }.admin-hero h1 { margin: 14px 0 12px; color: #2b3d4b; font-family: var(--font-display); font-size: clamp(30px, 4vw, 43px); font-weight: 650; letter-spacing: -.04em; line-height: 1.2; }.admin-hero__copy > p { max-width: 450px; margin: 0; color: #586b79; font-size: 13px; line-height: 1.8; }.admin-hero__note { display: inline-flex; align-items: center; gap: 7px; margin-top: 19px; padding: 8px 11px; border: 1px solid rgb(183 121 31 / 18%); border-radius: 999px; color: #8f651d; background: rgb(255 255 255 / 65%); font-size: 10px; font-weight: 750; }.admin-hero__art { position: relative; justify-self: end; width: min(100%, 240px); margin: 0; text-align: center; }.admin-hero__art img { display: block; width: 100%; max-height: 195px; object-fit: contain; }.admin-hero__art figcaption { margin-top: 5px; color: #71808c; font-size: 10px; }.admin-heading { margin-top: 30px; }
.admin-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 13px; margin-top: 15px; }.admin-feature { position: relative; min-height: 170px; padding: 18px; }.admin-feature__icon { display: grid; width: 38px; height: 38px; place-items: center; border-radius: 11px; color: #167e9b; background: #e8f6f9; }.admin-feature__icon--teal { color: #388576; background: #e8f4ef; }.admin-feature__state { position: absolute; top: 19px; right: 16px; padding: 5px 8px; border-radius: 999px; color: #996517; background: #fbf2de; font-size: 10px; font-weight: 750; }.admin-feature h2 { margin: 13px 0 5px; color: var(--color-text-primary); font-size: 14px; }.admin-feature p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.65; }.admin-feature a { display: inline-flex; align-items: center; gap: 5px; margin-top: 13px; color: #167e9b; font-size: 11px; font-weight: 750; }
.admin-blocked { display: flex; gap: 14px; margin-bottom: 14px; padding: 21px; }.admin-blocked__icon { display: grid; width: 42px; height: 42px; flex: 0 0 42px; place-items: center; border-radius: 12px; color: #9b6a1b; background: #fbf1dc; }.admin-blocked h2 { margin: 7px 0 6px; color: var(--color-text-primary); font-size: 15px; }.admin-blocked p { max-width: 780px; margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.7; }.admin-blocked__foot { display: block; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--color-border); color: var(--color-text-muted); font-size: 10px; }
.health-panel { margin-top: 0; padding: 20px; }.health-panel__heading { display: flex; align-items: center; gap: 12px; }.health-panel__heading h2 { margin: 4px 0; color: var(--color-text-primary); font-size: 15px; }.health-panel__heading p { margin: 0; color: var(--color-text-secondary); font-size: 11px; line-height: 1.6; }.health-refresh { display: inline-flex; align-items: center; gap: 6px; min-height: 34px; margin-left: auto; padding: 0 10px; border: 1px solid var(--color-border); border-radius: 7px; color: var(--color-text-secondary); background: white; cursor: pointer; font-size: 11px; }.health-refresh:disabled { opacity: .6; cursor: wait; }.health-list { margin-top: 17px; border-top: 1px solid var(--color-border); }.health-row { display: grid; grid-template-columns: minmax(105px, .65fr) minmax(0, 1.3fr) 90px; align-items: center; gap: 12px; min-height: 48px; border-bottom: 1px solid var(--color-border); }.health-row__name { color: var(--color-text-primary); font-size: 12px; font-weight: 700; text-transform: capitalize; }.health-row__integration { overflow: hidden; color: var(--color-text-muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.health-row__status { display: inline-flex; align-items: center; gap: 6px; justify-self: end; font-size: 10px; font-weight: 750; }.health-row__status i { width: 7px; height: 7px; border-radius: 50%; background: currentcolor; }.health-row__status--ready { color: #287765; }.health-row__status--down { color: #ac392d; }.health-row__status--unknown { color: #9b6a1b; }.health-message { display: flex; align-items: center; gap: 8px; min-height: 58px; margin-top: 14px; padding: 12px; border-radius: 9px; color: var(--color-text-secondary); background: #f7f8f9; font-size: 11px; }.health-message--error { color: #8f651d; background: #fcf7eb; }.health-disclosure { display: flex; align-items: flex-start; gap: 10px; margin-top: 13px; padding: 14px; color: #6d7c88; }.health-disclosure p { margin: 0; font-size: 11px; line-height: 1.65; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } } @media(max-width:720px) { .admin-workspace { padding-top: 18px; }.admin-hero { grid-template-columns: 1fr; min-height: 0; }.admin-hero__art { display: none; }.admin-heading { margin-top: 24px; }.admin-summary { grid-template-columns: 1fr; }.admin-blocked,.health-panel { padding: 16px; }.health-panel__heading { align-items: flex-start; }.health-row { grid-template-columns: minmax(0,1fr) auto; gap: 5px 10px; padding: 9px 0; }.health-row__integration { grid-column: 1; grid-row: 2; }.health-row__status { grid-column: 2; grid-row: 1 / span 2; } }
</style>
