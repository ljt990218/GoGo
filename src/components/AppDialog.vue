<script setup lang='ts'>
import { nextTick, onMounted, onUnmounted, ref } from 'vue'

defineProps<{ title: string, locked?: boolean, placement?: 'center' | 'right' }>()
const emit = defineEmits<{ close: [] }>()
const panel = ref<HTMLElement | null>(null)
let previous: HTMLElement | null = null

function trap(event: KeyboardEvent) {
  if (event.key !== 'Tab') return
  const targets = [...(panel.value?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex="0"]') ?? [])]
  if (!targets.length) {
    event.preventDefault()
    return
  }
  const first = targets[0]
  const last = targets[targets.length - 1]
  if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.value)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

onMounted(async () => {
  previous = document.activeElement as HTMLElement | null
  await nextTick()
  panel.value?.focus()
})
onUnmounted(() => previous?.focus())
</script>

<template>
  <Teleport to='body'>
    <div :class='["dialog-backdrop", { "drawer-backdrop": placement === "right" }]' @click.self='!locked && emit("close")'>
      <section ref='panel' :class='["dialog", { "drawer": placement === "right" }]' role='dialog' aria-modal='true' aria-labelledby='dialog-heading' tabindex='-1' @keydown='trap' @keydown.esc.stop.prevent='!locked && emit("close")'>
        <h2 id='dialog-heading'>{{ title }}</h2>
        <slot />
      </section>
    </div>
  </Teleport>
</template>
