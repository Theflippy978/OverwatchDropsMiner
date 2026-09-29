<script setup lang="ts">
import { ref, watch, nextTick } from "vue";
import { useLogsStore } from "@/stores/logs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";

const logsStore = useLogsStore();
const scrollRef = ref<HTMLElement | null>(null);

// 自动滚动到底部
watch(
  () => logsStore.logs.length,
  async () => {
    await nextTick();
    if (scrollRef.value) {
      scrollRef.value.scrollTop = scrollRef.value.scrollHeight;
    }
  }
);

function getLevelColor(level: string) {
  switch (level) {
    case "error":
      return "text-red-500";
    case "warning":
      return "text-yellow-500";
    case "debug":
      return "text-muted-foreground";
    default:
      return "text-foreground";
  }
}

function formatTime(timestamp: string) {
  return new Date(timestamp).toLocaleTimeString("zh-CN");
}
</script>

<template>
  <Card class="h-full">
    <CardHeader class="pb-3">
      <div class="flex items-center justify-between">
        <CardTitle class="text-sm">运行日志</CardTitle>
        <Button
          size="sm"
          variant="ghost"
          class="h-7 text-xs text-muted-foreground"
          @click="logsStore.clear()"
        >
          清空
        </Button>
      </div>
    </CardHeader>
    <CardContent class="pt-0">
      <ScrollArea ref="scrollRef" class="h-[calc(100vh-320px)] rounded-md border border-border bg-muted/30 p-3">
        <div v-if="logsStore.logs.length === 0" class="py-8 text-center text-sm text-muted-foreground">
          暂无日志
        </div>
        <div v-else class="space-y-1 font-mono text-xs">
          <div
            v-for="(log, index) in logsStore.logs"
            :key="index"
            class="flex gap-2"
          >
            <span class="shrink-0 text-muted-foreground">{{ formatTime(log.timestamp) }}</span>
            <span
              v-if="log.account_id"
              class="shrink-0 text-blue-500"
            >
              [{{ log.account_id.slice(0, 6) }}]
            </span>
            <span :class="getLevelColor(log.level)">
              {{ log.message }}
            </span>
          </div>
        </div>
      </ScrollArea>
    </CardContent>
  </Card>
</template>
