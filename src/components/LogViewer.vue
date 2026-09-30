<script setup lang="ts">
import { ref, watch, nextTick } from "vue";
import { useLogsStore } from "@/stores/logs";
import { useAccountsStore } from "@/stores/accounts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const logsStore = useLogsStore();
const accountsStore = useAccountsStore();
const scrollRef = ref<HTMLElement | null>(null);
const collapsed = ref(false);

watch(
  () => logsStore.filteredLogs.length,
  async () => {
    const el = scrollRef.value;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= 30;
    if (!atBottom) return;
    await nextTick();
    el.scrollTop = el.scrollHeight;
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

function handleClear() {
  const filterId = logsStore.filterAccountId;
  if (filterId) {
    logsStore.clearByAccount(filterId);
  } else {
    logsStore.clear();
  }
}
</script>

<template>
  <Card class="h-full">
    <CardHeader class="pb-3">
      <div class="flex items-center justify-between">
        <CardTitle class="text-sm">运行日志</CardTitle>
        <div class="flex items-center gap-2">
          <select
            class="h-7 rounded-md border border-border bg-background px-2 text-xs"
            :value="logsStore.filterAccountId ?? ''"
            @change="logsStore.setFilter(($event.target as HTMLSelectElement).value || null)"
          >
            <option value="">全部账号</option>
            <option
              v-for="acc in accountsStore.accounts"
              :key="acc.id"
              :value="acc.id"
            >
              {{ acc.remark }}
            </option>
          </select>
          <Button
            size="sm"
            variant="ghost"
            class="h-7 text-xs text-muted-foreground"
            @click="collapsed = !collapsed"
          >
            {{ collapsed ? "展开" : "折叠" }}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            class="h-7 text-xs text-muted-foreground"
            @click="handleClear"
          >
            清空
          </Button>
        </div>
      </div>
    </CardHeader>
    <CardContent class="pt-0">
      <div
        ref="scrollRef"
        class="overflow-y-auto rounded-md border border-border bg-muted/30 p-3 transition-all duration-300"
        :class="collapsed ? 'max-h-0' : 'h-[calc(100vh-320px)]'"
      >
        <div v-if="logsStore.filteredLogs.length === 0" class="py-8 text-center text-sm text-muted-foreground">
          暂无日志
        </div>
        <div v-else class="space-y-1 font-mono text-xs">
          <div
            v-for="log in logsStore.filteredLogs"
            :key="log.seq"
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
      </div>
    </CardContent>
  </Card>
</template>
