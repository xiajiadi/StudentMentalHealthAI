<script setup lang="ts">
/* global File, HTMLInputElement, BodyInit, DragEvent */
import { onMounted, ref, watch } from 'vue'
import { FileText, Upload } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppDialog from '@/components/app/AppDialog.vue'

type Layer = 'policy' | 'theory' | 'intervention'
type Document = { ref: string; title: string; layer: Layer; imported_at: string; chunk_count: number }
type Match = { ref: string; title: string; layer: Layer; ordinal: number; text: string }
const labels = { policy: '政策与实施', theory: '理论与研究', intervention: '预防与干预' }
const endpoint = '/api/v1/school/research-sources/library'
const props = defineProps<{ showResults: boolean; showEmpty: boolean; initialFile?: File }>()
const showImport = defineModel<boolean>('showImport', { required: true })
const emit = defineEmits<{ imported: [] }>()
const maxFiles = 10
const maxBytes = 50 * 1024 * 1024
const queue = ref<{ file: File; status: 'ready' | 'uploading' | 'done' | 'failed'; note: string }[]>([])
const documents = ref<Document[]>([])
const hits = ref<Match[]>([])
const reviewed = ref(false)
const busy = ref(false)
const dragging = ref(false)
const searched = ref(false)
const message = ref('')
const problem = ref('')
const listProblem = ref('')
const loadingDocuments = ref(false)
const fileInput = ref<HTMLInputElement>()
const searching = ref(false)
const withdrawTarget = ref<{ ref: string; title: string }>()
const withdrawing = ref(false)
const withdrawProblem = ref('')
const withdrawnRefs = new Set<string>()
let searchVersion = 0

async function call<Payload>(path: string, method: 'GET' | 'POST' | 'DELETE' = 'GET', body?: BodyInit, headers: Record<string, string> = {}) {
  if (method !== 'GET') {
    const csrf = await fetch('/api/v1/auth/csrf', { credentials: 'same-origin', cache: 'no-store' })
    const token = csrf.ok ? (await csrf.json()).data?.csrf_token : undefined
    if (typeof token !== 'string' || !token) throw new Error('登录状态已过期，请重新登录。')
    headers['X-CSRF-Token'] = token
  }
  const response = await fetch(endpoint + path, { method, body, headers, credentials: 'same-origin', cache: 'no-store' })
  if (response.status === 401) throw new Error('登录状态已过期，请重新登录。')
  if (response.status === 403) throw new Error('当前角色无权访问本校知识库。')
  if (response.status === 404 && method === 'DELETE') throw new Error('本校目录中找不到这份资料')
  if (response.status === 409 && path === '/documents') throw new Error('这份资料已撤回，请核对后导入更新版本')
  if ((response.status === 422 || response.status === 400 || response.status === 413) && path === '/documents') {
    throw new Error('未能读取文件。请检查文件大小、格式和可选取文字。')
  }
  if (!response.ok) throw new Error('本校知识库暂时不可用，请稍后重试。')
  return (await response.json()).data as Payload
}

async function loadDocuments() {
  if (loadingDocuments.value) return
  listProblem.value = ''
  loadingDocuments.value = true
  try {
    documents.value = (await call<{ items: Document[] }>('/documents')).items.filter((item) => !withdrawnRefs.has(item.ref))
  } catch (cause) {
    listProblem.value = (cause as Error).message
  } finally {
    loadingDocuments.value = false
  }
}

function chooseFiles(next: ArrayLike<File> | null | undefined) {
  if (!next?.length) return
  message.value = ''
  problem.value = ''
  reviewed.value = false
  const files = Array.from(next)
  queue.value = files.slice(0, maxFiles).map((file) => {
    const valid = /\.(pdf|docx|txt|md)$/i.test(file.name) && file.size > 0 && file.size <= maxBytes
    return { file, status: valid ? 'ready' : 'failed', note: valid ? '待导入' : '文件格式、大小或内容不符合要求。' }
  })
  if (files.length > maxFiles) problem.value = `每批最多 ${maxFiles} 个文件，已选中前 ${maxFiles} 个。`
}

watch(() => props.initialFile, (file) => { if (file) chooseFiles([file]) }, { immediate: true })

function acceptDrop(event: DragEvent) {
  dragging.value = false
  if (!busy.value) chooseFiles(event.dataTransfer?.files)
}

