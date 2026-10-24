<template>
  <n-config-provider>
    <n-dialog-provider>
      <n-message-provider>
        <RunProgress v-if="isMonitor" />
        <template v-else>
        <TopProgressBar
        :active="progressActive"
        @done="progressActive = false"
        @height="barHeight = $event"
        />
        <div v-if="monitorUrl" class="monitor-link">
          <a :href="monitorUrl" target="_blank" rel="noopener">페르소나별 진행 상황 열기 ↗</a>
          <span v-if="popupBlocked"> 새 창이 차단되었습니다. 링크를 눌러 열어주세요.</span>
        </div>
        <n-layout
          class="min-h-screen"
          :style="{ paddingTop: `${barHeight}px` }"
        >
          <n-layout-header bordered>
            <div class="container">
              <n-space vertical>
                <n-steps :current="nav.current.value" :status="currentStatus">
                  <n-step
                    title="Participant Recruitment"
                    description="Configure participant demographics"
                  />
                  <n-step
                    title="Survey"
                    description="Provide a questionnaire"
                  />
                  <n-step title="Review" description="Confirm & Run" />
                </n-steps>
              </n-space>
            </div>
          </n-layout-header>

          <n-layout-content>
            <div class="container content">
              <transition name="fade" mode="out-in">
                <component
                  :is="stepComponents[nav.current.value - 1]"
                  :key="nav.current.value"
                />
              </transition>
            </div>
          </n-layout-content>
        </n-layout>
        </template>
      </n-message-provider>
    </n-dialog-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { provide, ref } from "vue";
import type { StepsProps } from "naive-ui";
import { FORM_KEY, NAV_KEY, type WizardNav } from "./types";
import { createWizardForm, submitWizardForm } from "./composables/useForm";
import TopProgressBar from "./components/topProgressBar.vue";
import RunProgress from "./components/RunProgress.vue";
import { useRouteQuery } from "@vueuse/router";

// ---- steps ----
import personas from "./steps/personas.vue";
import survey from "./steps/survey.vue";
import reviewSubmit from "./steps/reviewSubmit.vue";

// ---- shared form ----
const form = createWizardForm();
provide(FORM_KEY, form);

// --- NEW: define barHeight ---
const barHeight = ref(0);

// ---- nav ----
const steps = 3;
// const current = ref<number>(1);
const current = useRouteQuery("step", 1, { transform: Number });
const currentStatus = ref<StepsProps["status"]>("process");

const progressActive = ref(false);
const isMonitor = new URLSearchParams(window.location.search).get("view") === "progress";
const monitorUrl = ref("");
const popupBlocked = ref(false);
let starting = false;

const next = () => {
  if (current.value < steps) current.value++;
};
const prev = () => {
  if (current.value > 1) current.value--;
};
const finish = async () => {
  if (starting) return;
  starting = true;
  // Open synchronously during the click so browsers allow the new window.
  const monitor = window.open("about:blank", "_blank", "popup,width=1200,height=850");
  if (monitor) {
    monitor.opener = null;
    monitor.document.title = "진행 상황 준비 중";
    monitor.document.body.textContent = "실행을 시작하고 있습니다…";
  }
  popupBlocked.value = !monitor;
  try {
    const result = await submitWizardForm(form);
    const url = new URL(window.location.href);
    url.search = new URLSearchParams({ view: "progress", run_id: result.run_id }).toString();
    monitorUrl.value = url.toString();
    if (monitor && !monitor.closed) monitor.location.replace(monitorUrl.value);
    progressActive.value = true;
  } catch (e) {
    monitor?.close();
    throw e;
  } finally {
    starting = false;
  }
};

const nav: WizardNav = { current, steps, next, prev, finish };
provide(NAV_KEY, nav);

const stepComponents = [personas, survey, reviewSubmit];
</script>

<style scoped>
.monitor-link { padding: 12px 24px; background: #edf8f3; }
.container {
  max-width: 960px;
  margin: 0 auto;
  padding: 16px;
}
.content {
  padding: 24px 16px;
  min-height: 52vh;
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.18s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
