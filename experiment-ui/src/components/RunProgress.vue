<template>
  <main class="monitor">
    <header class="monitor-header">
      <div><p class="eyebrow">UXAGENT · LIVE MONITOR</p><h1>페르소나별 진행 상황</h1>
        <p class="muted">{{ data.start_url || '실행 상태를 불러오고 있습니다.' }}</p></div>
      <n-button @click="fetchOnce">새로고침</n-button>
    </header>
    <n-alert v-if="error" type="error" title="진행 상태 연결 오류" class="notice">
      {{ error }} · 연결을 자동으로 재시도합니다. 표시된 정보는 마지막으로 받은 상태입니다.
    </n-alert>
    <n-alert v-if="data.error" type="error" class="notice">{{ data.error }}</n-alert>
    <section class="summary">
      <div><span>전체 페르소나</span><strong>{{ participants.length }}</strong></div>
      <div><span>진행 중</span><strong>{{ activeCount }}</strong></div>
      <div><span>완료</span><strong>{{ completed }}</strong></div>
      <div><span>오류</span><strong>{{ failed }}</strong></div>
    </section>
    <n-card class="notice">
      <div class="phase"><strong>{{ runLabel }}</strong><span>{{ completed }} / {{ participants.length }} 완료</span></div>
      <n-progress type="line" :percentage="completion" :status="failed ? 'warning' : 'success'" />
      <p class="muted">{{ phaseLabel }} · {{ data.current || 0 }} / {{ data.total || 0 }} 처리</p>
      <small class="muted">1초마다 자동 갱신 · {{ lastUpdated ? `마지막 수신 ${lastUpdated.toLocaleTimeString('ko-KR')}` : '연결 중' }}</small>
    </n-card>
    <n-empty v-if="!participants.length" description="실행 중인 페르소나가 없습니다." />
    <section class="participants">
      <n-card v-for="p in participants" :key="p.id" :title="p.name">
        <template #header-extra><n-tag :type="tagType(p.status)">{{ statusLabel(p.status) }}</n-tag></template>
        <p class="activity">{{ activityLabel(p) }}</p>
        <div class="phase"><span>브라우저 행동 수</span><strong>{{ p.steps }} / {{ p.max_steps }}</strong></div>
        <n-progress type="line" :percentage="Math.min(100, Math.round(p.steps / Math.max(1, p.max_steps) * 100))" :show-indicator="false" :processing="p.status === 'running'" :status="p.status === 'error' ? 'error' : 'default'" />
        <small class="muted">최대 행동 수 기준이며, 목표를 달성하면 일찍 종료할 수 있습니다.</small>
        <p v-if="p.url" class="url">현재 페이지: {{ p.url }}</p>
        <n-alert v-if="p.error" type="error" class="participant-error">{{ p.error }}</n-alert>
        <details v-if="p.persona"><summary>페르소나 정보</summary><p class="persona">{{ p.persona }}</p><p>{{ p.intent }}</p></details>
        <details v-if="p.action"><summary>최근 행동</summary><pre>{{ p.action }}</pre></details>
      </n-card>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useProgress, type Participant } from '../composables/useProgress'

const runId = new URLSearchParams(window.location.search).get('run_id') || undefined
const { data, error, lastUpdated, start, stop, fetchOnce } = useProgress(1000, runId)
const participants = computed(() => data.value.participants || [])
const completed = computed(() => participants.value.filter(p => p.status === 'completed').length)
const failed = computed(() => participants.value.filter(p => p.status === 'error').length)
const activeCount = computed(() => participants.value.filter(p => ['running', 'surveying', 'generating'].includes(p.status)).length)
const completion = computed(() => participants.value.length ? Math.round(completed.value / participants.value.length * 100) : 0)
const labels: Record<string, string> = { generating: '생성 중', queued: '실행 대기', running: '실행 중', awaiting_survey: '설문 대기', surveying: '설문 작성 중', completed: '완료', error: '오류' }
const statusLabel = (status: string) => labels[status] || status
const phaseLabel = computed(() => ({ personas: '페르소나 생성', agents: '웹사이트 탐색', surveys: '설문 작성' }[data.value.phase || ''] || '준비 중'))
const runLabel = computed(() => ({ completed: '실행 완료', completed_with_errors: '실행 종료 · 일부 오류', error: '실행 실패', idle: '실행 대기' }[data.value.status] || '실시간 진행 중'))
function tagType(status: string) {
  if (status === 'error') return 'error'
  if (status === 'completed') return 'success'
  if (['running', 'surveying', 'generating'].includes(status)) return 'info'
  return 'default'
}
function activityLabel(p: Participant) {
  if (p.status === 'running') return p.message === 'Executing action' ? '브라우저에서 행동 실행 중' : p.message === 'Preparing browser' ? '브라우저 준비 중' : '페이지를 살펴보고 다음 행동을 결정하는 중'
  return statusLabel(p.status)
}
onMounted(() => { document.title = 'UXAgent · 페르소나 진행 상황'; start() })
watch(() => data.value.status, status => {
  if (['completed', 'completed_with_errors', 'error'].includes(status)) stop()
})
</script>

<style scoped>
.monitor { width: min(1120px, 100%); margin: 0 auto; padding: 12px 0 32px; }
.monitor-header, .phase { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.eyebrow { color: #168568; font-size: 12px; font-weight: 700; letter-spacing: 2px; }
h1 { margin: 8px 0; font-size: 28px; }
.muted { color: #687584; overflow-wrap: anywhere; }
.notice { margin-bottom: 20px; }
.summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 24px 0; }
.summary > div { padding: 20px; border: 1px solid #e1e7eb; border-radius: 12px; background: #f8fafb; }
.summary span { color: #687584; font-size: 13px; }
.summary strong { display: block; font-size: 30px; margin-top: 8px; }
.participants { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.phase { margin-bottom: 10px; }
.activity { margin-top: 0; color: #28725f; }
.url, .persona, pre, .participant-error { overflow-wrap: anywhere; word-break: break-word; }
.url { font-size: 12px; color: #687584; }
details { margin-top: 16px; } summary { cursor: pointer; color: #28725f; }
.persona, pre { white-space: pre-wrap; max-height: 280px; overflow: auto; font-size: 12px; }
@media(max-width: 720px) { .participants { grid-template-columns: 1fr; } .summary { grid-template-columns: repeat(2, 1fr); } h1 { font-size: 22px; } }
</style>
