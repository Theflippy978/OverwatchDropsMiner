<script setup lang="ts">
import { ref, computed } from "vue";
import { Input } from "@/components/ui/input";

const props = defineProps<{
  modelValue: string;
  placeholder?: string;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: string];
  search: [value: string];
}>();

const currentValue = computed({
  get: () => props.modelValue,
  set: (value) => {
    emit("update:modelValue", value);
    emit("search", value);
  },
});

const searchQuery = ref("");
</script>

<template>
  <div class="relative">
    <svg
      class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
    >
      <path
        stroke-linecap="round"
        stroke-linejoin="round"
        stroke-width="2"
        d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
      />
    </svg>
    <Input
      v-model="currentValue"
      :placeholder="placeholder || '搜索...'"
      class="pl-9"
    />
  </div>
</template>
