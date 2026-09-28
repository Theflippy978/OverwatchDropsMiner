<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  title: string;
  description?: string;
}>();

const pageTitle = computed(() => props.title);
</script>

<template>
  <div class="space-y-4">
    <div>
      <h1 class="text-2xl font-bold">{{ pageTitle }}</h1>
      <p v-if="description" class="text-sm text-muted-foreground">
        {{ description }}
      </p>
    </div>
    <slot />
  </div>
</template>
