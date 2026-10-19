<script setup lang="ts">
/* global HTMLInputElement, KeyboardEvent */
import { ArrowDown, ArrowUp, CornerDownLeft, Search } from '@lucide/vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type { AdminWorkspaceAction } from './admin-workspace-actions'

const props = defineProps<{ actions: AdminWorkspaceAction[] }>()
const emit = defineEmits<{ activate: [] }>()

const router = useRouter()
const root = ref<HTMLElement | null>(null)
const searchInput = ref<HTMLInputElement | null>(null)
const query = ref('')
const open = ref(false)
const selectedIndex = ref(0)
const resultId = 'admin-command-results'

const matches = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase('zh-CN')
  if (!needle) return props.actions
  return props.actions.filter((action) => [action.label, action.description, action.group, ...action.keywords]
    .join(' ').toLocaleLowerCase('zh-CN').includes(needle))
})

watch(matches, () => { selectedIndex.value = 0 })

const focusSearch = async () => {
  open.value = true
  await nextTick()
  searchInput.value?.focus()
}

const closePalette = () => {
  open.value = false
  searchInput.value?.blur()
}

const moveSelection = (direction: -1 | 1) => {
  if (!matches.value.length) return
  selectedIndex.value = (selectedIndex.value + direction + matches.value.length) % matches.value.length
}

const activate = (action: AdminWorkspaceAction) => {
  closePalette()
  query.value = ''
  selectedIndex.value = 0
  emit('activate')
  void router.push(action.to)
}

const onInputKeydown = (event: KeyboardEvent) => {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    if (!open.value) open.value = true
    moveSelection(1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    if (!open.value) open.value = true
    moveSelection(-1)
  } else if (event.key === 'Enter') {
    const action = matches.value[selectedIndex.value]
    if (open.value && action) {
      event.preventDefault()
      activate(action)
    }
  } else if (event.key === 'Escape' && open.value) {
    event.preventDefault()
    event.stopPropagation()
    closePalette()
  }
}

const onGlobalKeydown = (event: KeyboardEvent) => {
  if (event.defaultPrevented || event.altKey || !(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'k') return
  const target = event.target instanceof HTMLElement ? event.target : null
  const isOwnInput = target === searchInput.value
  const isEditable = target?.isContentEditable || Boolean(target?.closest('input, textarea, select, [role="textbox"]'))
  if (isEditable && !isOwnInput) return
  event.preventDefault()
  void focusSearch()
}

const onDocumentPointerDown = (event: PointerEvent) => {
  if (!root.value?.contains(event.target as Node)) open.value = false
}

onMounted(() => {
  document.addEventListener('keydown', onGlobalKeydown)
  document.addEventListener('pointerdown', onDocumentPointerDown)
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onGlobalKeydown)
  document.removeEventListener('pointerdown', onDocumentPointerDown)
})

defineExpose({ focusSearch })
</script>

<template>
  <div ref="root" class="admin-command">
    <div class="admin-command__bar" :class="{ 'admin-command__bar--open': open }">
      <Search :size="20" stroke-width="1.8" aria-hidden="true" />
      <input
        ref="searchInput"
        v-model="query"
        type="search"
        role="combobox"
        aria-label="搜索管理操作"
        aria-autocomplete="list"
        :aria-expanded="open"
        :aria-controls="open ? resultId : undefined"
        :aria-activedescendant="open && matches[selectedIndex] ? `admin-command-${matches[selectedIndex].id}` : undefined"
        placeholder="搜索操作，例如：导入账号、发布测评…"
        autocomplete="off"
        @focus="open = true"
        @input="open = true"
        @keydown="onInputKeydown"
      >
      <span class="admin-command__hint"><kbd>Ctrl</kbd><span>K</span></span>
    </div>

    <Transition name="command-list">
      <div v-if="open" :id="resultId" class="admin-command__results" role="listbox" aria-label="可用管理操作">
        <template v-if="matches.length">
          <div class="admin-command__caption">{{ query.trim() ? '匹配的操作' : '常用操作' }}</div>
          <button
            v-for="(action, index) in matches"
            :id="`admin-command-${action.id}`"
            :key="action.id"
            class="admin-command__result"
            :class="{ 'admin-command__result--selected': index === selectedIndex }"
            type="button"
            role="option"
            :aria-selected="index === selectedIndex"
            @mouseenter="selectedIndex = index"
            @click="activate(action)"
          >
            <span class="admin-command__result-copy"><span class="admin-command__result-label">{{ action.label }}</span><span class="admin-command__result-description">{{ action.description }}</span></span>
            <span class="admin-command__result-meta"><span>{{ action.group }}</span><CornerDownLeft :size="16" aria-hidden="true" /></span>
          </button>
        </template>
        <div v-else class="admin-command__empty" role="status">没有找到可用操作</div>
        <div v-if="matches.length" class="admin-command__foot"><span><ArrowUp :size="13" aria-hidden="true" /><ArrowDown :size="13" aria-hidden="true" />选择</span><span><CornerDownLeft :size="13" aria-hidden="true" />打开</span><span>Esc 关闭</span></div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.admin-command { position: relative; z-index: 15; width: min(100%, 900px); margin: 0 auto 26px; }
