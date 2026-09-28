<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";

const isOpen = ref(false);
const position = ref({ x: 0, y: 0 });

function open(event: MouseEvent) {
  event.preventDefault();
  position.value = { x: event.clientX, y: event.clientY };
  isOpen.value = true;
}

function close() {
  isOpen.value = false;
}

onMounted(() => {
  document.addEventListener("click", close);
});

onUnmounted(() => {
  document.removeEventListener("click", close);
});
</script>

<template>
  <div @contextmenu="open">
    <slot />
  </div>
  <Teleport to="body">
    <div
      v-if="isOpen"
      class="fixed z-50 min-w-[8rem] rounded-md border border-border bg-card p-1 shadow-lg"
      :style="{ left: `${position.x}px`, top: `${position.y}px` }"
      @click.stop
    >
      <slot name="menu" />
    </div>
  </Teleport>
</template>
