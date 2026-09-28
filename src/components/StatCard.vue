<script setup lang="ts">
import { computed } from "vue";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const props = defineProps<{
  title: string;
  value: string | number;
  description?: string;
  icon?: string;
}>();

const displayValue = computed(() => props.value);
</script>

<template>
  <Card>
    <CardHeader class="flex flex-row items-center justify-between space-y-0 pb-2">
      <CardTitle class="text-sm font-medium">{{ title }}</CardTitle>
      <span v-if="icon" class="text-2xl">{{ icon }}</span>
    </CardHeader>
    <CardContent>
      <div class="text-2xl font-bold">{{ displayValue }}</div>
      <p v-if="description" class="text-xs text-muted-foreground">
        {{ description }}
      </p>
    </CardContent>
  </Card>
</template>
