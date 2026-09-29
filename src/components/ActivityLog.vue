<script setup lang="ts">
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";

const props = defineProps<{
  logs: Array<{
    id: string;
    timestamp: string;
    level: "info" | "warning" | "error" | "debug";
    message: string;
    accountId?: string;
  }>;
}>();

const levelColors = {
  info: "default",
  warning: "secondary",
  error: "destructive",
  debug: "outline",
} as const;

const levelLabels = {
  info: "信息",
  warning: "警告",
  error: "错误",
  debug: "调试",
};

function formatTime(timestamp: string) {
  return new Date(timestamp).toLocaleTimeString("zh-CN");
}
</script>

<template>
  <Card>
    <CardHeader>
      <CardTitle class="text-sm">活动日志</CardTitle>
    </CardHeader>
    <CardContent>
      <ScrollArea class="h-64">
        <div v-if="logs.length === 0" class="py-8 text-center text-sm text-muted-foreground">
          暂无日志
        </div>
        <div v-else class="space-y-2">
          <div
            v-for="log in logs"
            :key="log.id"
            class="flex items-start gap-2 text-sm"
          >
            <span class="shrink-0 text-xs text-muted-foreground">
              {{ formatTime(log.timestamp) }}
            </span>
            <Badge :variant="levelColors[log.level]" class="shrink-0 text-xs">
              {{ levelLabels[log.level] }}
            </Badge>
            <span v-if="log.accountId" class="shrink-0 text-xs text-blue-500">
              [{{ log.accountId.slice(0, 6) }}]
            </span>
            <span class="text-xs">{{ log.message }}</span>
          </div>
        </div>
      </ScrollArea>
    </CardContent>
  </Card>
</template>
