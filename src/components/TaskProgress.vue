<script setup lang="ts">
import { computed } from "vue";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";

const props = defineProps<{
  accountId: string;
  running: boolean;
  watchTimeSeconds: number;
  taskProgress: {
    task_id: string;
    title: string;
    progress: number;
    target: number;
    status: string;
    rewards: Array<{ name: string; icon: string; count: number }>;
  } | null;
}>();

const progressPercent = computed(() => {
  if (!props.taskProgress) return 0;
  const { progress, target } = props.taskProgress;
  if (target <= 0) return 0;
  return Math.min(100, Math.round((progress / target) * 100));
});

const watchTimeFormatted = computed(() => {
  const hours = Math.floor(props.watchTimeSeconds / 3600);
  const minutes = Math.floor((props.watchTimeSeconds % 3600) / 60);
  const seconds = props.watchTimeSeconds % 60;
  return `${hours.toString().padStart(2, "0")}:${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
});
</script>

<template>
  <Card>
    <CardHeader class="pb-3">
      <div class="flex items-center justify-between">
        <CardTitle class="text-sm">任务进度</CardTitle>
        <span
          class="rounded-full px-2 py-0.5 text-xs"
          :class="running ? 'bg-green-500/10 text-green-500' : 'bg-muted text-muted-foreground'"
        >
          {{ running ? "运行中" : "已停止" }}
        </span>
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
          <Progress :value="progressPercent" class="h-2" />
          
          <!-- 奖励列表 -->
          <div v-if="taskProgress.rewards.length > 0" class="flex flex-wrap gap-2 pt-2">
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
      </div>
    </CardContent>
  </Card>
</template>
