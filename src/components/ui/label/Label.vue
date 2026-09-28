<script setup lang="ts">
import { cva } from "class-variance-authority";

const labelVariants = cva(
  "text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
);

interface Props {
  for?: string;
  class?: string;
}

const props = defineProps<Props>();
</script>

<template>
  <label
    :for="props.for"
    :class="labelVariants({ class: props.class })"
  >
    <slot />
  </label>
</template>
