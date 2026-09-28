<script setup lang="ts">
import { computed } from "vue";
import { Label } from "@/components/ui/label";

const props = defineProps<{
  label: string;
  required?: boolean;
  error?: string;
  hint?: string;
}>();

const labelFor = computed(() => props.label.toLowerCase().replace(/\s+/g, "-"));
</script>

<template>
  <div class="space-y-2">
    <Label :for="labelFor" class="text-sm font-medium">
      {{ label }}
      <span v-if="required" class="text-red-500">*</span>
    </Label>
    <slot />
    <p v-if="error" class="text-xs text-red-500">{{ error }}</p>
    <p v-else-if="hint" class="text-xs text-muted-foreground">{{ hint }}</p>
  </div>
</template>
