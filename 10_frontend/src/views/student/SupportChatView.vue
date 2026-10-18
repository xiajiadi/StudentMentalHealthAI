<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { MessageCircle, Plus, RotateCcw, Send } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppLoadingDots from '@/components/app/AppLoadingDots.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import StudentIndependentEducationReviews from '@/components/school/StudentIndependentEducationReviews.vue'
import StudentPageHero from '@/components/student/StudentPageHero.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import { studentPageArt, studentPageBannerCopy, studentPageTitles } from '@/data/student-feature-cards'
import {
  independentConversations,
  researchConversations,
  researchConversationCapability,
  newConversationIdempotencyKey,
  type IndependentConversation,
  type IndependentConversationDetail,
  type IndependentConversationMessage,
  type IndependentConversationTurn,
  type IndependentTurnReceipt,
} from '@/services/independent-conversations'

const props = withDefaults(defineProps<{ researchMode?: boolean }>(), { researchMode: false })
const conversationApi = props.researchMode ? researchConversations : independentConversations
const researchAvailable = ref(false)
const conversations = ref<IndependentConversation[]>([])
const selectedConversationId = ref('')
const detail = ref<IndependentConversationDetail | null>(null)
const loadingList = ref(true)
const loadingDetail = ref(false)
const creating = ref(false)
const sending = ref(false)
const educationReviewRefreshToken = ref(0)
const loadingMore = ref(false)
const listError = ref('')
const detailError = ref('')
const sendError = ref('')
const createError = ref('')
const draft = ref('')
const receipt = ref<IndependentTurnReceipt | null>(null)
const conversationHasMore = ref(false)
const supportMessageInput = ref<HTMLTextAreaElement | null>(null)
const suggestedPrompts = [
  '帮我安排本周复习计划',
  '学习压力大时，我可以怎么调整？',
  '怎样把学习目标拆成小步骤？',
]

let conversationOffset = 0
let pendingCreateKey = ''
let failedSubmission: { conversationId: string; text: string; key: string } | null = null
let detailRequestSequence = 0
let messagePageRequestSequence = 0

const selectedConversation = computed(() =>
  conversations.value.find((item) => item.conversationId === selectedConversationId.value)
    ?? (detail.value?.conversation.conversationId === selectedConversationId.value ? detail.value.conversation : null),
)
const receiptNeedsDisplay = computed(() => Boolean(
  receipt.value
  && !detail.value?.messages.some((message) => message.turnId === receipt.value?.turnId
    && (receipt.value?.content ? message.role === 'assistant' : true)),
))
const loadedTurnCount = computed(() => new Set(detail.value?.messages.map((message) => message.turnId) ?? []).size)
const hasEarlierMessages = computed(() => Boolean(detail.value && detail.value.offset > 0))
const hasLaterMessages = computed(() => Boolean(detail.value && detail.value.offset + loadedTurnCount.value < detail.value.totalTurns))
const hasRequestedTurn = computed(() => Boolean(
  receipt.value?.status === 'requested'
  || detail.value?.messages.some((message) => message.turn.status === 'requested'),
))

const canSend = computed(() =>
  Boolean(selectedConversationId.value)
  && Boolean(detail.value)
  && !detailError.value
  && !loadingDetail.value
  && !sending.value
  && !hasRequestedTurn.value
  && selectedConversation.value?.status !== 'closed'
  && selectedConversation.value?.status !== 'archived'
  && (!failedSubmission || failedSubmission.conversationId === selectedConversationId.value),
)

const statusText = (status: string): string => ({
  open: '可继续',
  active: '进行中',
  closed: '已结束',
  archived: '已归档',
  requested: '处理中',
  completed: '已完成',
  blocked: '已暂停',
  failed: '未完成',
}[status] ?? '状态待确认')

const turnStatusText = (turn: Pick<IndependentConversationTurn, 'action' | 'status'>): string => {
  if (turn.action === 'ABSTAIN') return '资料不足，暂不提供建议'
  if (turn.status === 'requested') return '处理中'
  if (turn.status === 'blocked' && turn.action === 'CRISIS_ROUTE') return '安全提示'
  if (turn.status === 'blocked' && turn.action === 'CONTENT_REVIEW_HELD') return '草稿待核对'
  if (turn.status === 'blocked') return '这条消息已暂停'
  if (turn.status === 'failed') return '本次回复未完成'
  return '教育支持信息'
}