.admin-command__bar { display: flex; align-items: center; gap: 14px; min-height: 68px; padding: 0 18px 0 20px; border: 1px solid #dbe6eb; border-radius: 18px; color: #748b98; background: var(--color-surface); box-shadow: 0 8px 28px rgb(31 67 83 / 5%); transition: border-color 180ms ease, box-shadow 180ms ease; }
.admin-command__bar--open, .admin-command__bar:focus-within { border-color: color-mix(in srgb, var(--color-primary) 50%, #dbe6eb); box-shadow: 0 12px 32px rgb(31 67 83 / 9%), 0 0 0 3px rgb(0 177 226 / 7%); }
.admin-command__bar > svg { flex: 0 0 auto; color: var(--color-primary-active); }
.admin-command__bar input { width: 100%; min-width: 0; height: 60px; padding: 0; border: 0; outline: 0; color: var(--color-text-primary); background: transparent; font: inherit; font-size: 16px; }
.admin-command__bar input::placeholder { color: #94a7b2; opacity: 1; }
.admin-command__bar input::-webkit-search-cancel-button { cursor: pointer; }
.admin-command__hint { display: inline-flex; align-items: center; gap: 2px; flex: 0 0 auto; padding: 8px 10px; border: 1px solid #dfe7ec; border-radius: 8px; color: #8fa2ad; background: #fbfcfd; font-size: 12px; line-height: 1; }
.admin-command__hint kbd { font: inherit; }
.admin-command__results { position: absolute; top: calc(100% + 8px); right: 0; left: 0; max-height: min(420px, 65vh); overflow-y: auto; padding: 8px; border: 1px solid #e2e9ed; border-radius: 15px; background: #fff; box-shadow: 0 22px 48px rgb(34 57 70 / 16%); }
.admin-command__caption { padding: 7px 10px 9px; color: var(--color-text-muted); font-size: 11px; font-weight: 650; }
.admin-command__result { display: flex; align-items: center; justify-content: space-between; gap: 14px; width: 100%; min-height: 58px; padding: 8px 10px; border: 0; border-radius: 9px; color: inherit; background: transparent; text-align: left; cursor: pointer; }
.admin-command__result:hover, .admin-command__result--selected { background: #f2f9fb; }
.admin-command__result:focus-visible { outline: 2px solid var(--color-primary-active); outline-offset: -2px; }
.admin-command__result-copy { display: grid; gap: 3px; min-width: 0; }
.admin-command__result-label { color: var(--color-text-primary); font-size: 13px; font-weight: 700; }
.admin-command__result-description { overflow: hidden; color: var(--color-text-muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.admin-command__result-meta { display: flex; align-items: center; gap: 12px; flex: 0 0 auto; color: #7a929f; font-size: 12px; line-height: 16px; }
.admin-command__result-meta svg { display: block; flex: 0 0 16px; color: var(--color-primary-active); }
.admin-command__empty { padding: 24px 12px; color: var(--color-text-muted); font-size: 13px; text-align: center; }
.admin-command__foot { display: flex; align-items: center; gap: 16px; margin-top: 5px; padding: 10px 10px 3px; border-top: 1px solid #edf0f2; color: #8997a0; font-size: 10px; }
.admin-command__foot span { display: inline-flex; align-items: center; gap: 3px; }
.command-list-enter-active, .command-list-leave-active { transition: opacity 140ms ease, transform 140ms ease; transform-origin: top center; }
.command-list-enter-from, .command-list-leave-to { opacity: 0; transform: translateY(-4px) scale(.99); }
@media (max-width: 640px) { .admin-command { margin-bottom: 18px; }.admin-command__bar { min-height: 58px; gap: 10px; padding: 0 12px 0 14px; border-radius: 14px; }.admin-command__bar input { height: 52px; font-size: 14px; }.admin-command__bar input::placeholder { font-size: 13px; }.admin-command__results { max-height: 60vh; }.admin-command__result-meta > span { display: none; }.admin-command__foot { gap: 12px; } }
@media (prefers-reduced-motion: reduce) { .command-list-enter-active, .command-list-leave-active, .admin-command__bar { transition-duration: 1ms; } }
</style>
