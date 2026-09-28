<script setup lang="ts">
import { computed } from "vue";
import { Progress } from "@/components/ui/progress";

const props = defineProps<{
  value: number;
  max?: number;
  label?: string;
  showValue?: boolean;
}>();

const percent = computed(() => {
  const max = props.max || 100;
  return Math.min(100, Math.round((props.value / max) * 100));
});
</script>

<template>
  <div class="space-y-2">
    <div v-if="label" class="flex items-center justify-between text-sm">
      <span class="text-muted-foreground">{{ label }}</span>
      <span v-if="showValue" class="font-medium">{{ percent }}%</span>
    </div>
    <Progress :value="percent" class="h-2" />
  </div>
</template>
