<script setup lang="ts">
/* global File, clearTimeout, setTimeout */
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppSelect from '@/components/app/AppSelect.vue'
import { catExport, catRequest, type Bank, type Curves, type Design, type DesignConfig, type Experiment, type Session } from '@/services/cat-workbench'

const modes = { banks: '题库中心', designs: '测评设计', sessions: '合成施测', experiments: '仿真实验' }
const props = defineProps<{ openExperiments?: boolean; initialBankFile?: File }>()
const mode = ref<keyof typeof modes>(props.openExperiments ? 'experiments' : 'banks')
watch(() => props.openExperiments, (open) => { if (open) mode.value = 'experiments' })
const banks = ref<Bank[]>([])
const designs = ref<Design[]>([])
const sessions = ref<Session[]>([])
const jobs = ref<Experiment[]>([])
const bank = ref<Bank>()
const session = ref<Session>()
const selectedJob = ref<Experiment>()
const curves = ref<Curves>()
const curveItem = ref('')
const designBank = ref('')
const sessionDesign = ref('')
const experimentBank = ref('')
const schemes = ref<string[]>([])
const file = ref<File | undefined>(props.initialBankFile)
const importName = ref(props.initialBankFile?.name.replace(/\.[^.]+$/, '').slice(0, 100) || '')
watch(() => props.initialBankFile, (selected) => {
  if (!selected || busy.value) return
  file.value = selected
  importName.value = selected.name.replace(/\.[^.]+$/, '').slice(0, 100)
  mode.value = 'banks'
})
const busy = ref(false)
const available = ref(false)
const problem = ref('')
const notice = ref('')
const jobState = { queued: '排队中', running: '运行中', completed: '已完成', failed: '未完成' }
const sessionState = { active: '进行中', paused: '已暂停', completed: '已完成' }
const metrics = { bias: '偏差', rmse: '均方根误差', mae: '平均绝对误差', mean_se: '平均后验标准差', mean_length: '平均题量', coverage_95: '区间覆盖率', bank_utilization: '题库利用率', max_exposure: '最高曝光率' }
const config = reactive({
  name: '', min_items: 5, max_items: 12, se_target: .35, prior_mean: 0,
  prior_sd: 1, selection: 'mfi', top_k: 3, seed: 20261102,
})
const quotas = ref('')
const sampling = reactive({ n: 30, repetitions: 1, seed: 20261102, distribution: 'normal', mean: 0, sd: 1, low: -2.5, high: 2.5 })
const numericFields = [
  { key: 'min_items', label: '最少题数', step: 1 }, { key: 'max_items', label: '最多题数', step: 1 },
  { key: 'se_target', label: '后验标准差目标', step: .01 }, { key: 'prior_mean', label: '先验均值', step: .01 },
  { key: 'prior_sd', label: '先验标准差', step: .01 }, { key: 'top_k', label: '随机候选题数', step: 1 },
  { key: 'seed', label: '随机种子', step: 1 },
] as const

const bankOptions = computed(() => banks.value.map((entry) => ({ value: entry.id, label: entry.name })))
const publishedBanks = computed(() => banks.value.filter((entry) => entry.status === 'published').map((entry) => ({ value: entry.id, label: entry.name })))
const sessionDesigns = computed(() => designs.value.filter((entry) => entry.status === 'published').map((entry) => ({ value: entry.id, label: entry.config.name })))
const experimentDesigns = computed(() => designs.value.filter((entry) => entry.bank_id === experimentBank.value).map((entry) => ({ value: entry.id, label: entry.config.name })))
let poll: ReturnType<typeof setTimeout> | undefined
const pendingAnswer = ref<{ sessionRef: string; item_id: string; score: number; idempotency_key: string; expected_revision: number }>()

async function action(task: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  notice.value = ''
  problem.value = ''
  try { await task() }
  catch (cause) { problem.value = (cause as Error).message }
  finally { busy.value = false }
}