async function upload() {
  if (!queue.value.some((row) => row.status === 'ready') || !reviewed.value || busy.value) return
  busy.value = true
  problem.value = ''
  message.value = ''
  for (const row of queue.value.filter((item) => item.status === 'ready')) {
    row.status = 'uploading'
    row.note = '正在导入…'
    try {
      const result = await call<{ document: Document; created: boolean }>('/documents', 'POST', row.file, {
        'Content-Type': 'application/octet-stream',
        'X-PsyNova-Filename': encodeURIComponent(row.file.name),
        'X-PsyNova-Reviewed': 'yes',
      })
      const { document } = result
      documents.value = [document, ...documents.value.filter((entry) => entry.ref !== document.ref)]
      row.status = 'done'
      row.note = result.created ? `${labels[document.layer]}，${document.chunk_count} 个片段` : '此前已导入'
    } catch (cause) {
      row.status = 'failed'
      row.note = (cause as Error).message
    }
  }
  const complete = queue.value.filter((row) => row.status === 'done').length
  const failed = queue.value.filter((row) => row.status === 'failed').length
  message.value = `处理完成，${complete} 项可检索，${failed} 项未导入`
  if (fileInput.value) fileInput.value.value = ''
  reviewed.value = false
  busy.value = false
  if (complete) emit('imported')
  if (complete && !failed) showImport.value = false
}

function updateImportOpen(open: boolean) {
  if (!busy.value) showImport.value = open
}

function openWithdraw(entry: { ref: string; title: string }) {
  if (busy.value || withdrawing.value) return
  withdrawProblem.value = ''
  withdrawTarget.value = entry
}

function closeWithdraw() {
  if (!withdrawing.value) withdrawTarget.value = undefined
}

async function withdraw() {
  const target = withdrawTarget.value
  if (!target || withdrawing.value) return
  withdrawing.value = true
  withdrawProblem.value = ''
  try {
    const data = await call<{ withdrawn: boolean }>(`/documents/${encodeURIComponent(target.ref)}`, 'DELETE')
    if (data.withdrawn !== true) throw new Error('暂时无法确认撤回结果，请重试')
    withdrawnRefs.add(target.ref)
    documents.value = documents.value.filter((entry) => entry.ref !== target.ref)
    hits.value = hits.value.filter((hit) => hit.ref !== target.ref)
    withdrawTarget.value = undefined
    message.value = '资料已撤回，本校检索将不再返回它'
  } catch (cause) {
    withdrawProblem.value = cause instanceof Error ? cause.message : '资料暂时无法撤回，请重试'
  } finally {
    withdrawing.value = false
  }
}

async function search(query: string) {
  const version = ++searchVersion
  hits.value = []
  searched.value = false
  problem.value = ''
  searching.value = Boolean(query.trim())
  if (!searching.value) return
  try {
    const result = await call<{ items: Match[] }>('/search', 'POST', JSON.stringify({ query: query.trim() }), {
      'Content-Type': 'application/json',
    })
    if (version === searchVersion) {
      hits.value = result.items.filter((hit) => !withdrawnRefs.has(hit.ref))
      searched.value = true
    }
  } catch (cause) {
    if (version === searchVersion) problem.value = (cause as Error).message
  } finally {
    if (version === searchVersion) searching.value = false
  }
}

defineExpose({ search })
onMounted(loadDocuments)
</script>

