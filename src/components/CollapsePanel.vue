<script setup lang="ts">
import { ref } from "vue";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const props = defineProps<{
  title: string;
  defaultOpen?: boolean;
}>();

const isOpen = ref(props.defaultOpen ?? false);
</script>

<template>
  <Card>
    <CardHeader class="pb-3">
      <div class="flex items-center justify-between">
        <CardTitle class="text-sm">{{ title }}</CardTitle>
        <Button
          size="sm"
          variant="ghost"
          class="h-7 w-7 p-0"
          @click="isOpen = !isOpen"
        >
          <span
            class="transition-transform"
            :class="{ 'rotate-180': isOpen }"
          >
            ▼
          </span>
        </Button>
      </div>
    </CardHeader>
    <CardContent v-show="isOpen" class="pt-0">
      <slot />
    </CardContent>
  </Card>
</template>