async function reload() {
  const [bankResult, designResult, sessionResult, experimentResult] = await Promise.all([
    catRequest<{ items: Bank[] }>('/banks'), catRequest<{ items: Design[] }>('/designs'),
    catRequest<{ items: Session[] }>('/sessions'), catRequest<{ items: Experiment[] }>('/experiments'),
  ])
  banks.value = bankResult.items
  designs.value = designResult.items
  sessions.value = sessionResult.items
  jobs.value = experimentResult.items
}

async function start() {
  await action(async () => {
    await catRequest('/capabilities')
    await reload()
    available.value = true
  })
}

async function openBank(id: string) {
  bank.value = await catRequest<Bank>(`/banks/${id}`)
  curves.value = undefined
  curveItem.value = ''
}

async function importBank() {
  if (!file.value || file.value.size > 1_500_000) throw new Error('请选择小于 1.5 MB 的 JSON 或 CSV 题库。')
  const contents = await file.value.text()
  const created = file.value.name.toLowerCase().endsWith('.csv')
    ? await catRequest<Bank>('/banks/import-csv', { name: importName.value.trim(), csv: contents })
    : await catRequest<Bank>('/banks', JSON.parse(contents))
  await reload()
  await openBank(created.id)
  notice.value = '已保存题库草稿。'
}

async function changeBank(actionName: 'publish' | 'fork') {
  if (!bank.value) return
  const result = await catRequest<Bank>(`/banks/${bank.value.id}/${actionName}`, {})
  await reload()
  await openBank(result.id)
}

async function viewCurves() {
  if (!curveItem.value || !bank.value) return
  curves.value = await catRequest<Curves>(`/banks/${bank.value.id}/curves?item_id=${encodeURIComponent(curveItem.value)}`)
}

function plot(values: number[]) {
  const scale = Math.max(1, ...values)
  const step = 620 / Math.max(1, values.length - 1)
  return values.map((value, i) => `${i * step},${110 - value / scale * 100}`).join(' ')
}

async function saveDesign() {
  const content_min: DesignConfig['content_min'] = quotas.value.trim() ? JSON.parse(quotas.value) : {}
  await catRequest('/designs', { bank_id: designBank.value, config: { ...config, content_min } })
  await reload()
  notice.value = '已保存测评方案。'
}

async function updateSession(endpoint: string, body?: unknown) {
  session.value = await catRequest<Session>(endpoint, body)
  if (pendingAnswer.value && (session.value.id !== pendingAnswer.value.sessionRef || session.value.revision !== pendingAnswer.value.expected_revision)) pendingAnswer.value = undefined
  await reload()
}

async function answer(score: number) {
  const current = session.value
  if (!current?.next_item) return
  if (pendingAnswer.value && (pendingAnswer.value.sessionRef !== current.id || pendingAnswer.value.score !== score)) {
    throw new Error('上次提交状态未确认，请重试原来的选项。')
  }
  pendingAnswer.value ??= {
    sessionRef: current.id, item_id: current.next_item.id, score, idempotency_key: crypto.randomUUID(), expected_revision: current.revision,
  }
  const { sessionRef, ...payload } = pendingAnswer.value
  await updateSession(`/sessions/${sessionRef}/answers`, payload)
  pendingAnswer.value = undefined
}

async function trackJob(id: string) {
  if (poll) clearTimeout(poll)
  selectedJob.value = await catRequest<Experiment>(`/experiments/${id}`)
  if (selectedJob.value.status === 'queued' || selectedJob.value.status === 'running') {
    poll = setTimeout(() => {
      void trackJob(id).catch(() => { problem.value = '仿真状态暂时无法刷新。请重新打开该任务。' })
    }, 1500)
  } else {
    await reload()
  }
}

async function createExperiment() {
  const configs = designs.value.filter((entry) => schemes.value.includes(entry.id) && entry.bank_id === experimentBank.value).map((entry) => entry.config)
  if (!configs.length || configs.length > 4) throw new Error('请选择 1–4 个来自同一题库的方案。')
  const result = await catRequest<Experiment>('/experiments', { bank_id: experimentBank.value, request: { ...sampling, configs } })
  await reload()
  await trackJob(result.id)
}

