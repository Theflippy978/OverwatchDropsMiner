<script setup lang="ts">
import { computed } from "vue";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";

const props = defineProps<{
  modelValue: string;
  label?: string;
  placeholder?: string;
  rows?: number;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: string];
}>();

const currentValue = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});
</script>

<template>
  <div class="space-y-2">
    <Label v-if="label" class="text-sm font-medium">{{ label }}</Label>
    <Textarea
      v-model="currentValue"
      :placeholder="placeholder"
      :rows="rows || 3"
      :disabled="disabled"
      class="resize-none"
    />
  </div>
</template>
