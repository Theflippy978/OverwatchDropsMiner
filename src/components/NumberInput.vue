<script setup lang="ts">
import { computed } from "vue";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

const props = defineProps<{
  modelValue: number;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: number];
}>();

const currentValue = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});

function increment() {
  const step = props.step || 1;
  const max = props.max ?? Infinity;
  emit("update:modelValue", Math.min(max, props.modelValue + step));
}

function decrement() {
  const step = props.step || 1;
  const min = props.min ?? -Infinity;
  emit("update:modelValue", Math.max(min, props.modelValue - step));
}
</script>

<template>
  <div class="flex items-center gap-2">
    <Button
      type="button"
      variant="outline"
      size="sm"
      class="h-8 w-8 p-0"
      :disabled="disabled"
      @click="decrement"
    >
      -
    </Button>
    <Input
      v-model.number="currentValue"
      type="number"
      :min="min"
      :max="max"
      :step="step"
      :disabled="disabled"
      class="h-8 text-center"
    />
    <Button
      type="button"
      variant="outline"
      size="sm"
      class="h-8 w-8 p-0"
      :disabled="disabled"
      @click="increment"
    >
      +
    </Button>
  </div>
</template>