onMounted(start)
const cancelPoll = () => { if (poll) clearTimeout(poll); poll = undefined }
onDeactivated(cancelPoll)
onUnmounted(cancelPoll)
onActivated(() => {
  if (selectedJob.value?.status === 'queued' || selectedJob.value?.status === 'running') {
    void trackJob(selectedJob.value.id).catch(() => { problem.value = '仿真状态暂时无法刷新，请重新打开该任务。' })
  }
})
</script>

<template>
  <section class="cat-workbench" aria-label="独立 CAT 研究工作台">
    <h1 class="sr-only">CAT 管理</h1>
    <p v-if="notice" class="cat-workbench__notice" role="status">{{ notice }}</p>
    <p v-if="problem" class="cat-workbench__error" role="alert">{{ problem }}</p>
    <AppButton v-if="!available && problem" variant="secondary" @click="start">重新连接</AppButton>
    <p v-else-if="!available" role="status">正在连接独立 CAT 引擎…</p>
    <template v-if="available">
      <nav class="cat-workbench__nav" aria-label="工作台功能">
        <AppButton v-for="(label, key) in modes" :key="key" :variant="mode === key ? 'primary' : 'secondary'" :aria-pressed="mode === key" @click="mode = key">{{ label }}</AppButton>
      </nav>
      <div v-if="mode === 'banks'" class="cat-workbench__split">
        <AppCard class="cat-workbench__card">
          <h3>题库与版本</h3>
          <AppButton :disabled="busy" @click="action(async () => { const result = await catRequest<Bank>('/banks/demo', {}); await reload(); await openBank(result.id) })">创建合成题库</AppButton>
          <form class="cat-workbench__form" @submit.prevent="action(importBank)">
            <label>导入 JSON 或 CSV<input type="file" accept=".json,.csv" @change="file = ($event.target as HTMLInputElement).files?.[0]"></label>
            <p v-if="initialBankFile && file === initialBankFile">对话中选择的文件 {{ file.name }}</p>
            <label v-if="file?.name.toLowerCase().endsWith('.csv')">CSV 题库名称<input v-model="importName" required maxlength="100"></label>
            <AppButton type="submit" variant="secondary" :disabled="!file || busy">导入题库</AppButton>
          </form>
          <AppButton v-for="entry in banks" :key="entry.id" variant="quiet" :aria-pressed="bank?.id === entry.id" @click="action(() => openBank(entry.id))">{{ entry.name }} · {{ entry.item_count }} 题 · {{ entry.status === 'published' ? '已发布' : '草稿' }}</AppButton>
        </AppCard>
        <AppCard class="cat-workbench__card">
          <template v-if="bank">
            <h3>{{ bank.name }}</h3>
            <div class="cat-workbench__actions">
              <AppButton v-if="bank.status === 'draft'" :disabled="busy" @click="action(() => changeBank('publish'))">发布工程版本</AppButton>
              <AppButton variant="secondary" :disabled="busy" @click="action(() => changeBank('fork'))">另存为草稿</AppButton>
              <a :href="catExport(`/banks/${bank.id}/export`)" download="cat-bank.json">导出 JSON</a>
            </div>
            <label for="cat-curve-item">类别概率曲线
              <AppSelect id="cat-curve-item" v-model="curveItem" placeholder="选择要核对的题目" :options="(bank.items ?? []).map(item => ({ value: item.id, label: item.stem }))" @update:model-value="action(viewCurves)" />
            </label>
            <div v-if="curves" class="cat-workbench__curves">
              <figure v-for="(values, index) in [curves.iif, curves.tif, ...curves.probabilities.map((_, i) => curves!.probabilities.map(row => row[i] ?? 0)).slice(0, curves.probabilities[0]?.length ?? 0)]" :key="index">
                <figcaption>{{ index === 0 ? '题目信息' : index === 1 ? '题库信息' : `选项 ${index - 1} 概率` }}</figcaption>
                <svg viewBox="0 0 620 120" role="img" :aria-label="index === 0 ? '题目信息曲线' : index === 1 ? '题库信息曲线' : `选项 ${index - 1} 概率曲线`" preserveAspectRatio="none"><polyline :points="plot(values)" fill="none" stroke="currentColor" stroke-width="2" /></svg>
              </figure>
            </div>
            <ol class="cat-workbench__list">
              <li v-for="item in bank.items" :key="item.id">{{ item.stem }} <small>{{ item.model }} · {{ item.content }}</small></li>
            </ol>
          </template>
          <p v-else>选择一份题库，查看题目、版本和曲线。</p>
        </AppCard>
      </div>
      <div v-else-if="mode === 'designs'" class="cat-workbench__split">
        <AppCard class="cat-workbench__card">
          <h3>新建测评方案</h3>
          <form class="cat-workbench__form" @submit.prevent="action(saveDesign)">
            <label for="cat-design-bank">绑定已发布题库<AppSelect id="cat-design-bank" v-model="designBank" placeholder="选择题库" :options="publishedBanks" /></label>
            <label>方案名称<input v-model="config.name" required maxlength="100"></label>
            <label for="cat-selection">选题策略<AppSelect id="cat-selection" v-model="config.selection" :options="[{ value:'mfi',label:'最大信息量' }, { value:'random',label:'随机' }, { value:'randomesque',label:'从高信息候选中随机' }]" /></label>
            <div class="cat-workbench__fields">
              <label v-for="field in numericFields" :key="field.key">{{ field.label }}<input v-model.number="config[field.key]" type="number" :step="field.step" required></label>
            </div>
            <label>各类别最少出题数（可选）<input v-model="quotas" placeholder='例如 {"communication": 2}'></label>
            <AppButton type="submit" :disabled="busy || !designBank">保存方案</AppButton>
          </form>
        </AppCard>
        <AppCard class="cat-workbench__card">
          <h3>本校方案</h3>
          <p v-if="!designs.length">还没有方案。</p>
          <ul class="cat-workbench__list">
            <li v-for="entry in designs" :key="entry.id"><strong>{{ entry.config.name }}</strong> · {{ entry.config.min_items }}–{{ entry.config.max_items }} 题
              <AppButton v-if="entry.status === 'draft'" variant="secondary" size="sm" :disabled="busy" @click="action(async () => { await catRequest(`/designs/${entry.id}/publish`, {}); await reload() })">发布工程方案</AppButton>
              <small v-else>已发布</small>
            </li>
          </ul>
        </AppCard>
      </div>
      <div v-else-if="mode === 'sessions'" class="cat-workbench__split">
        <AppCard class="cat-workbench__card">
          <h3>合成施测</h3>
          <label for="cat-session-design">选择已发布方案<AppSelect id="cat-session-design" v-model="sessionDesign" placeholder="选择方案" :options="sessionDesigns" /></label>
          <AppButton :disabled="busy || !sessionDesign" @click="action(() => updateSession('/sessions', { design_id: sessionDesign }))">开始新会话</AppButton>
          <AppButton v-for="entry in sessions" :key="entry.id" variant="quiet" :aria-pressed="session?.id === entry.id" @click="action(() => updateSession(`/sessions/${entry.id}`))">{{ entry.id.slice(0, 8) }} · {{ sessionState[entry.status] }} · 已答 {{ entry.revision }}</AppButton>
        </AppCard>
        <AppCard class="cat-workbench__card">
          <template v-if="session">
            <h3>{{ sessionState[session.status] }} · 已答 {{ session.revision }} 题</h3>
            <div class="cat-workbench__actions">
              <AppButton v-if="session.status === 'active'" variant="secondary" :disabled="busy" @click="action(() => updateSession(`/sessions/${session!.id}/pause`, {}))">暂停</AppButton>
              <AppButton v-if="session.status === 'paused'" :disabled="busy" @click="action(() => updateSession(`/sessions/${session!.id}/resume`, {}))">继续作答</AppButton>
              <a :href="catExport(`/sessions/${session.id}/provenance`)" download="cat-session.json">导出复现记录</a>
            </div>
            <template v-if="session.status === 'active' && session.next_item">
              <p>{{ session.next_item.stem }}</p>
              <AppButton v-for="(option,index) in session.next_item.options" :key="index" variant="secondary" :disabled="busy || (Boolean(pendingAnswer) && pendingAnswer?.score !== index)" @click="action(() => answer(index))">{{ option }}</AppButton>
            </template>
            <p>能力估计 {{ session.theta.toFixed(3) }}，后验标准差 {{ session.se.toFixed(3) }}</p>
            <details v-if="session.trace.length"><summary>作答轨迹</summary><ol><li v-for="step in session.trace" :key="step.index">{{ step.item_id }} · 选项 {{ step.score + 1 }} · 标准差 {{ step.se.toFixed(3) }}</li></ol></details>
          </template>
          <p v-else>开始新会话或继续已有的合成会话。</p>
        </AppCard>
      </div>
      <div v-else class="cat-workbench__split">
        <AppCard class="cat-workbench__card">
          <h3>多方案仿真</h3>
          <p>合成仿真结果仅用于工程验证</p>
          <form class="cat-workbench__form" @submit.prevent="action(createExperiment)">
            <label for="cat-experiment-bank">题库<AppSelect id="cat-experiment-bank" v-model="experimentBank" placeholder="选择题库" :options="bankOptions" @update:model-value="schemes = []" /></label>
            <label for="cat-experiment-schemes">方案（最多四个）<AppSelect id="cat-experiment-schemes" v-model="schemes" multiple placeholder="选择方案" :options="experimentDesigns" :disabled="!experimentBank" /></label>
            <label for="cat-distribution">能力分布<AppSelect id="cat-distribution" v-model="sampling.distribution" :options="[{ value: 'normal', label: '正态' }, { value: 'uniform', label: '均匀' }, { value: 'grid', label: '等距' }]" /></label>
            <div class="cat-workbench__fields">
              <label>样本数<input v-model.number="sampling.n" type="number" min="10" max="1000" required></label>
              <label>重复次数<input v-model.number="sampling.repetitions" type="number" min="1" max="5" required></label>
              <label>随机种子<input v-model.number="sampling.seed" type="number" min="0" required></label>
              <label v-if="sampling.distribution === 'normal'">均值<input v-model.number="sampling.mean" type="number" step="0.1" required></label>
              <label v-if="sampling.distribution === 'normal'">标准差<input v-model.number="sampling.sd" type="number" min="0.1" step="0.1" required></label>
              <label v-if="sampling.distribution !== 'normal'">能力下界<input v-model.number="sampling.low" type="number" step="0.1" required></label>
              <label v-if="sampling.distribution !== 'normal'">能力上界<input v-model.number="sampling.high" type="number" step="0.1" required></label>
            </div>
            <AppButton type="submit" :disabled="busy || !experimentBank || !schemes.length">运行仿真</AppButton>
          </form>
          <AppButton v-for="job in jobs" :key="job.id" variant="quiet" :aria-pressed="job.id === selectedJob?.id" @click="action(() => trackJob(job.id))">{{ job.id.slice(0,8) }} · {{ jobState[job.status] }}</AppButton>
        </AppCard>
        <AppCard class="cat-workbench__card">
          <template v-if="selectedJob">
            <h3>{{ jobState[selectedJob.status] }}</h3>
            <p v-if="selectedJob.error">{{ selectedJob.error }}</p>
            <AppButton v-if="selectedJob.status === 'failed'" :disabled="busy" @click="action(async () => { const result = await catRequest<Experiment>(`/experiments/${selectedJob!.id}/retry`, {}); await reload(); await trackJob(result.id) })">按原设定重试</AppButton>
            <div v-if="selectedJob.status === 'completed'" class="cat-workbench__actions">
              <a v-for="format in ['json','csv','md']" :key="format" :href="catExport(`/experiments/${selectedJob.id}/export?format=${format}`)" :download="`cat-experiment.${format}`">导出 {{ format.toUpperCase() }}</a>
            </div>
            <section v-for="scheme in selectedJob.result?.schemes" :key="scheme.name" class="cat-workbench__scheme">
              <h4>{{ scheme.name }}</h4>
              <dl><div v-for="(label,key) in metrics" :key="key"><dt>{{ label }}</dt><dd>{{ scheme.metrics[key]?.toFixed(3) }}</dd></div></dl>
              <details><summary>区间误差与题目曝光</summary>
                <ul><li v-for="row in scheme.conditional" :key="row.low">{{ row.low }} 至 {{ row.high }} · {{ row.n }} 人 · RMSE {{ row.rmse.toFixed(3) }}</li></ul>
                <ul><li v-for="row in scheme.exposure" :key="row.item_id">{{ row.item_id }} · {{ (row.rate * 100).toFixed(1) }}%</li></ul>
              </details>
            </section>
          </template>
          <p v-else>选择一项实验查阅进度、结果与导出。</p>
        </AppCard>
      </div>
    </template>
  </section>