const formatDate = (value: string): string => {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间未提供'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

const updateConversation = (value: IndependentConversation) => {
  const index = conversations.value.findIndex((item) => item.conversationId === value.conversationId)
  if (index < 0) conversations.value = [value, ...conversations.value]
  else conversations.value[index] = value
}

const loadConversations = async (append = false) => {
  loadingList.value = true
  listError.value = ''
  try {
    const offset = append ? conversationOffset : 0
    const page = await conversationApi.list(offset, 20)
    if (append) {
      const existingIds = new Set(conversations.value.map((item) => item.conversationId))
      conversations.value = [...conversations.value, ...page.items.filter((item) => !existingIds.has(item.conversationId))]
    } else {
      conversations.value = page.items
    }
    conversationOffset = offset + page.items.length
    conversationHasMore.value = page.hasMore
  } catch (error) {
    listError.value = error instanceof Error ? error.message : '会话列表暂时无法加载。'
  } finally {
    loadingList.value = false
  }
}

const openConversation = async (conversationId: string, offset = 0) => {
  const requestSequence = ++detailRequestSequence
  messagePageRequestSequence += 1
  const sameConversation = selectedConversationId.value === conversationId
  selectedConversationId.value = conversationId
  detail.value = null
  detailError.value = ''
  sendError.value = ''
  loadingMore.value = false
  if (!sameConversation) receipt.value = null
  loadingDetail.value = true
  try {
    const result = await conversationApi.detail(conversationId, offset)
    if (requestSequence === detailRequestSequence && selectedConversationId.value === conversationId) {
      detail.value = result
      const receiptTurn = receipt.value && result.messages.find((message) => message.turnId === receipt.value?.turnId)
      if (receipt.value?.status === 'requested' && receiptTurn && receiptTurn.turn.status !== 'requested') {
        receipt.value = null
        if (props.researchMode) educationReviewRefreshToken.value += 1
      }
    }
  } catch (error) {
    if (requestSequence === detailRequestSequence && selectedConversationId.value === conversationId) {
      detailError.value = error instanceof Error ? error.message : '这段会话暂时无法打开。'
    }
  } finally {
    if (requestSequence === detailRequestSequence && selectedConversationId.value === conversationId) loadingDetail.value = false
  }
}

const loadMoreConversations = () => loadConversations(true)

const loadMoreMessages = async (direction: 'earlier' | 'later') => {
  if (!detail.value || loadingMore.value) return
  const currentDetail = detail.value
  const conversationId = currentDetail.conversation.conversationId
  const offset = direction === 'earlier'
    ? Math.max(0, currentDetail.offset - currentDetail.limit)
    : currentDetail.offset + loadedTurnCount.value
  if (direction === 'earlier' ? !hasEarlierMessages.value : !hasLaterMessages.value) return
  const requestSequence = ++messagePageRequestSequence
  loadingMore.value = true
  detailError.value = ''
  try {
    const page = await conversationApi.detail(conversationId, offset, currentDetail.limit)
    if (requestSequence !== messagePageRequestSequence || selectedConversationId.value !== conversationId || detail.value !== currentDetail) return
    const messagesById = new Map([...currentDetail.messages, ...page.messages].map((message) => [message.messageId, message]))
    detail.value = { ...page, offset: Math.min(currentDetail.offset, page.offset), messages: [...messagesById.values()].sort((a, b) => a.sequence - b.sequence) }
  } catch (error) {
    if (requestSequence === messagePageRequestSequence && selectedConversationId.value === conversationId) {
      detailError.value = error instanceof Error ? error.message : '更多对话暂时无法加载。'
    }
  } finally {
    if (requestSequence === messagePageRequestSequence && selectedConversationId.value === conversationId) loadingMore.value = false
  }
}

const createConversation = async () => {
  if (creating.value || sending.value) return
  creating.value = true
  createError.value = ''
  try {
    if (!pendingCreateKey) pendingCreateKey = newConversationIdempotencyKey()
    const created = await conversationApi.create(pendingCreateKey)
    pendingCreateKey = ''
    selectedConversationId.value = created.conversationId
    receipt.value = null
    updateConversation(created)
    await openConversation(created.conversationId)
    await loadConversations()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '暂时无法创建会话。请使用同一请求重试。'
  } finally {
    creating.value = false
  }
}

const initializeConversation = async () => {
  if (creating.value || sending.value) return
  await loadConversations()
  if (props.researchMode || listError.value || selectedConversationId.value) return

  const resumable = conversations.value.find((conversation) => conversation.status === 'open' || conversation.status === 'active')
  if (resumable) {
    await openConversation(resumable.conversationId)
    return
  }

  await createConversation()
}

const handleSend = async () => {
  if (!canSend.value) return
  const conversationId = selectedConversationId.value
  const text = failedSubmission?.conversationId === conversationId ? failedSubmission.text : draft.value.trim()
  if (!text) return
  const pageLimit = detail.value?.limit ?? 20
  const latestOffset = Math.floor((detail.value?.totalTurns ?? 0) / pageLimit) * pageLimit
  sending.value = true
  sendError.value = ''
  try {
    const submission = failedSubmission?.conversationId === conversationId
      ? failedSubmission
      : { conversationId, text, key: newConversationIdempotencyKey() }
    failedSubmission = submission
    receipt.value = await conversationApi.send(
      conversationId,
      submission.text,
      submission.key,
    )
    if (props.researchMode && selectedConversationId.value === conversationId && receipt.value.status !== 'requested') {
      educationReviewRefreshToken.value += 1
    }
    failedSubmission = null
    draft.value = ''
    await openConversation(conversationId, latestOffset)
    await loadConversations()
  } catch (error) {
    sendError.value = error instanceof Error ? error.message : '消息未确认，请使用同一请求重试。'
  } finally {
    sending.value = false
  }
}

const refreshConversation = async () => {
  if (selectedConversationId.value) {
    const limit = detail.value?.limit ?? 20
    const latestOffset = Math.floor(Math.max((detail.value?.totalTurns ?? 1) - 1, 0) / limit) * limit
    await openConversation(selectedConversationId.value, latestOffset)
  }
}

const messageStateLabel = (message: IndependentConversationMessage): string => turnStatusText(message.turn)

const useSuggestedPrompt = async (prompt: string) => {
  if (!canSend.value || (failedSubmission && failedSubmission.conversationId === selectedConversationId.value)) return
  draft.value = prompt
  await nextTick()
  supportMessageInput.value?.focus()
}

onMounted(() => {
  void initializeConversation()
  if (!props.researchMode) {
    void researchConversationCapability().then((enabled) => { researchAvailable.value = enabled }).catch(() => {
      researchAvailable.value = false
    })
  }
})
</script>

<template>
  <div class="content-wrap content-wrap--student education-support">
    <template v-if="props.researchMode">
      <header class="support-heading">
        <div>
          <span class="support-kicker">学生空间 · 教育支持</span>
          <h1>高中场景教育支持</h1>
          <p>围绕学习和日常生活中的问题，查看已保存的私密对话。</p>
        </div>
        <div>
          <AppBadge tone="support" dot>研究演示</AppBadge>
          <RouterLink class="support-back" to="/student/support">返回教育支持</RouterLink>
        </div>
      </header>
    </template>
    <template v-else>
      <WorkspaceBreadcrumb current="教育支持" />
      <StudentPageHero
        :eyebrow="studentPageBannerCopy.educationSupport.eyebrow"
        :title="studentPageTitles.educationSupport"
        :subtitle="studentPageBannerCopy.educationSupport.subtitle"
        :image="studentPageArt.educationSupport"
        image-position="center 48%"
        light-text
      >
        <template #actions>
          <div class="support-hero-actions">
            <RouterLink v-if="researchAvailable" class="support-back" to="/student/research-support">进入高中场景研究演示</RouterLink>
          </div>
        </template>
      </StudentPageHero>
    </template>

    <AppStatusCallout
      v-if="props.researchMode"
      class="support-boundary"
      tone="info"
      title="14–17 岁虚构校园场景研究演示"
      body="每条问题独立处理，不使用其他对话历史或测评答案。生成草稿需经单独分享与核对后才能发布；资料仅用于研究演示，不用于诊断或治疗。"
    />

    <AppStatusCallout
      v-if="failedSubmission && failedSubmission.conversationId !== selectedConversationId"
      class="support-boundary"
      tone="attention"
      title="上一条消息状态未确认"
      body="请在会话列表中打开对应对话，并使用同一请求重试后再继续发送。"
    />

    <div class="conversation-workspace">
      <AppCard class="conversation-sidebar" aria-label="教育支持会话列表">
        <div class="conversation-sidebar__heading">
          <div><h2>我的会话</h2><span>仅当前账号可查看</span></div>
          <AppButton size="sm" :loading="creating" :disabled="creating || sending || loadingList" aria-label="新建会话" @click="createConversation">
            <Plus :size="15" aria-hidden="true" />新建
          </AppButton>
        </div>
        <AppStatusCallout v-if="createError && selectedConversationId" tone="attention" title="创建未确认" :body="createError">
          <AppButton size="sm" variant="secondary" :loading="creating" @click="createConversation">使用同一请求重试</AppButton>
        </AppStatusCallout>
        <AppStatusCallout v-if="listError && selectedConversationId" tone="attention" title="会话列表暂不可用" :body="listError">
          <AppButton size="sm" variant="secondary" :loading="loadingList" @click="loadConversations()">重试</AppButton>
        </AppStatusCallout>
        <p v-if="loadingList && conversations.length === 0" class="conversation-muted" role="status">正在加载会话<AppLoadingDots /></p>
        <p v-else-if="!listError && conversations.length === 0" class="conversation-muted" role="status">{{ creating ? '正在准备对话' : '暂无会话' }}<AppLoadingDots v-if="creating" /></p>
        <ul v-else class="conversation-list" aria-label="会话列表">
          <li v-for="(conversation, index) in conversations" :key="conversation.conversationId">
            <button
              class="conversation-list__item"
              :data-conversation-id="conversation.conversationId"
              :class="{ 'conversation-list__item--selected': selectedConversationId === conversation.conversationId }"
              :aria-pressed="selectedConversationId === conversation.conversationId"
              :disabled="sending || creating"
              @click="openConversation(conversation.conversationId)"
            >
              <span class="conversation-list__icon"><MessageCircle :size="17" aria-hidden="true" /></span>
              <span class="conversation-list__copy">
                <strong>会话 {{ index + 1 }}</strong>
                <small>{{ formatDate(conversation.updatedAt) }}</small>
              </span>
              <span class="conversation-list__status">{{ statusText(conversation.status) }}</span>
            </button>
          </li>
        </ul>
        <AppButton
          v-if="conversationHasMore"
          variant="quiet"
          size="sm"
          class="conversation-more"
          :loading="loadingList"
          @click="loadMoreConversations"
        >
          加载更多会话
        </AppButton>
      </AppCard>

      <AppCard class="conversation-panel" aria-label="当前教育支持对话">
        <div v-if="!selectedConversationId" class="conversation-starting">
          <p v-if="loadingList || creating" class="conversation-muted" role="status">正在准备对话<AppLoadingDots /></p>
          <AppStatusCallout v-else-if="listError" tone="attention" title="会话暂时无法打开" :body="listError">
            <AppButton size="sm" variant="secondary" @click="initializeConversation">重试</AppButton>
          </AppStatusCallout>
          <AppStatusCallout v-else-if="createError" tone="attention" title="暂时无法开始对话" :body="createError">
            <AppButton size="sm" variant="secondary" :loading="creating" @click="createConversation">使用同一请求重试</AppButton>
          </AppStatusCallout>
        </div>

        <template v-else>
          <header v-if="props.researchMode" class="conversation-panel__header">
            <div>
              <span class="support-kicker">当前会话</span>
              <h2>教育支持对话</h2>
              <p v-if="selectedConversation">创建于 {{ formatDate(selectedConversation.createdAt) }}</p>
            </div>
            <div class="conversation-panel__actions">
              <AppBadge v-if="selectedConversation" :tone="selectedConversation.status === 'active' || selectedConversation.status === 'open' ? 'support' : 'attention'">
                {{ statusText(selectedConversation.status) }}
              </AppBadge>
              <AppButton variant="quiet" size="sm" :loading="loadingDetail" :disabled="sending || creating" aria-label="刷新会话" @click="refreshConversation">
                <RotateCcw :size="15" aria-hidden="true" />刷新
              </AppButton>
            </div>
          </header>

          <AppStatusCallout v-if="detailError" tone="attention" title="会话内容暂不可用" :body="detailError">
            <AppButton size="sm" variant="secondary" :loading="loadingDetail" @click="refreshConversation">重试加载</AppButton>
          </AppStatusCallout>
          <p v-if="loadingDetail && !detail" class="conversation-muted" role="status">正在读取会话<AppLoadingDots /></p>
          <div v-else-if="detail" class="conversation-thread" aria-live="polite">
            <AppButton v-if="hasEarlierMessages" variant="quiet" size="sm" :loading="loadingMore" :disabled="sending || creating" @click="loadMoreMessages('earlier')">加载更早的对话</AppButton>
            <AppButton v-if="hasLaterMessages" variant="quiet" size="sm" :loading="loadingMore" :disabled="sending || creating" @click="loadMoreMessages('later')">加载更多对话</AppButton>
            <div v-if="detail.messages.length === 0" class="conversation-thread__empty">
              <div class="conversation-thread__welcome">
                <h3>有什么学习问题想一起梳理？</h3>
                <p>可以从复习安排、学习压力或目标规划开始。</p>
              </div>
              <div class="conversation-suggestions" aria-label="问题示例">
                <button
                  v-for="prompt in suggestedPrompts"
                  :key="prompt"
                  type="button"
                  class="conversation-suggestion"
                  :disabled="!canSend || Boolean(failedSubmission && failedSubmission.conversationId === selectedConversationId)"
                  @click="useSuggestedPrompt(prompt)"
                >
                  {{ prompt }}
                </button>
              </div>
            </div>
            <article
              v-for="message in detail.messages"
              :key="message.messageId"
              class="conversation-message"
              :class="`conversation-message--${message.role}`"
            >
              <div class="conversation-message__meta">
                <strong>{{ message.role === 'student' ? '你' : '教育支持' }}</strong>
                <time :datetime="message.createdAt">{{ formatDate(message.createdAt) }}</time>
                <span v-if="message.turn.status !== 'completed' || message.turn.action === 'ABSTAIN'" class="conversation-message__state">
                  {{ messageStateLabel(message) }}
                </span>
              </div>
              <p v-if="message.text" class="conversation-message__text">{{ message.text }}</p>
              <template v-if="message.content?.kind === 'answer'">
                <p class="conversation-message__text">{{ message.content.summary }}</p>
                <ul v-if="message.content.observations.length" class="conversation-message__details">
                  <li v-for="(observation, observationIndex) in message.content.observations" :key="`${message.messageId}-observation-${observationIndex}`">{{ observation }}</li>
                </ul>
                <ul v-if="message.content.suggestions.length" class="conversation-message__details">
                  <li v-for="(suggestion, suggestionIndex) in message.content.suggestions" :key="`${message.messageId}-suggestion-${suggestionIndex}`">{{ suggestion.text }}</li>
                </ul>
                <p class="conversation-message__disclaimer">{{ message.content.disclaimer }}</p>
              </template>
              <AppStatusCallout
                v-else-if="message.content?.kind === 'approved_safety_response'"
                tone="attention"
                title="安全提示"
                :body="message.content.text"
              />
              <AppStatusCallout
                v-else-if="researchMode && message.turn.action === 'CONTENT_REVIEW_HELD'"
                tone="info"
                title="草稿待核对"
                body="这份生成草稿尚未发布。你可以在下方选择是否将它分享给一位心理老师核对。"
              />
              <AppStatusCallout
                v-else-if="message.role === 'assistant' && message.turn.status === 'blocked'"
                tone="attention"
                title="这次对话已暂停"
                body="系统暂停了普通回复。你可以继续浏览已保存的其他对话。"
              />
              <AppStatusCallout
                v-else-if="message.role === 'assistant' && message.turn.status === 'failed'"
                tone="attention"
                title="本次回复未完成"
                body="没有保存未通过检查的回复内容。可刷新状态或稍后重试同一请求。"
              />
              <p v-else-if="message.role === 'student' && message.turn.status === 'requested'" class="conversation-message__pending" role="status">正在处理这条消息。</p>
              <AppStatusCallout
                v-else-if="message.role === 'student' && message.turn.status === 'blocked'"
                tone="attention"
                title="这条消息已暂停"
                :body="message.turn.action === 'CRISIS_ROUTE' ? '系统已显示安全提示，普通回复已暂停。' : '系统暂停了普通回复，没有提供未经审核的建议。'"
              />
              <AppStatusCallout
                v-else-if="message.role === 'student' && message.turn.status === 'failed'"
                tone="attention"
                title="本次回复未完成"
                body="没有保存未通过检查的回复内容。你可以稍后发送一条新消息。"
              />
              <div v-if="message.role === 'assistant' && message.turn.citations.length" class="conversation-citations">
                <strong>参考来源</strong>
                <ul>
                  <li v-for="citation in message.turn.citations" :key="citation.citationId">
                    <span>{{ citation.title || '已审核资料' }}</span>
                    <small v-if="citation.organization">{{ citation.organization }}</small>
                    <small v-if="citation.locator">{{ citation.locator }}</small>
                  </li>
                </ul>
              </div>
            </article>
          </div>

          <section v-if="receipt && receiptNeedsDisplay" class="conversation-receipt" aria-live="polite">
            <p v-if="receipt.status === 'requested'" class="conversation-pending" role="status">
              消息已收到，回复仍在处理中。请刷新会话查看状态。
            </p>
            <AppStatusCallout
              v-else-if="researchMode && receipt.action === 'CONTENT_REVIEW_HELD'"
              tone="info"
              title="草稿待核对"
              body="这份生成草稿尚未发布。你可以在下方选择是否将它分享给一位心理老师核对。"
            />
            <AppStatusCallout
              v-else-if="receipt.status === 'blocked' && receipt.content?.kind !== 'approved_safety_response'"
              tone="attention"
              title="这条消息已暂停"
              body="系统暂停了普通回复，没有提供未经审核的建议。"
            />
            <AppStatusCallout
              v-else-if="receipt.status === 'failed'"
              tone="attention"
              title="本次回复未完成"
              body="没有保存未通过检查的回复内容。你可以稍后发送一条新消息。"
            />
            <template v-if="receipt.content?.kind === 'approved_safety_response'">
              <AppStatusCallout tone="attention" title="安全提示" :body="receipt.content.text" />
            </template>
            <template v-else-if="receipt.content?.kind === 'answer'">
              <article class="conversation-message">
                <div class="conversation-message__meta"><strong>教育支持</strong><span>{{ turnStatusText(receipt) }}</span></div>
                <p class="conversation-message__text">{{ receipt.content.summary }}</p>
                <ul v-if="receipt.content.observations.length" class="conversation-message__details">
                  <li v-for="(observation, index) in receipt.content.observations" :key="`receipt-observation-${index}`">{{ observation }}</li>
                </ul>
                <ul v-if="receipt.content.suggestions.length" class="conversation-message__details">
                  <li v-for="(suggestion, index) in receipt.content.suggestions" :key="`receipt-suggestion-${index}`">{{ suggestion.text }}</li>
                </ul>
                <p class="conversation-message__disclaimer">{{ receipt.content.disclaimer }}</p>
                <div v-if="receipt.citations.length" class="conversation-citations">
                  <strong>参考来源</strong>
                  <ul><li v-for="citation in receipt.citations" :key="citation.citationId"><span>{{ citation.title || '已审核资料' }}</span><small v-if="citation.organization">{{ citation.organization }}</small><small v-if="citation.locator">{{ citation.locator }}</small></li></ul>
                </div>
              </article>
            </template>
          </section>

          <AppStatusCallout
            v-if="hasRequestedTurn"
            tone="info"
            title="上一条消息仍在处理中"
            body="刷新只读取已保存状态，不会重新发送消息；处理完成前不能继续发送。"
          />

          <form v-if="selectedConversation && selectedConversation.status !== 'closed' && selectedConversation.status !== 'archived'" class="conversation-composer" @submit.prevent="handleSend">
            <label class="sr-only" for="support-message">写下你的问题</label>
            <textarea
              ref="supportMessageInput"
              id="support-message"
              class="conversation-composer__input"
              v-model="draft"
              :disabled="sending || Boolean(failedSubmission && failedSubmission.conversationId === selectedConversationId)"
              maxlength="20000"
              rows="3"
              placeholder="说说你想讨论的学习问题…"
              :aria-describedby="sendError ? 'support-message-error' : 'support-message-help'"
            />
            <div class="conversation-composer__footer">
              <p v-if="sendError" id="support-message-error" class="conversation-composer__error" role="alert">
                {{ sendError }} 本次重试会沿用相同消息请求。
              </p>
              <p v-else id="support-message-help">AI 生成的回复仅供一般教育支持参考，不提供诊断或治疗建议。请勿填写姓名、学号等身份信息。</p>
              <AppButton type="submit" :loading="sending" :disabled="!canSend || (!draft.trim() && !failedSubmission)">
                <Send :size="15" aria-hidden="true" />{{ failedSubmission ? '重试发送' : '发送消息' }}
              </AppButton>
            </div>
          </form>
          <p v-else-if="selectedConversation" class="conversation-muted">这段会话已结束，无法继续发送消息。</p>
        </template>
      </AppCard>
    </div>

    <StudentIndependentEducationReviews
      v-if="props.researchMode && selectedConversation"
      :key="selectedConversationId"
      :conversation-id="selectedConversationId"
      :refresh-token="educationReviewRefreshToken"
    />

  </div>
</template>

<style scoped>
.education-support { padding-top: 0; padding-bottom: 64px; }
.support-heading { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 18px; }
.support-hero-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.support-hero-actions .support-back { margin-top: 0; color: #fff; }
.support-hero-actions .support-back:hover { color: #e7fbff; }
.support-kicker { color: var(--color-support); font-size: 11px; font-weight: 800; letter-spacing: .1em; }
.support-heading h1 { margin: 8px 0 5px; color: var(--color-text-primary); font-family: var(--font-display); font-size: clamp(30px, 4vw, 40px); letter-spacing: -.04em; }
.support-heading p { margin: 0; color: var(--color-text-secondary); font-size: 13px; line-height: 1.65; }
.support-boundary { margin-bottom: 18px; }
.conversation-workspace { display: grid; grid-template-columns: minmax(0, 1fr) minmax(240px, 300px); align-items: start; gap: 15px; }
.conversation-sidebar { order: 2; }
.conversation-panel { order: 1; }
.conversation-sidebar, .conversation-panel { min-width: 0; padding: 18px; }
.conversation-sidebar { display: grid; gap: 12px; }
.conversation-sidebar__heading, .conversation-panel__header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.conversation-sidebar__heading h2, .conversation-panel__header h2 { margin: 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: 17px; }
.conversation-sidebar__heading span { display: block; margin-top: 4px; color: var(--color-text-muted); font-size: 11px; }
.conversation-list { display: grid; gap: 6px; margin: 0; padding: 0; list-style: none; }
.conversation-list__item { display: flex; align-items: center; gap: 9px; width: 100%; padding: 10px 8px; border: 1px solid transparent; border-radius: var(--radius-control); color: inherit; background: transparent; text-align: left; cursor: pointer; }
.conversation-list__item:hover, .conversation-list__item--selected { border-color: var(--color-border); background: var(--color-support-wash); }
.conversation-list__item:focus-visible, .support-back:focus-visible { outline: 3px solid var(--color-focus-ring); outline-offset: 2px; }
.conversation-list__icon, .conversation-intro__icon { display: grid; flex: 0 0 34px; width: 34px; height: 34px; place-items: center; border-radius: 10px; color: var(--color-support); background: var(--color-support-wash); }
.conversation-list__copy { display: grid; flex: 1; min-width: 0; gap: 3px; }
.conversation-list__copy strong { overflow: hidden; color: var(--color-text-primary); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.conversation-list__copy small, .conversation-list__status { color: var(--color-text-muted); font-size: 10px; }
.conversation-list__status { flex: 0 0 auto; }
.conversation-more { justify-self: start; }
.conversation-muted { margin: 0; color: var(--color-text-secondary); font-size: 13px; line-height: 1.65; }
.conversation-panel { display: grid; gap: 15px; }
.conversation-starting { display: grid; min-height: 340px; place-items: center; }
.conversation-panel__header { padding-bottom: 12px; border-bottom: 1px solid var(--color-border); }
.conversation-panel__header h2 { margin-top: 4px; }
.conversation-panel__header p { margin: 4px 0 0; color: var(--color-text-muted); font-size: 11px; }
.conversation-panel__actions { display: flex; align-items: center; gap: 9px; }
.conversation-thread { display: grid; justify-items: start; gap: 12px; max-height: min(64vh, 680px); min-height: clamp(220px, 30vh, 380px); overflow-y: auto; padding: 4px 2px 8px; }
.conversation-thread__empty { display: grid; justify-items: center; align-content: center; gap: 18px; width: 100%; min-height: 180px; padding: 18px 8px; color: var(--color-text-secondary); text-align: center; }
.conversation-thread__welcome { display: grid; gap: 8px; }
.conversation-thread__welcome h3 { margin: 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: clamp(21px, 2.4vw, 26px); font-weight: 700; letter-spacing: -.025em; }
.conversation-thread__welcome p { max-width: 420px; margin: 0; color: var(--color-text-secondary); font-size: 13px; line-height: 1.7; }
.conversation-suggestions { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; max-width: 660px; }
.conversation-suggestion { padding: 8px 12px; border: 1px solid var(--color-border); border-radius: 999px; color: var(--color-text-primary); background: var(--color-surface); font: inherit; font-size: 12px; line-height: 1.4; cursor: pointer; transition: border-color var(--motion-fast) ease, background-color var(--motion-fast) ease; }
.conversation-suggestion:hover:not(:disabled) { border-color: rgb(0 177 226 / 38%); background: var(--color-info-wash); }
.conversation-suggestion:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.conversation-suggestion:disabled { color: var(--color-text-muted); cursor: not-allowed; }
.conversation-message { display: grid; gap: 8px; width: min(100%, 680px); padding: 12px 14px; border-radius: var(--radius-card); background: var(--color-surface-soft); }
.conversation-message--student { justify-self: end; width: min(92%, 600px); background: var(--color-support-wash); }
.conversation-message__meta { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; color: var(--color-text-muted); font-size: 10px; }
.conversation-message__meta strong { color: var(--color-text-primary); font-size: 12px; }
.conversation-message__state { color: var(--color-attention); }
.conversation-message__text { margin: 0; color: var(--color-text-primary); font-size: 13px; line-height: 1.75; white-space: pre-wrap; overflow-wrap: anywhere; }
.conversation-message__details { display: grid; gap: 6px; margin: 0; padding-left: 19px; color: var(--color-text-primary); font-size: 13px; line-height: 1.7; }
.conversation-message__disclaimer { margin: 0; padding-top: 8px; border-top: 1px solid var(--color-border); color: var(--color-text-secondary); font-size: 11px; line-height: 1.6; }
.conversation-message__pending, .conversation-pending { margin: 0; color: var(--color-text-secondary); font-size: 12px; }
.conversation-receipt { display: grid; gap: 10px; }
.conversation-citations { display: grid; gap: 6px; padding-top: 8px; border-top: 1px solid var(--color-border); }
.conversation-citations > strong { color: var(--color-text-secondary); font-size: 11px; }
.conversation-citations ul { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.conversation-citations li { display: grid; gap: 2px; min-width: 0; }
.conversation-citations li span { color: var(--color-text-primary); font-size: 11px; font-weight: 650; overflow-wrap: anywhere; }
.conversation-citations li small { color: var(--color-text-secondary); font-size: 10px; overflow-wrap: anywhere; }
.conversation-composer { display: grid; gap: 8px; padding: 10px 12px 11px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-dialog); background: var(--color-surface); transition: border-color var(--motion-fast) ease, box-shadow var(--motion-fast) ease; }
.conversation-composer:focus-within { border-color: var(--color-primary); box-shadow: 0 0 0 3px rgb(0 177 226 / 14%); }
.conversation-composer__input { width: 100%; min-height: 86px; resize: vertical; padding: 7px 6px; border: 0; border-radius: var(--radius-control); color: var(--color-text-primary); background: transparent; font: inherit; font-size: 13px; line-height: 1.6; }
.conversation-composer__input:focus-visible { outline: none; box-shadow: none; }
.conversation-composer__input:disabled { color: var(--color-text-muted); }
.conversation-composer__footer { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; padding-top: 9px; border-top: 1px solid var(--color-border); }
.conversation-composer__footer p { flex: 1; min-width: 0; margin: 0; color: var(--color-text-muted); font-size: 10px; line-height: 1.6; }
.conversation-composer__footer .conversation-composer__error { color: var(--color-attention); }
.support-back { display: inline-flex; align-items: center; gap: 7px; margin-top: 26px; color: var(--color-text-secondary); font-size: 12px; text-decoration: none; }
.support-back:hover { color: var(--color-primary); }
@media (max-width: 780px) {
  .conversation-workspace { grid-template-columns: minmax(0, 1fr); }
  .conversation-sidebar { order: 2; }
  .conversation-panel { order: 1; }
  .conversation-thread { max-height: 60vh; }
}
@media (max-width: 600px) {
  .conversation-sidebar, .conversation-panel { padding: 14px; }
  .conversation-message--student { width: 96%; }
  .conversation-composer__footer { align-items: flex-end; gap: 8px; }
}
</style>
