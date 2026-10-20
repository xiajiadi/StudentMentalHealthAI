<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  Search,
  X,
} from '@lucide/vue'
import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'
import {
  specialistAtlasEntries,
  specialistAtlasGroups,
  type SpecialistAtlasEntry,
} from './specialist-workspace-atlas'

const router = useRouter()
const selectedEntryId = ref(specialistAtlasEntries[0].id)
const paletteOpen = ref(false)
const query = ref('')
const activeIndex = ref(0)
const searchInput = ref<HTMLInputElement | null>(null)

const selectedEntry = computed(
  () => specialistAtlasEntries.find((entry) => entry.id === selectedEntryId.value) ?? specialistAtlasEntries[0],
)
const selectedIndex = computed(() => specialistAtlasEntries.findIndex((entry) => entry.id === selectedEntry.value.id) + 1)
const filteredEntries = computed(() => {
  const keyword = query.value.trim().toLocaleLowerCase()
  if (!keyword) return specialistAtlasEntries
  return specialistAtlasEntries.filter((entry) =>
    entry.groupLabel.toLocaleLowerCase() === keyword
      || [entry.title, entry.summary].some((value) => value.toLocaleLowerCase().includes(keyword)),
  )
})
const activeEntry = computed(() => filteredEntries.value[activeIndex.value])

watch(query, () => {
  activeIndex.value = 0
})

function selectEntry(entry: SpecialistAtlasEntry) {
  selectedEntryId.value = entry.id
}

function openPalette() {
  query.value = ''
  activeIndex.value = 0
  paletteOpen.value = true
}

defineExpose({ openPalette })

function isEditableTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || Boolean(target.closest('input, textarea, select, [role="combobox"], [contenteditable="true"]'))
}

function handleGlobalKeydown(event: KeyboardEvent) {
  if (paletteOpen.value || !(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'k' || event.defaultPrevented || isEditableTarget(event.target)) return
  event.preventDefault()
  openPalette()
}

function handlePaletteKeydown(event: KeyboardEvent) {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    if (filteredEntries.value.length) {
      activeIndex.value = (activeIndex.value + 1) % filteredEntries.value.length
      selectEntry(activeEntry.value)
    }
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    if (filteredEntries.value.length) {
      activeIndex.value = (activeIndex.value - 1 + filteredEntries.value.length) % filteredEntries.value.length
      selectEntry(activeEntry.value)
    }
  } else if (event.key === 'Enter' && activeEntry.value) {
    event.preventDefault()
    void navigateTo(activeEntry.value)
  }
}

function focusPaletteSearch(event: Event) {
  event.preventDefault()
  requestAnimationFrame(() => searchInput.value?.focus())
}

async function navigateTo(entry: SpecialistAtlasEntry) {
  paletteOpen.value = false
  await router.push(entry.to)
}

function optionId(entry: SpecialistAtlasEntry) {
  return 'specialist-quick-option-' + entry.id
}

