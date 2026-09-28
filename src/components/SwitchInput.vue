<script setup lang="ts">
import { computed } from "vue";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";

const props = defineProps<{
  modelValue: boolean;
  label?: string;
  description?: string;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: boolean];
}>();

const currentValue = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});
</script>

<template>
  <div class="flex items-center justify-between">
    <div class="space-y-0.5">
      <Label v-if="label" class="text-sm font-medium">{{ label }}</Label>
      <p v-if="description" class="text-xs text-muted-foreground">{{ description }}</p>
    </div>
    <Switch
      v-model="currentValue"
      :disabled="disabled"
    />
  </div>
</template>
