<script setup lang="ts">
import AppSelect from '@/components/app/AppSelect.vue'
import AppSelectOption from '@/components/app/AppSelectOption.vue'
import {computed, nextTick, ref, watch} from 'vue'
import {Activity, ArrowRight, BookOpen, Check, GraduationCap, LayoutDashboard, UsersRound} from '@lucide/vue'
import AppButton from '../components/app/AppButton.vue'
import AppCard from '../components/app/AppCard.vue'
import wordmark from '../../public/assets/psynova/wordmark.png?url'
import hero from '../../public/assets/heartbridge/hero-flow-original.png?url'
import {applyAction, choices, classRows, demoClass, feedbackText, historicRecords, newWorkspace, questions, restoreWorkspace, roles, roster, studentFeedback} from './workflow'
import type {Role} from './workflow'

const storageKey = 'psynova-public-demo-v1'
const storageAvailable = ref(true)
function load() {
  try { return restoreWorkspace(sessionStorage.getItem(storageKey)) }
  catch { storageAvailable.value = false; return newWorkspace() }
}
const state = ref(load())
const heading = ref<HTMLElement>()
const selectedClass = ref(demoClass.id)
const rosterVisible = ref(false)
const selectedAnswer = ref<number>()
const answering = ref(false)
const releaseConfirmed = ref(false)
const aiExample = ref<'grounded' | 'abstain' | 'safety'>('grounded')
const notice = ref('')
const overallCompleted = classRows.reduce((sum, row) => sum + row.completed, 0)
const visibleRoster = computed(() => roster.filter((person) => person.classId === selectedClass.value))
const questionCount = computed(() => state.value.answers.length)
const publishedFeedback = computed(() => studentFeedback(state.value))
const supportLabel = computed(() => ({none: '未提出', requested: '待心理老师受理', assigned: '已分派，待班主任反馈', reported: '班主任已反馈，待复核', closed: '已结案'})[state.value.support])
const sections: {role: Role; title: string; icon: typeof Activity; done: () => boolean}[] = [
  {role: 'admin', title: '发布测评', icon: LayoutDashboard, done: () => state.value.published},
  {role: 'student', title: '作答与恢复', icon: GraduationCap, done: () => state.value.completed},
  {role: 'teacher', title: '查看班级进度', icon: UsersRound, done: () => state.value.teacherViewed},
  {role: 'specialist', title: '复核并发布反馈', icon: Activity, done: () => state.value.feedback === 'published'},
]

function persist() {
  try { sessionStorage.setItem(storageKey, JSON.stringify(state.value)) }
  catch { storageAvailable.value = false }
}
watch(state, persist, {flush: 'sync'})

function action(value: Parameters<typeof applyAction>[1], message = '') {
  const updated = applyAction(state.value, value)
  if (updated !== state.value) {
    state.value = updated
    notice.value = message
  }
}

async function enter(role: Role) {
  action({type: 'role', role})
  answering.value = false
  selectedAnswer.value = undefined
  releaseConfirmed.value = false
  rosterVisible.value = false
  await nextTick()
  heading.value?.focus()
}

function nextQuestion() {
  if (selectedAnswer.value === undefined) return
  action({type: 'answer', value: selectedAnswer.value}, '已保存该题。')
  selectedAnswer.value = undefined
}

async function begin() {
  action({type: 'enter'})
  await enter('admin')
}

function reset() {
  if (!window.confirm('清空此标签页的演练进度并重新开始？')) return
  state.value = newWorkspace()
  answering.value = false
  selectedAnswer.value = undefined
  releaseConfirmed.value = false
  notice.value = ''
}
</script>