onMounted(() => window.addEventListener('keydown', handleGlobalKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', handleGlobalKeydown))
</script>

<template>
  <section class="specialist-atlas" aria-labelledby="specialist-atlas-title">
    <header class="specialist-atlas__header">
      <div>
        <p class="specialist-atlas__eyebrow">WORKSPACE ATLAS</p>
        <h1 id="specialist-atlas-title">选择一条工作路径</h1>
        <p class="specialist-atlas__intro">从专业复核，到教育研究与工程实验。</p>
      </div>
      <button class="specialist-atlas__quick-trigger" type="button" @click="openPalette">
        <Search :size="16" aria-hidden="true" />
        <span>快速直达</span>
        <kbd>Ctrl K</kbd>
      </button>
    </header>

    <div class="specialist-atlas__workbench">
      <div class="specialist-atlas__map" aria-label="专业工作地图">
        <section
          v-for="(group, groupIndex) in specialistAtlasGroups"
          :key="group.id"
          class="specialist-atlas__path"
          :aria-labelledby="'specialist-atlas-path-' + group.id"
        >
          <header class="specialist-atlas__path-heading">
            <span class="specialist-atlas__path-code">{{ group.code }}</span>
            <h3 :id="'specialist-atlas-path-' + group.id">{{ group.title }}</h3>
          </header>
          <div class="specialist-atlas__nodes">
            <span
              class="specialist-atlas__connector specialist-atlas__connector--animated"
              :style="{ '--atlas-flow-delay': (groupIndex * -4) + 's' }"
              aria-hidden="true"
            />
            <RouterLink
              v-for="entry in specialistAtlasEntries.filter((item) => item.group === group.id)"
              :key="entry.id"
              :to="entry.to"
              class="specialist-atlas__node"
              :class="[
                'specialist-atlas__tone--' + entry.accent,
                { 'specialist-atlas__node--active': selectedEntryId === entry.id },
              ]"
              @mouseenter="selectEntry(entry)"
              @focus="selectEntry(entry)"
              @click="selectEntry(entry)"
            >
              <span class="specialist-atlas__node-icon">
                <component :is="entry.icon" :size="25" stroke-width="1.8" aria-hidden="true" />
              </span>
              <span class="specialist-atlas__node-title">{{ entry.title }}</span>
              <span class="specialist-atlas__node-summary">{{ entry.summary }}</span>
            </RouterLink>
          </div>
        </section>
      </div>

      <aside class="specialist-atlas__lens" aria-label="当前功能预览">
        <div class="specialist-atlas__lens-heading">
          <span>功能预览</span>
          <span class="specialist-atlas__lens-count">{{ String(selectedIndex).padStart(2, '0') }} / 08</span>
        </div>
        <Transition name="specialist-atlas-lens" mode="out-in">
          <div :key="selectedEntry.id" class="specialist-atlas__lens-content">
            <div class="specialist-atlas__orbit" :class="'specialist-atlas__tone--' + selectedEntry.accent" aria-hidden="true">
              <span class="specialist-atlas__orbit-ring specialist-atlas__orbit-ring--outer" />
              <span class="specialist-atlas__orbit-ring specialist-atlas__orbit-ring--inner" />
              <span class="specialist-atlas__lens-icon">
                <component :is="selectedEntry.icon" :size="32" stroke-width="1.7" />
              </span>
              <span class="specialist-atlas__orbit-point" />
            </div>
            <p class="specialist-atlas__lens-group">{{ selectedEntry.groupLabel }}</p>
            <h3>{{ selectedEntry.title }}</h3>
            <p class="specialist-atlas__lens-description">{{ selectedEntry.description }}</p>
            <RouterLink class="specialist-atlas__enter" :to="selectedEntry.to">
              进入此功能
            </RouterLink>
          </div>
        </Transition>
      </aside>
    </div>
  </section>

  <DialogRoot :open="paletteOpen" @update:open="paletteOpen = $event">
    <DialogPortal>
      <DialogOverlay class="specialist-quick__overlay" />
      <DialogContent
        class="specialist-quick__dialog"
        @open-auto-focus="focusPaletteSearch"
      >
        <div class="specialist-quick__search">
          <Search :size="19" aria-hidden="true" />
          <input
            id="specialist-quick-input"
            ref="searchInput"
            v-model="query"
            type="search"
            role="combobox"
            aria-label="搜索工作入口"
            aria-autocomplete="list"
            aria-controls="specialist-quick-list"
            :aria-expanded="paletteOpen"
            :aria-activedescendant="activeEntry ? optionId(activeEntry) : undefined"
            placeholder="搜索工作入口…"
            @keydown="handlePaletteKeydown"
          >
          <kbd>ESC</kbd>
          <button class="specialist-quick__close" type="button" aria-label="关闭快速直达" @click="paletteOpen = false">
            <X :size="18" aria-hidden="true" />
          </button>
        </div>
        <DialogTitle class="specialist-quick__title">快速直达</DialogTitle>
        <DialogDescription class="specialist-quick__description">
          搜索后选择一个功能入口，直接进入对应工作流。
        </DialogDescription>
        <div id="specialist-quick-list" class="specialist-quick__results" role="listbox" aria-label="工作入口">
          <button
            v-for="(entry, index) in filteredEntries"
            :id="optionId(entry)"
            :key="entry.id"
            class="specialist-quick__result"
            :class="{ 'specialist-quick__result--active': activeIndex === index }"
            type="button"
            role="option"
            tabindex="-1"
            :aria-selected="activeIndex === index"
            @mouseenter="activeIndex = index; selectEntry(entry)"
            @mousedown.prevent
            @click="navigateTo(entry)"
          >
            <span class="specialist-quick__icon" :class="'specialist-atlas__tone--' + entry.accent">
              <component :is="entry.icon" :size="18" aria-hidden="true" />
            </span>
            <span class="specialist-quick__result-copy">
              <strong>{{ entry.title }}</strong>
              <small>{{ entry.groupLabel }} · {{ entry.summary }}</small>
            </span>
          </button>
          <p v-if="!filteredEntries.length" class="specialist-quick__empty">没有匹配的工作入口</p>
        </div>
        <footer class="specialist-quick__footer">
          <span><kbd>↑</kbd><kbd>↓</kbd> 选择</span>
          <span><kbd>↵</kbd> 打开</span>
          <span><kbd>Tab</kbd> 切换焦点</span>
        </footer>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>

</template>

<style scoped>
.specialist-atlas { overflow: hidden; border: 1px solid #e4eaf0; border-radius: 16px; background: var(--color-surface); box-shadow: var(--shadow-rest); }
.specialist-atlas__header { position: relative; display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 17px 24px 12px; }
.specialist-atlas__eyebrow { margin: 0 0 7px; color: var(--color-primary-active); font-size: 10px; font-weight: 760; letter-spacing: .14em; }
.specialist-atlas__header h1 { margin: 0; color: var(--color-text-primary); font-size: 20px; font-weight: 720; line-height: 1.35; }
.specialist-atlas__intro { margin: 5px 0 0; color: var(--color-text-muted); font-size: 13px; line-height: 1.6; }
.specialist-atlas__workbench { display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(285px, .8fr); border-top: 1px solid #edf0f3; }
.specialist-atlas__map { display: grid; align-content: center; gap: 3px; min-width: 0; padding: 9px 22px 10px; background: radial-gradient(ellipse at 46% 14%, rgb(0 177 226 / 4%), transparent 60%), radial-gradient(#dce9ee 0.75px, transparent .75px); background-size: auto, 18px 18px; }
.specialist-atlas__path { display: grid; grid-template-columns: 126px minmax(0, 1fr); align-items: center; gap: 8px; min-width: 0; padding: 8px 0; }
.specialist-atlas__path + .specialist-atlas__path { border-top: 1px solid rgb(211 222 228 / 68%); }
.specialist-atlas__path-heading { min-width: 0; padding-left: 2px; }
.specialist-atlas__path-code { color: #93a4ae; font-size: 11px; font-weight: 760; letter-spacing: .1em; }
.specialist-atlas__path-heading h3 { margin: 5px 0 0; color: #334654; font-size: 15px; font-weight: 680; line-height: 1.4; }
.specialist-atlas__nodes { position: relative; display: flex; min-width: 0; align-items: flex-start; justify-content: space-around; gap: 2px; }
.specialist-atlas__connector { position: absolute; z-index: 0; top: 26px; right: 11%; left: 11%; height: 1px; background: linear-gradient(90deg, #d7e5e8, #dedfeb 48%, #dce9e4); pointer-events: none; }
.specialist-atlas__connector::after { position: absolute; top: -1px; left: -10%; width: 24%; height: 3px; border-radius: 99px; background: linear-gradient(90deg, transparent, rgb(0 177 226 / 38%), transparent); content: ''; opacity: 0; }
.specialist-atlas__connector--animated::after { opacity: .8; animation: atlas-flow 12s ease-in-out infinite; animation-delay: var(--atlas-flow-delay, 0s); }
.specialist-atlas__node { position: relative; z-index: 1; display: flex; width: 33.333%; min-width: 74px; flex-direction: column; align-items: center; gap: 5px; padding: 3px 5px 5px; border-radius: 12px; color: inherit; text-align: center; text-decoration: none; transition: background-color 180ms ease, transform 180ms ease; }
.specialist-atlas__node:hover,.specialist-atlas__node--active { background: color-mix(in srgb, var(--atlas-wash) 42%, transparent); }
.specialist-atlas__node:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; background: color-mix(in srgb, var(--atlas-wash) 42%, transparent); }
.specialist-atlas__node-icon { position: relative; display: grid; width: 52px; height: 52px; flex: 0 0 52px; place-items: center; border: 1px solid color-mix(in srgb, var(--atlas-accent) 18%, #fff); border-radius: 50%; color: var(--atlas-accent); background: radial-gradient(circle at 32% 26%, #fff 0, color-mix(in srgb, var(--atlas-wash) 78%, #fff) 68%, var(--atlas-wash) 100%); box-shadow: inset 0 1px 3px rgb(255 255 255 / 92%), 0 4px 13px color-mix(in srgb, var(--atlas-accent) 7%, transparent); transition: transform 190ms ease, box-shadow 190ms ease, color 190ms ease; }
.specialist-atlas__node-icon::after { position: absolute; inset: -5px; border: 1px solid color-mix(in srgb, var(--atlas-accent) 34%, transparent); border-radius: 50%; content: ''; opacity: 0; transform: scale(.9); transition: opacity 190ms ease, transform 190ms ease; }
.specialist-atlas__node:hover .specialist-atlas__node-icon,.specialist-atlas__node--active .specialist-atlas__node-icon,.specialist-atlas__node:focus-visible .specialist-atlas__node-icon { box-shadow: inset 0 1px 3px #fff, 0 4px 14px color-mix(in srgb, var(--atlas-accent) 15%, transparent); transform: scale(1.045); }
.specialist-atlas__node:hover .specialist-atlas__node-icon::after,.specialist-atlas__node--active .specialist-atlas__node-icon::after,.specialist-atlas__node:focus-visible .specialist-atlas__node-icon::after { opacity: 1; transform: scale(1); }
.specialist-atlas__node-title { color: #314451; font-size: 14px; font-weight: 700; line-height: 1.35; white-space: nowrap; }
.specialist-atlas__node-summary { color: #8a9aa4; font-size: 12px; line-height: 1.35; white-space: nowrap; }
.specialist-atlas__tone--cyan { --atlas-accent: #009dbf; --atlas-wash: #e8f6fa; }
.specialist-atlas__tone--violet { --atlas-accent: #7777b8; --atlas-wash: #f1effa; }
.specialist-atlas__tone--lavender { --atlas-accent: #817bd1; --atlas-wash: #f2effd; }
.specialist-atlas__tone--sky { --atlas-accent: #4d9fc0; --atlas-wash: #edf6fb; }
.specialist-atlas__tone--amber { --atlas-accent: #b7791f; --atlas-wash: #fbf4e7; }
.specialist-atlas__tone--mint { --atlas-accent: #258a78; --atlas-wash: #eaf7f2; }
.specialist-atlas__tone--teal { --atlas-accent: #328b81; --atlas-wash: #e9f6f4; }
.specialist-atlas__lens { position: relative; display: flex; min-width: 0; min-height: 320px; flex-direction: column; align-items: center; justify-content: flex-start; padding: 16px 24px 16px; border-left: 1px solid #edf0f3; background: linear-gradient(145deg, #fbfcfd, #f8fbfc 66%, #fafafd); text-align: center; }
.specialist-atlas__lens-heading { display: flex; width: 100%; align-items: center; justify-content: space-between; color: #6f828f; font-size: 13px; font-weight: 650; }
.specialist-atlas__lens-count { color: #93a3ad; font-size: 12px; font-weight: 700; font-variant-numeric: tabular-nums; letter-spacing: .08em; }
.specialist-atlas__lens-content { display: grid; width: 100%; min-height: 0; flex: 1; grid-template-columns: minmax(0, 1fr); align-content: center; justify-items: center; gap: 8px; padding-top: 8px; text-align: center; }
.specialist-atlas__orbit { position: relative; display: grid; width: 126px; height: 126px; flex: 0 0 126px; place-items: center; color: var(--atlas-accent); }
.specialist-atlas__orbit-ring { position: absolute; border: 1px solid color-mix(in srgb, var(--atlas-accent) 16%, #fff); border-radius: 50%; }
.specialist-atlas__orbit-ring--outer { inset: 1px; border-style: dashed; animation: atlas-orbit 34s linear infinite; }
.specialist-atlas__orbit-ring--inner { inset: 13px; border-color: color-mix(in srgb, var(--atlas-accent) 10%, #fff); }
.specialist-atlas__lens-icon { position: relative; z-index: 1; display: grid; width: 72px; height: 72px; place-items: center; border: 1px solid color-mix(in srgb, var(--atlas-accent) 19%, #fff); border-radius: 50%; background: radial-gradient(circle at 32% 24%, #fff 0, color-mix(in srgb, var(--atlas-wash) 84%, #fff) 68%, var(--atlas-wash) 100%); box-shadow: inset 0 1px 4px #fff, 0 8px 23px color-mix(in srgb, var(--atlas-accent) 11%, transparent); animation: atlas-float 5.4s ease-in-out infinite; }
.specialist-atlas__orbit-point { position: absolute; top: 12px; right: 21px; width: 6px; height: 6px; border-radius: 50%; background: color-mix(in srgb, var(--atlas-accent) 48%, #fff); box-shadow: 0 0 0 4px color-mix(in srgb, var(--atlas-accent) 9%, transparent); }
.specialist-atlas__lens-group { margin: 0; color: var(--atlas-accent); font-size: 12px; font-weight: 700; letter-spacing: .04em; }
.specialist-atlas__lens-content h3 { margin: 0; color: var(--color-text-primary); font-size: 19px; font-weight: 720; line-height: 1.35; }
.specialist-atlas__lens-description { max-width: 320px; min-height: 0; margin: 0; color: var(--color-text-muted); font-size: 13px; line-height: 1.55; }
.specialist-atlas__enter { display: inline-flex; min-height: 36px; align-items: center; justify-content: center; gap: 8px; margin: 0; padding: 0 15px; border: 1px solid color-mix(in srgb, var(--color-primary) 30%, #fff); border-radius: 9px; color: var(--color-primary-active); background: #fff; box-shadow: 0 3px 10px rgb(12 116 142 / 6%); font-size: 13px; font-weight: 700; text-decoration: none; transition: border-color 180ms ease, background-color 180ms ease, transform 180ms ease; }
.specialist-atlas__enter:hover { border-color: var(--color-primary); background: #f2fbfd; transform: translateY(-1px); }
.specialist-atlas__enter:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 3px; }
.specialist-atlas-lens-enter-active,.specialist-atlas-lens-leave-active { transition: opacity 160ms ease, transform 160ms ease; }
.specialist-atlas-lens-enter-from { opacity: 0; transform: translateY(5px) scale(.985); }
.specialist-atlas-lens-leave-to { opacity: 0; transform: translateY(-3px) scale(.99); }
.specialist-atlas__quick-trigger { display: inline-flex; min-height: 38px; flex: 0 0 auto; align-items: center; gap: 8px; margin-left: auto; padding: 0 10px; border: 1px solid #dfe7ed; border-radius: 9px; color: #4d6371; background: #fff; cursor: pointer; font: inherit; font-size: 12px; font-weight: 640; box-shadow: 0 2px 8px rgb(30 60 75 / 3%); transition: border-color 180ms ease, color 180ms ease, background-color 180ms ease; }
.specialist-atlas__quick-trigger:hover { border-color: #a7dce8; color: var(--color-primary-active); background: #f7fcfd; }
.specialist-atlas__quick-trigger:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 3px; }
.specialist-atlas__quick-trigger svg { color: var(--color-primary-active); }
.specialist-atlas__quick-trigger kbd { padding: 2px 5px; border: 1px solid #e1e8ed; border-radius: 5px; color: #7e8e99; background: #f8fafb; font-family: inherit; font-size: 9px; font-weight: 600; }
.specialist-quick__search kbd,.specialist-quick__footer kbd { padding: 2px 5px; border: 1px solid #e1e8ed; border-radius: 5px; color: #7e8e99; background: #f8fafb; font-family: inherit; font-size: 9px; font-weight: 600; }
.specialist-quick__overlay { position: fixed; inset: 0; z-index: 80; background: rgb(23 32 51 / 42%); backdrop-filter: blur(2px); }
.specialist-quick__dialog { position: fixed; top: 50%; left: 50%; z-index: 90; display: flex; width: min(100% - 32px, 560px); max-height: min(620px, calc(100vh - 32px)); flex-direction: column; overflow: hidden; padding: 16px; border: 1px solid #dfe7ec; border-radius: 15px; outline: 0; background: #fff; box-shadow: 0 26px 70px rgb(22 44 58 / 19%); transform: translate(-50%, -50%); }
.specialist-quick__search { display: flex; min-height: 48px; align-items: center; gap: 11px; padding: 0 11px; border: 1px solid #dbe5eb; border-radius: 10px; color: #8497a2; background: #fbfcfd; }
.specialist-quick__search:focus-within { border-color: color-mix(in srgb, var(--color-primary) 52%, #dbe5eb); box-shadow: 0 0 0 3px rgb(0 177 226 / 8%); }
.specialist-quick__search > svg { flex: 0 0 auto; color: var(--color-primary-active); }
.specialist-quick__search input { width: 100%; min-width: 0; height: 44px; padding: 0; border: 0; outline: 0; color: var(--color-text-primary); background: transparent; font: inherit; font-size: 14px; }
.specialist-quick__search input::placeholder { color: #95a4ae; }
.specialist-quick__search input::-webkit-search-cancel-button { cursor: pointer; }
.specialist-quick__close { display: grid; width: 31px; height: 31px; flex: 0 0 31px; place-items: center; border: 0; border-radius: 7px; color: #71838e; background: transparent; cursor: pointer; }
.specialist-quick__close:hover { color: var(--color-primary-active); background: #edf8fb; }
.specialist-quick__close:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.specialist-quick__title { margin: 16px 5px 0; color: #425866; font-size: 13px; font-weight: 700; }
.specialist-quick__description { margin: 4px 5px 9px; color: #8a9aa3; font-size: 11px; line-height: 1.55; }
.specialist-quick__results { display: grid; min-height: 0; gap: 3px; overflow-y: auto; padding: 3px; }
.specialist-quick__result { display: flex; width: 100%; min-height: 51px; align-items: center; gap: 11px; padding: 7px 9px; border: 1px solid transparent; border-radius: 9px; color: inherit; background: transparent; cursor: pointer; text-align: left; }
.specialist-quick__result:hover,.specialist-quick__result--active { border-color: #e3edf1; background: #f7fafc; }
.specialist-quick__result:focus-visible { outline: 2px solid var(--color-primary); outline-offset: -2px; }
.specialist-quick__icon { display: grid; width: 34px; height: 34px; flex: 0 0 34px; place-items: center; border: 1px solid color-mix(in srgb, var(--atlas-accent) 13%, #fff); border-radius: 10px; color: var(--atlas-accent); background: var(--atlas-wash); }
.specialist-quick__result-copy { display: grid; min-width: 0; gap: 3px; }
.specialist-quick__result-copy strong { color: #3a4f5b; font-size: 12px; font-weight: 690; }
.specialist-quick__result-copy small { color: #8c9ba4; font-size: 10px; }
.specialist-quick__empty { margin: 0; padding: 24px 12px; color: #8a9aa3; font-size: 12px; text-align: center; }
.specialist-quick__footer { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 10px; padding: 11px 4px 0; border-top: 1px solid #edf1f4; color: #8a9aa3; font-size: 10px; }
.specialist-quick__footer span { display: inline-flex; align-items: center; gap: 4px; }
@keyframes atlas-flow { 0% { left: -10%; transform: translateX(0); } 55% { opacity: .6; } 100% { left: 91%; transform: translateX(0); } }
@keyframes atlas-orbit { to { transform: rotate(360deg); } }
@keyframes atlas-float { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-3px); } }
@media (max-width: 1100px) {
  .specialist-atlas__workbench { grid-template-columns: minmax(0, 1fr); }
  .specialist-atlas__lens { min-height: 0; flex-direction: row; align-items: center; justify-content: center; gap: 18px; padding: 18px 24px; border-top: 1px solid #edf0f3; border-left: 0; }
  .specialist-atlas__lens-heading { position: absolute; top: 13px; right: 20px; width: auto; gap: 12px; }
  .specialist-atlas__lens-content { width: 100%; grid-template-columns: 104px minmax(0, 1fr) auto; align-content: center; justify-items: stretch; align-items: center; gap: 4px 16px; padding: 12px 0 0; text-align: left; }
  .specialist-atlas__orbit { width: 96px; height: 96px; grid-row: span 3; }
  .specialist-atlas__orbit-ring--outer { inset: 4px; }
  .specialist-atlas__orbit-ring--inner { inset: 13px; }
  .specialist-atlas__lens-icon { width: 56px; height: 56px; }
  .specialist-atlas__orbit-point { top: 14px; right: 17px; }
  .specialist-atlas__lens-group { grid-column: 2; margin: 0; align-self: end; }
  .specialist-atlas__lens-content h3 { grid-column: 2; align-self: start; margin: 0; }
  .specialist-atlas__lens-description { grid-column: 2; grid-row: 3; min-height: 0; }
  .specialist-atlas__enter { grid-column: 3; grid-row: 2 / span 2; margin: 0; }
}
@media (max-width: 700px) {
  .specialist-atlas__header { padding: 19px 18px 15px; }
  .specialist-atlas__header h1 { padding-right: 108px; font-size: 18px; }
  .specialist-atlas__intro { max-width: calc(100% - 96px); font-size: 12px; }
  .specialist-atlas__quick-trigger { position: absolute; top: 18px; right: 16px; min-height: 34px; gap: 6px; padding: 0 8px; font-size: 11px; }
  .specialist-atlas__quick-trigger kbd { display: none; }
  .specialist-atlas__map { gap: 0; padding: 8px 16px 11px; }
  .specialist-atlas__path { grid-template-columns: 1fr; gap: 6px; padding: 13px 0 11px; }
  .specialist-atlas__path-heading { display: flex; align-items: baseline; gap: 8px; }
  .specialist-atlas__path-heading h3 { margin: 0; font-size: 14px; }
  .specialist-atlas__nodes { justify-content: flex-start; gap: 5px; }
  .specialist-atlas__connector { top: 26px; right: 12%; left: 12%; }
  .specialist-atlas__node { width: 33.333%; min-width: 0; padding: 3px 2px 4px; gap: 4px; }
  .specialist-atlas__node-icon { width: 52px; height: 52px; flex-basis: 52px; }
  .specialist-atlas__node-icon svg { width: 22px; height: 22px; }
  .specialist-atlas__node-title { font-size: 13px; }
  .specialist-atlas__node-summary { font-size: 11px; }
  .specialist-atlas__lens { display: block; padding: 16px 18px 18px; }
  .specialist-atlas__lens-heading { top: 13px; right: 17px; }
  .specialist-atlas__lens-content { grid-template-columns: 78px minmax(0, 1fr); gap: 3px 12px; padding-top: 14px; }
  .specialist-atlas__orbit { width: 78px; height: 78px; grid-row: 1 / span 4; }
  .specialist-atlas__orbit-ring--outer { inset: 2px; }
  .specialist-atlas__orbit-ring--inner { inset: 10px; }
  .specialist-atlas__lens-icon { width: 47px; height: 47px; }
  .specialist-atlas__lens-icon svg { width: 25px; height: 25px; }
  .specialist-atlas__orbit-point { top: 9px; right: 14px; width: 5px; height: 5px; }
  .specialist-atlas__lens-group,.specialist-atlas__lens-content h3,.specialist-atlas__lens-description { grid-column: 2; }
  .specialist-atlas__lens-group { grid-row: 1; align-self: end; }
  .specialist-atlas__lens-content h3 { grid-row: 2; }
  .specialist-atlas__lens-description { grid-row: 3; }
  .specialist-atlas__enter { grid-column: 2; grid-row: 4; justify-self: start; min-height: 34px; }
  .specialist-quick__dialog { padding: 12px; }
  .specialist-quick__footer { gap: 9px; }
}
@media (prefers-reduced-motion: reduce) {
  .specialist-atlas__connector--animated::after { animation: none; opacity: 0; }
  .specialist-atlas__orbit-ring--outer,.specialist-atlas__lens-icon { animation: none; }
  .specialist-atlas__node,.specialist-atlas__node-icon,.specialist-atlas__node-icon::after,.specialist-atlas__enter,.specialist-atlas-lens-enter-active,.specialist-atlas-lens-leave-active { transition-duration: .01ms; }
}
</style>