</template>

<style scoped>
.cat-workbench { display: grid; gap: 14px; min-width: 0; }
.cat-workbench h2,.cat-workbench h3,.cat-workbench h4,.cat-workbench p { margin: 0; }
.cat-workbench h2 { font: 650 22px/1.4 var(--font-display); }
.cat-workbench h3 { font-size: 16px; }
.cat-workbench p,.cat-workbench small { color: var(--color-text-secondary); font-size: 13px; }
.cat-workbench__nav,.cat-workbench__actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.cat-workbench__actions a { color: var(--color-primary); font-size: 13px; }
.cat-workbench__split { display: grid; grid-template-columns: minmax(240px, 35%) minmax(0,1fr); gap: 12px; align-items: start; }
.cat-workbench__card,.cat-workbench__form { display: grid; gap: 10px; min-width: 0; }
.cat-workbench__card { padding: 14px; }
.cat-workbench__card button { justify-self: start; }
.cat-workbench label { display: grid; gap: 5px; min-width: 0; color: var(--color-text-secondary); font-size: 13px; }
.cat-workbench input { width: 100%; min-width: 0; min-height: 38px; padding: 6px 9px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); background: var(--color-surface); color: var(--color-text-primary); font: inherit; }
.cat-workbench input:focus-visible { border-color: var(--color-primary); outline: 2px solid color-mix(in srgb,var(--color-primary) 25%,transparent); }
.cat-workbench__fields,.cat-workbench__curves,.cat-workbench__scheme dl { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px; }
.cat-workbench__list { margin: 0; padding-inline-start: 20px; font-size: 13px; }
.cat-workbench__list > li { padding: 6px 0; border-bottom: 1px solid var(--color-border); }
.cat-workbench__list small { display: inline-block; margin-inline-start: 5px; }
.cat-workbench__curves figure { margin: 0; padding: 8px; border: 1px solid var(--color-border); border-radius: var(--radius-control); font-size: 12px; }
.cat-workbench__curves svg { width: 100%; color: var(--color-primary); }
.cat-workbench__scheme { padding: 10px; border: 1px solid var(--color-border); border-radius: var(--radius-card); font-size: 13px; }
.cat-workbench__scheme dl { margin: 8px 0; }
.cat-workbench__scheme dd { margin: 0; font-weight: 650; }
.cat-workbench .cat-workbench__error { color: var(--color-critical); }
.cat-workbench .cat-workbench__notice { color: var(--color-primary); }
@media (max-width: 730px) { .cat-workbench__split { grid-template-columns: minmax(0,1fr); } }
</style>
