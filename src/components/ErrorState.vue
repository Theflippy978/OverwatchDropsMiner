<script setup lang="ts">
import { computed } from "vue";
import { Button } from "@/components/ui/button";

const props = defineProps<{
  title?: string;
  message: string;
  retryable?: boolean;
}>();

const emit = defineEmits<{
  retry: [];
}>();

const displayTitle = computed(() => props.title || "出错了");
</script>

<template>
  <div class="flex flex-col items-center justify-center py-8 text-center">
    <div class="mb-4 rounded-full bg-red-500/10 p-4">
      <svg
        class="h-8 w-8 text-red-500"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          stroke-width="2"
          d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
        />
      </svg>
    </div>
    <h3 class="mb-2 text-lg font-semibold">{{ displayTitle }}</h3>
    <p class="mb-4 text-sm text-muted-foreground">{{ message }}</p>
    <Button
      v-if="retryable"
      variant="outline"
      @click="emit('retry')"
    >
      重试
    </Button>
  </div>
</template>