<template>
  <AppDialog :open="showImport" title="导入资料" description="支持 PDF、DOCX、TXT 和 Markdown" @update:open="updateImportOpen">
    <form class="school-library__form" @submit.prevent="upload">
      <div class="school-library__drop" :data-dragging="dragging" @dragover.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="acceptDrop">
        <Upload :size="20" aria-hidden="true" />
        <label for="school-library-file">选择或拖放文件，每批最多 10 个，每个最大 50 MB</label>
        <input id="school-library-file" ref="fileInput" type="file" multiple accept=".pdf,.docx,.txt,.md" :disabled="busy" @change="chooseFiles(($event.target as HTMLInputElement).files)">
      </div>
      <label class="school-library__review">
        <input v-model="reviewed" type="checkbox" :disabled="busy">
        我确认资料已审核且有权入库，不含真实学生信息。
      </label>
      <AppButton type="submit" :disabled="!queue.some((row) => row.status === 'ready') || !reviewed || busy">批量导入</AppButton>
      <ul v-if="queue.length" class="school-library__documents" aria-label="导入进度" aria-live="polite">
        <li v-for="(row,index) in queue" :key="index"><strong>{{ row.file.name }}</strong><span :data-state="row.status">{{ row.note }}</span></li>
      </ul>
      <p v-if="message && showImport" role="status">{{ message }}</p>
      <p v-if="problem && showImport" class="school-library__problem" role="alert">{{ problem }}</p>
    </form>
  </AppDialog>
  <AppDialog :open="Boolean(withdrawTarget)" title="撤回本校资料" description="撤回后，本校检索将不再返回这份资料" @update:open="closeWithdraw">
    <p>{{ withdrawTarget?.title }}</p>
    <p v-if="withdrawProblem" class="school-library__problem" role="alert">{{ withdrawProblem }}</p>
    <div class="school-library__actions">
      <AppButton variant="secondary" :disabled="withdrawing" @click="closeWithdraw">取消</AppButton>
      <AppButton :loading="withdrawing" @click="withdraw">确认撤回</AppButton>
    </div>
  </AppDialog>
  <p v-if="message && !showImport" class="school-library__message" role="status">{{ message }}</p>
  <section v-if="props.showResults && (documents.length || searched || searching || problem || listProblem || props.showEmpty)" class="school-library" aria-label="本校资料">
    <p v-if="problem && !showImport" class="school-library__problem" role="alert">{{ problem }}</p>
    <h2 v-if="props.showResults">本校资料</h2>
    <div v-if="props.showResults && listProblem" class="school-library__list-error">
      <p class="school-library__problem" role="alert">{{ listProblem }}</p>
      <AppButton size="sm" variant="secondary" @click="loadDocuments">重新读取目录</AppButton>
    </div>
    <p v-else-if="props.showResults && loadingDocuments && props.showEmpty" role="status">正在读取本校资料…</p>
    <p v-if="props.showResults && searching" role="status">正在搜索本校资料…</p>
    <ul v-if="props.showResults && documents.length && !searched && !searching" class="school-library__documents" aria-label="已导入的本校资料">
      <li v-for="entry in documents" :key="entry.ref">
        <FileText :size="17" aria-hidden="true" />
        <span>{{ entry.title }}</span><small>{{ labels[entry.layer] }} · {{ entry.chunk_count }} 个片段</small>
        <AppButton size="sm" variant="quiet" :disabled="busy" :aria-label="`撤回资料：${entry.title}`" @click="openWithdraw(entry)">撤回</AppButton>
      </li>
    </ul>
    <p v-if="props.showResults && searched && !hits.length" role="status">本校已导入的资料里没有匹配的片段。</p>
    <p v-else-if="props.showResults && !searched && !searching && !loadingDocuments && !documents.length && !problem && !listProblem">尚未导入本校资料。</p>
    <ul v-else-if="props.showResults && hits.length" class="school-library__hits" aria-label="匹配的资料片段">
      <li v-for="hit in hits" :key="`${hit.ref}-${hit.ordinal}`">
        <strong>{{ hit.title }}，片段 {{ hit.ordinal }}</strong>
        <p>{{ hit.text }}</p>
        <AppButton size="sm" variant="quiet" :disabled="busy" :aria-label="`撤回资料：${hit.title}`" @click="openWithdraw(hit)">撤回</AppButton>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.school-library { display: grid; gap: 12px; padding: 16px; border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface); }
.school-library h2 { margin: 0; font-size: 17px; }
.school-library p { margin: 4px 0 0; color: var(--color-text-secondary); font-size: 13px; }
.school-library__message { margin: 0 14px 12px; color: var(--color-text-secondary); font-size: 13px; }
.school-library__form { display: grid; gap: 8px; justify-items: start; }
.school-library__drop { display: flex; width: 100%; flex-wrap: wrap; align-items: center; gap: 10px; padding: 12px; border: 1px dashed var(--color-border-strong); border-radius: var(--radius-control); font-size: 13px; }
.school-library__drop[data-dragging='true'] { border-color: var(--color-primary); background: var(--color-info-wash); }
.school-library__drop svg, .school-library__documents svg { flex: none; color: var(--color-primary); }
.school-library__drop input { max-width: 100%; }
.school-library__review { display: flex; align-items: center; gap: 6px; font-size: 13px; }
.school-library__list-error { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.school-library__actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; margin-top: 14px; }
.school-library__hits, .school-library__documents { display: grid; gap: 7px; margin: 0; padding: 0; list-style: none; }
.school-library__hits li, .school-library__documents li { padding: 10px; border: 1px solid var(--color-border); border-radius: var(--radius-control); overflow-wrap: anywhere; font-size: 13px; }
.school-library__hits p { white-space: pre-wrap; }
.school-library__documents li { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; }
.school-library__documents small { color: var(--color-text-secondary); }
.school-library__problem { color: var(--color-critical); }
</style>
