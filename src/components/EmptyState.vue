<script setup lang="ts">
import { Button } from "@/components/ui/button";

const props = defineProps<{
  title: string;
  description?: string;
  actionText?: string;
  loading?: boolean;
}>();

const emit = defineEmits<{
  action: [];
}>();
</script>

<template>
  <div class="flex flex-col items-center justify-center py-12 text-center">
    <div class="mb-4 rounded-full bg-muted p-4">
      <slot name="icon">
        <svg
          class="h-8 w-8 text-muted-foreground"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"
          />
        </svg>
      </slot>
    </div>
    <h3 class="mb-2 text-lg font-semibold">{{ title }}</h3>
    <p v-if="description" class="mb-4 text-sm text-muted-foreground">
      {{ description }}
    </p>
    <Button
      v-if="actionText"
      :disabled="loading"
      @click="emit('action')"
    >
      {{ loading ? "加载中..." : actionText }}
    </Button>
  </div>
</template>
