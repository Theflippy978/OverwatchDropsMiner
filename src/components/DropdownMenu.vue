<script setup lang="ts">
import { ref } from "vue";
import { Button } from "@/components/ui/button";

defineProps<{
  label: string;
  icon?: string;
}>();

const isOpen = ref(false);
</script>

<template>
  <div class="relative">
    <Button
      variant="outline"
      size="sm"
      @click="isOpen = !isOpen"
    >
      {{ label }}
    </Button>
    <div
      v-if="isOpen"
      class="absolute right-0 z-10 mt-1 w-48 rounded-md border border-border bg-card p-1 shadow-lg"
    >
      <slot />
    </div>
  </div>
</template>
