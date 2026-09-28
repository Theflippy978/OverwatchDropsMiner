<script setup lang="ts">
import { computed } from "vue";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const props = defineProps<{
  modelValue: string;
  tabs: Array<{ value: string; label: string }>;
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
  <Tabs v-model="currentValue" class="w-full">
    <TabsList class="grid w-full" :style="{ gridTemplateColumns: `repeat(${tabs.length}, 1fr)` }">
      <TabsTrigger
        v-for="tab in tabs"
        :key="tab.value"
        :value="tab.value"
      >
        {{ tab.label }}
      </TabsTrigger>
    </TabsList>
    <TabsContent
      v-for="tab in tabs"
      :key="tab.value"
      :value="tab.value"
    >
      <slot :name="tab.value" />
    </TabsContent>
  </Tabs>
</template>
