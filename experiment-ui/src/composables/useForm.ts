// src/composables/useForm.ts
import { reactive, watch } from 'vue'
import type { WizardForm } from '../types'
import decathlonHikingPreset from '../presets/decathlon-hiking.json'

// Defaults are portable; browser drafts are restored after the one-time preset update.
export function getWizardDefaults(): WizardForm {
  return structuredClone(decathlonHikingPreset.form)
}

export function createWizardForm() {
  const STORAGE_KEY = 'wizard_form'
  let saved: (Partial<WizardForm> & { _preset?: string }) | null = null
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
    if (value && typeof value === 'object' && !Array.isArray(value)) saved = value
  } catch { /* Unavailable storage or an invalid draft: use the preset. */ }

  const defaults = getWizardDefaults()
  const form = reactive<WizardForm>(defaults)

  // Migrate older drafts to this study once. Subsequent visits retain edits.
  if (saved?._preset === decathlonHikingPreset.id) {
    if (saved.persona && typeof saved.persona === 'object') Object.assign(form.persona, saved.persona)
    if (saved.experiment && typeof saved.experiment === 'object') Object.assign(form.experiment, saved.experiment)
    if (saved.survey && typeof saved.survey === 'object') Object.assign(form.survey, saved.survey)
  }

  watch(form, (value) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...value, _preset: decathlonHikingPreset.id }))
    } catch { /* The form still works when browser storage is unavailable. */ }
  }, { deep: true, immediate: true })

  return form
}


export type RunPayload = {
  total_personas: number
  demographics: { name: string; choices: { name: string; weight: number }[] }[]
  general_intent: string
  example_persona?: string
  start_url: string
  max_steps: number
  concurrency: number
  questionnaire: Record<string, any>
  headless: boolean
}

export function buildRunPayload(form: WizardForm): RunPayload {
  // parse questionnaire string to object
  let questionnaireObj: any = {}
  try { questionnaireObj = JSON.parse(form?.survey?.questionnaire ?? '{}') } catch { questionnaireObj = {} }

  return {
    total_personas: Number(form?.persona?.numSubjects ?? 0),
    demographics:   (form?.persona?.demographics ?? []).map(f => ({
      name: String(f?.name ?? '').trim(),
      choices: Array.isArray(f?.choices) ? f.choices.map(c => ({
        name: String(c?.name ?? '').trim(),
        weight: Number(c?.weight ?? 0) / 100
      })) : []
    })),
    general_intent: String(form?.persona?.generalIntent ?? ''),
    // Conditionally include only when enabled and non-empty
    ...(form?.persona?.useExamplePersona ? { example_persona: form?.persona?.examplePersona } :
        {example_persona: ''}),
    start_url:      String(form?.experiment?.startUrl ?? ''),
    max_steps:      Number(form?.experiment?.maxSteps ?? 0),
    concurrency:    Number(form?.experiment?.concurrency ?? 1),
    questionnaire:  questionnaireObj,
    headless:       Boolean(form?.experiment?.headless ?? true),
  }
}

export async function submitWizardForm(form: WizardForm) {
  const payload = buildRunPayload(form)
  const res = await fetch('/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  if (!res.ok) {
    // surface server’s error body to help you debug (400 shows missing fields)
    const text = await res.text()
    throw new Error(`Submit failed: ${res.status} ${text}`)
  }
  return await res.json()
}
