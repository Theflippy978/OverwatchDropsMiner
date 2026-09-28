<script setup lang="ts">
import { ref, onMounted } from "vue";

const props = defineProps<{
  message: string;
  type?: "success" | "error" | "warning" | "info";
  duration?: number;
}>();

const emit = defineEmits<{
  close: [];
}>();

const visible = ref(true);

onMounted(() => {
  const duration = props.duration || 3000;
  setTimeout(() => {
    visible.value = false;
    emit("close");
  }, duration);
});

const typeClasses = {
  success: "bg-green-500/10 text-green-500 border-green-500/20",
  error: "bg-red-500/10 text-red-500 border-red-500/20",
  warning: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20",
  info: "bg-blue-500/10 text-blue-500 border-blue-500/20",
};
</script>

<template>
  <Transition
    enter-active-class="transition-all duration-300"
    enter-from-class="opacity-0 translate-y-2"
    enter-to-class="opacity-100 translate-y-0"
    leave-active-class="transition-all duration-300"
    leave-from-class="opacity-100 translate-y-0"
    leave-to-class="opacity-0 translate-y-2"
  >
    <div
      v-if="visible"
      class="fixed bottom-4 right-4 z-50 flex items-center gap-2 rounded-lg border p-3 shadow-lg"
      :class="typeClasses[type || 'info']"
    >
      <span class="text-sm">{{ message }}</span>
      <button
        class="ml-2 text-current opacity-60 hover:opacity-100"
        @click="visible = false; emit('close')"
      >
        ✕
      </button>
    </div>
  </Transition>
</template>