<template>
  <a class="demo-skip" href="#workspace">跳至工作区</a>
  <header class="demo-header">
    <div class="demo-page demo-header-inner">
      <img :src="wordmark" alt="PsyNova" width="158" height="40">
      <span class="demo-marker">合成数据 · 公开演练</span>
      <AppButton v-if="state.started" variant="quiet" size="sm" @click="reset">重新开始</AppButton>
    </div>
  </header>

  <main id="workspace" class="demo-page">
    <section v-if="!state.started" class="demo-intro">
      <AppCard raised flush>
        <div class="demo-hero" :style="{backgroundImage: `url(${hero})`}">
          <div class="demo-hero-copy">
            <p class="demo-kicker">PsyNova 校园工作台</p>
            <h1>走一遍学校测评流程</h1>
            <p>用合成学校练习发布任务、学生作答、班级跟进和反馈复核。不用账号，也不用提供真实个人信息。</p>
            <AppButton @click="begin">开始四端演练 <ArrowRight :size="17" aria-hidden="true" /></AppButton>
          </div>
        </div>
      </AppCard>
      <div class="demo-metrics" aria-label="合成学校概览">
        <AppCard class="demo-panel"><span>合成学生</span><strong>{{ roster.length }}</strong></AppCard>
        <AppCard class="demo-panel"><span>演示班级</span><strong>{{ classRows.length }}</strong></AppCard>
        <AppCard class="demo-panel"><span>已完成的历史报名</span><strong>{{ overallCompleted }}</strong></AppCard>
        <AppCard class="demo-panel"><span>业务角色</span><strong>4</strong></AppCard>
      </div>
      <p class="demo-note">这是独立的浏览器演练，不连接学校的账号、数据库或 AI 服务。进度保留在当前标签页；关掉后请重新开始。</p>
    </section>

    <div v-else class="demo-layout">
      <nav class="demo-nav" aria-label="演练角色">
        <h2>演练角色</h2>
        <button v-for="item in sections" :key="item.role" class="demo-nav-button" type="button" :aria-current="state.role === item.role ? 'step' : undefined" @click="enter(item.role)">
          <component :is="item.icon" :size="18" aria-hidden="true" />
          <span><strong>{{ roles[item.role] }}</strong><small>{{ item.title }}</small></span>
          <Check v-if="item.done()" :size="16" aria-label="步骤完成" />
        </button>
        <p>切换的是演练视角，不会登录真实学校账号。</p>
      </nav>

      <div class="demo-content">
        <div class="demo-heading">
          <p class="demo-kicker">合成学校 · {{ roles[state.role] }}</p>
          <h1 ref="heading" tabindex="-1">{{ sections.find((item) => item.role === state.role)?.title }}</h1>
          <p v-if="notice" class="demo-notice" role="status">{{ notice }}</p>
          <p v-if="state.feedback === 'published' && state.teacherViewed && state.support === 'closed'" class="demo-notice">四端演练已完成：班级测评和校内支持均已走通。</p>
          <p v-if="!storageAvailable" class="demo-note" role="status">浏览器禁止保存进度。刷新或关闭后将重新开始。</p>
        </div>

        <template v-if="state.role === 'admin'">
          <AppCard class="demo-panel demo-stack">
            <h2>新生学习安排 · 测评练习</h2>
            <p>本轮练习使用 {{ demoClass.name }}。合成学生已入班，班主任为 {{ demoClass.teacher }}。练习题不输出个人心理分数。</p>
            <div class="demo-actions">
              <AppButton v-if="!state.published" @click="action({type: 'publish'}, '测评已发布。')">发布到 {{ demoClass.name }}</AppButton>
              <template v-else><span class="demo-marker">已发布 · {{ demoClass.enrolled }} 人报名</span><AppButton @click="enter('student')">前往学生端 <ArrowRight :size="16" aria-hidden="true" /></AppButton></template>
            </div>
          </AppCard>
          <AppCard class="demo-panel demo-stack">
            <h2>学校名册与历史进度</h2>
            <p>{{ classRows.length }} 个班、{{ roster.length }} 条独立合成名册记录。下表为历史演练，不包含个人作答。</p>
            <div class="demo-table-scroll" tabindex="0" aria-label="班级历史汇总">
              <table><thead><tr><th scope="col">班级</th><th scope="col">班主任</th><th scope="col">历史报名</th><th scope="col">已完成</th></tr></thead>
                <tbody><tr v-for="row in classRows" :key="row.id"><th scope="row">{{ row.name }}</th><td>{{ row.teacher }}</td><td>{{ row.enrolled }}</td><td>{{ row.completed }}</td></tr></tbody>
              </table>
            </div>
            <div class="demo-actions"><label for="sample-roster">选择合成班级</label><AppSelect id="sample-roster" v-model="selectedClass"><AppSelectOption v-for="row in classRows" :key="row.id" :value="row.id">{{ row.name }}</AppSelectOption></AppSelect><AppButton variant="secondary" @click="rosterVisible = !rosterVisible">{{ rosterVisible ? '收起名册' : '查看合成名册' }}</AppButton></div>
            <div v-if="rosterVisible" class="demo-table-scroll demo-roster" tabindex="0" aria-label="合成名册">
              <table><thead><tr><th scope="col">演示编号</th><th scope="col">姓名占位</th><th scope="col">历史练习</th></tr></thead>
                <tbody><tr v-for="person in visibleRoster" :key="person.id"><th scope="row">{{ person.id }}</th><td>{{ person.name }}</td><td>{{ person.previousTaskCompleted ? '已完成' : '未完成' }}</td></tr></tbody>
              </table>
            </div>
          </AppCard>
        </template>

        <template v-else-if="state.role === 'student'">
          <AppCard class="demo-panel demo-stack">
            <h2>我的测评</h2>
            <template v-if="!state.published"><p>管理员还没有发布本轮练习。</p><AppButton variant="secondary" @click="enter('admin')">切换到学校管理员</AppButton></template>
            <template v-else-if="state.completed">
              <p class="demo-notice">新生学习安排 · 已完成。完成只表示试答已提交。</p>
              <AppButton @click="enter('teacher')">前往班主任端 <ArrowRight :size="16" aria-hidden="true" /></AppButton>
            </template>
            <template v-else-if="!answering"><p>新生学习安排 · 已保存 {{ questionCount }}/{{ questions.length }} 题。</p><AppButton @click="answering = true">{{ questionCount ? '继续测评' : '开始测评' }}</AppButton></template>
            <template v-else>
              <span class="demo-marker">已保存 {{ questionCount }}/{{ questions.length }} 题</span>
              <fieldset v-if="questionCount < questions.length" :key="questionCount" class="demo-question"><legend>第 {{ questionCount + 1 }} 题：{{ questions[questionCount] }}</legend>
                <label v-for="(choice, index) in choices" :key="choice"><input v-model="selectedAnswer" name="demo-answer" type="radio" :value="index">{{ choice }}</label>
              </fieldset>
              <div class="demo-actions">
                <AppButton v-if="questionCount < questions.length" :disabled="selectedAnswer === undefined" @click="nextQuestion">保存并下一题</AppButton>
                <AppButton v-else @click="action({type: 'complete'}, '已完成测评。'); answering = false">确认完成</AppButton>
                <AppButton variant="secondary" @click="answering = false; selectedAnswer = undefined">保存进度并离开</AppButton>
              </div>
            </template>
          </AppCard>
          <AppCard class="demo-panel demo-stack">
            <h2>我的记录与反馈</h2>
            <ul class="demo-records"><li v-for="item in historicRecords" :key="item.date"><strong>{{ item.name }}</strong><small>{{ item.date }} · {{ item.status }} · {{ item.source }}</small></li></ul>
            <p v-if="publishedFeedback" class="demo-notice"><strong>已发布反馈：</strong>{{ publishedFeedback }}</p>
            <p v-else>本轮暂无已发布反馈。未发布草稿不会显示在学生端。</p>
          </AppCard>
          <AppCard class="demo-panel demo-stack">
            <h2>向学校求助</h2><p>预置请求：想和班主任核对下一项课业计划。不接收真实姓名或自由文本。</p>
            <AppButton v-if="state.support === 'none'" variant="secondary" @click="action({type: 'request'}, '已提交预置支持请求。')">提交练习请求</AppButton>
            <p v-else class="demo-marker">我的支持状态：{{ supportLabel }}</p>
          </AppCard>
          <AppCard class="demo-panel demo-stack">
            <h2>AI 教育支持 · 结果示例</h2><p>这些是预置示例，公开演练不会发送问题，也不会调用 AI。</p>
            <label for="demo-ai-example">查看示例</label><AppSelect id="demo-ai-example" v-model="aiExample"><AppSelectOption value="grounded">有依据的回答</AppSelectOption><AppSelectOption value="abstain">没有符合条件的依据</AppSelectOption><AppSelectOption value="safety">进入安全提示</AppSelectOption></AppSelect>
            <div v-if="aiExample === 'grounded'" class="demo-note"><strong>参考做法：</strong>先核对课程要求，再选择今天可以做完的一个小步骤。<br><strong>参考来源：</strong>项目原创合成《大学生学习任务规划》· 从课程要求整理计划。</div>
            <div v-else-if="aiExample === 'abstain'" class="demo-note">当前没有符合条件的资料。示例不生成回答或引用。</div>
            <div v-else class="demo-note">合成测试信号触发安全提示，普通回复暂停。此示例不提供危机咨询。</div>
          </AppCard>
        </template>

        <template v-else-if="state.role === 'teacher'">
          <AppCard class="demo-panel demo-stack">
            <h2>{{ demoClass.name }} · 授权班级汇总</h2>
            <p>这里只显示班级任务的报名与完成人数，不显示学生姓名、答卷或专业反馈。</p>
            <div class="demo-table-scroll"><table><thead><tr><th scope="col">任务</th><th scope="col">有效报名</th><th scope="col">已完成</th><th scope="col">待完成</th></tr></thead><tbody>
              <tr><th scope="row">历史 · 校园资源了解</th><td>{{ demoClass.enrolled }}</td><td>{{ demoClass.completed }}</td><td>{{ demoClass.enrolled - demoClass.completed }}</td></tr>
              <tr v-if="state.published"><th scope="row">本轮 · 新生学习安排</th><td>{{ demoClass.enrolled }}</td><td>{{ state.completed ? 1 : 0 }}</td><td>{{ demoClass.enrolled - (state.completed ? 1 : 0) }}</td></tr>
            </tbody></table></div>
            <AppButton @click="enter('specialist')">前往心理老师端 <ArrowRight :size="16" aria-hidden="true" /></AppButton>
          </AppCard>
          <AppCard class="demo-panel demo-stack"><h2>班主任跟进</h2><p>{{ supportLabel }}</p>
            <template v-if="state.support === 'assigned'"><p>分派事项：与合成学生一起核对一项课业安排。</p><AppButton variant="secondary" @click="action({type: 'report'}, '已提交预置班主任反馈。')">提交练习跟进反馈</AppButton></template>
          </AppCard>
        </template>

        <template v-else>
          <AppCard class="demo-panel demo-stack">
            <h2>班级测评复核</h2>
            <p>只使用一条预置的学校支持反馈演练草拟与发布，不读取学生答卷，也不生成测量学结论。</p>
            <p v-if="!state.completed">暂无完成的本轮记录。请先以学生视角完成测评。</p>
            <AppButton v-else-if="state.feedback === 'none'" @click="action({type: 'draft'}, '已创建预置草稿，学生仍不可见。')">创建合成反馈草稿</AppButton>
            <template v-else-if="state.feedback === 'draft'">
              <p class="demo-note"><strong>待发布：</strong>{{ feedbackText }}</p>
              <label class="demo-confirm"><input v-model="releaseConfirmed" type="checkbox">我已核对，这是一份合成演练反馈。</label>
              <AppButton :disabled="!releaseConfirmed" @click="action({type: 'release'}, '已发布练习反馈。')">确认并发布反馈</AppButton>
            </template>
            <template v-else><p class="demo-notice">已发布 · 学生现在可以查看。</p><AppButton @click="enter('student')">回到学生端查看反馈 <ArrowRight :size="16" aria-hidden="true" /></AppButton></template>
          </AppCard>
          <AppCard class="demo-panel demo-stack"><h2>学生支持</h2><p>{{ supportLabel }}</p>
            <AppButton v-if="state.support === 'requested'" variant="secondary" @click="action({type: 'assign'}, '已受理并分派给班主任。')">受理并分派练习任务</AppButton>
            <AppButton v-if="state.support === 'reported'" variant="secondary" @click="action({type: 'close'}, '已确认反馈并结案。')">确认反馈并结案</AppButton>
          </AppCard>
        </template>
      </div>
    </div>

    <footer class="demo-footer"><BookOpen :size="17" aria-hidden="true" /> 仅用于合成学校操作演练，不用于心理诊断，也不接收真实学生数据。</footer>
  </main>
</template>
