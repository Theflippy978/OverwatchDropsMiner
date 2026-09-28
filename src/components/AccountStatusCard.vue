<script setup lang="ts">
import { ref, onMounted, watch } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

const props = defineProps<{
  accountId: string;
  running: boolean;
}>();

const watchTimeSeconds = ref(0);
const taskProgress = ref<any>(null);
const loading = ref(false);

async function fetchStatus() {
  loading.value = true;
  try {
    const status = await invoke<any>("get_account_status", {
      accountId: props.accountId,
    });
    watchTimeSeconds.value = status.watch_time_seconds || 0;
    taskProgress.value = status.task_progress || null;
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  fetchStatus();
  // 每 5 秒刷新一次状态
  const interval = setInterval(fetchStatus, 5000);
  return () => clearInterval(interval);
});

watch(() => props.running, (newVal) => {
  if (newVal) {
    fetchStatus();
  }
});

const watchTimeFormatted = computed(() => {
  const hours = Math.floor(watchTimeSeconds.value / 3600);
  const minutes = Math.floor((watchTimeSeconds.value % 3600) / 60);
  const seconds = watchTimeSeconds.value % 60;
  return `${hours.toString().padStart(2, "0")}:${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
});

const progressPercent = computed(() => {
  if (!taskProgress.value) return 0;
  const { progress, target } = taskProgress.value;
  if (target <= 0) return 0;
  return Math.min(100, Math.round((progress / target) * 100));
});

import { computed } from "vue";
</script>

<template>
  <Card>
    <CardHeader class="pb-3">
      <div class="flex items-center justify-between">
        <CardTitle class="text-sm">账号状态</CardTitle>
        <Badge :variant="running ? 'default' : 'secondary'">
          {{ running ? "运行中" : "已停止" }}
        </Badge>
      </div>
    </CardHeader>
    <CardContent class="pt-0">
      <div class="space-y-4">
        <!-- 观看时间 -->
        <div class="flex items-center justify-between text-sm">
          <span class="text-muted-foreground">观看时间</span>
          <span class="font-mono font-medium">{{ watchTimeFormatted }}</span>
        </div>

        <Separator />

        <!-- 任务进度 -->
        <div v-if="taskProgress" class="space-y-2">
          <div class="flex items-center justify-between text-sm">
            <span class="font-medium">{{ taskProgress.title }}</span>
            <span class="text-muted-foreground">
              {{ taskProgress.progress }} / {{ taskProgress.target }}
            </span>
          </div>
          <div class="h-2 w-full rounded-full bg-muted">
            <div
              class="h-full rounded-full bg-primary transition-all"
              :style="{ width: `${progressPercent}%` }"
            />
          </div>
          
          <!-- 奖励列表 -->
          <div v-if="taskProgress.rewards?.length > 0" class="flex flex-wrap gap-2 pt-2">
            <div
              v-for="reward in taskProgress.rewards"
              :key="reward.name"
              class="flex items-center gap-1 rounded-md border border-border bg-muted/50 px-2 py-1 text-xs"
            >
              <span>{{ reward.name }}</span>
              <span class="text-muted-foreground">x{{ reward.count }}</span>
            </div>
          </div>
        </div>
        <div v-else class="py-4 text-center text-sm text-muted-foreground">
          暂无任务进度
        </div>

        <!-- 操作按钮 -->
        <div class="flex gap-2">
          <Button
            v-if="!running"
            size="sm"
            class="flex-1"
            @click="emit('start', accountId)"
          >
            启动
          </Button>
          <Button
            v-else
            size="sm"
            variant="destructive"
            class="flex-1"
            @click="emit('stop', accountId)"
          >
            停止
          </Button>
          <Button
            size="sm"
            variant="outline"
            @click="emit('refresh', accountId)"
          >
            刷新任务
          </Button>
        </div>
      </div>
    </CardContent>
  </Card>
</template>

<script lang="ts">
export default {
  emits: ["start", "stop", "refresh"],
};
</script>
