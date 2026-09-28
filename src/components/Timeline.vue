<script setup lang="ts">
import { computed } from "vue";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const props = defineProps<{
  title: string;
  events: Array<{
    id: string;
    title: string;
    description?: string;
    time: string;
    type?: "info" | "success" | "warning" | "error";
  }>;
}>();

const typeColors = {
  info: "bg-blue-500",
  success: "bg-green-500",
  warning: "bg-yellow-500",
  error: "bg-red-500",
};
</script>

<template>
  <Card>
    <CardHeader>
      <CardTitle class="text-sm">{{ title }}</CardTitle>
    </CardHeader>
    <CardContent>
      <div v-if="events.length === 0" class="py-8 text-center text-sm text-muted-foreground">
        暂无事件
      </div>
      <div v-else class="space-y-4">
        <div
          v-for="event in events"
          :key="event.id"
          class="flex gap-3"
        >
          <div class="flex flex-col items-center">
            <div
              class="h-3 w-3 rounded-full"
              :class="typeColors[event.type || 'info']"
            />
            <div class="w-px flex-1 bg-border" />
          </div>
          <div class="flex-1 pb-4">
            <div class="flex items-center justify-between">
              <p class="text-sm font-medium">{{ event.title }}</p>
              <span class="text-xs text-muted-foreground">{{ event.time }}</span>
            </div>
            <p v-if="event.description" class="text-xs text-muted-foreground">
              {{ event.description }}
            </p>
          </div>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
