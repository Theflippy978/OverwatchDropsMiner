<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useTasksStore } from "@/stores/tasks";

interface Reward {
  name: string;
  icon: string;
  count: number;
}

interface TaskItem {
  task_id: string;
  title: string;
  progress: number;
  target: number;
  status: string;
  rewards: Reward[];
}

const props = defineProps<{
  accountId: string;
  running: boolean;
}>();

const tasksStore = useTasksStore();
const accountTasks = computed(() => tasksStore.getAccountTasks(props.accountId));

const tasks = computed(() => accountTasks.value.tasks);
const statusText = computed(() => accountTasks.value.text);
const actionError = computed(() => accountTasks.value.error);
const refreshing = computed(() => accountTasks.value.refreshing);
const claiming = computed(() => accountTasks.value.claiming);

const watchTimeSeconds = ref(0);
const estimatedRemaining = ref<number | null>(null);
const statusLine = ref("");
const progressPercent = ref(0);

let statusTimer: number | null = null;

const hasTasks = computed(() => tasks.value.length > 0);

const watchTimeFormatted = computed(() => {
  const hours = Math.floor(watchTimeSeconds.value / 3600);
  const minutes = Math.floor((watchTimeSeconds.value % 3600) / 60);
  const seconds = watchTimeSeconds.value % 60;
  return `${hours.toString().padStart(2, "0")}:${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
});

function percentOf(task: TaskItem) {
  if (task.target <= 0) return 0;
  return Math.min(100, Math.round((task.progress / task.target) * 100));
}

function estimateRemaining(): number | null {
  const task = tasks.value.find((t) => t.target > 0 && t.progress < t.target);
  if (!task || watchTimeSeconds.value <= 0) return null;
  const rate = task.progress / watchTimeSeconds.value;
  if (rate <= 0) return null;
  return Math.ceil((task.target - task.progress) / rate);
}

function formatEstimatedRemaining(): string {
  if (estimatedRemaining.value === null) return "--";
  const hours = Math.floor(estimatedRemaining.value / 3600);
  const minutes = Math.floor((estimatedRemaining.value % 3600) / 60);
  const seconds = estimatedRemaining.value % 60;
  if (hours > 0) return `${hours}小时${minutes}分`;
  if (minutes > 0) return `${minutes}分${seconds}秒`;
  return `${seconds}秒`;
}

function statusClass(status: string) {
  if (status === "已完成" || status === "已领取") return "bg-green-500/10 text-green-500";
  if (status === "进行中") return "bg-blue-500/10 text-blue-500";
  return "bg-muted text-muted-foreground";
}

async function handleRefresh() {
  await tasksStore.refreshTasks(props.accountId);
}

async function handleClaim() {
  await tasksStore.claimRewards(props.accountId, false);
}

async function fetchStatus() {
  try {
    const status = await invoke<{
      watch_time_seconds: number;
      status_line: string;
      progress: { cur: number; limit: number; percent: number } | null;
    }>(
      "get_account_status",
      { accountId: props.accountId }
    );
    watchTimeSeconds.value = status.watch_time_seconds;
    statusLine.value = status.status_line;
    if (status.progress) {
      progressPercent.value = status.progress.percent;
    }
    estimatedRemaining.value = estimateRemaining();
  } catch {
    // 状态查询失败时保留上次数据
  }
}

function startStatusTimer() {
  stopStatusTimer();
  void fetchStatus();
  statusTimer = window.setInterval(() => {
    void fetchStatus();
  }, 10000);
}

function stopStatusTimer() {
  if (statusTimer) {
    clearInterval(statusTimer);
    statusTimer = null;
  }
}

watch(
  () => props.accountId,
  () => {
    startStatusTimer();
    void handleRefresh();
  }
);

watch(
  () => props.running,
  (running) => {
    if (running) startStatusTimer();
  }
);

onMounted(() => {
  startStatusTimer();
  void handleRefresh();
});

onUnmounted(() => {
  stopStatusTimer();
});
</script>

<template>
  <Card>
    <CardHeader class="pb-3">
      <div class="flex items-center justify-between gap-2">
        <CardTitle class="text-sm">任务进度</CardTitle>
        <div class="flex items-center gap-2">
          <span
            class="rounded-full px-2 py-0.5 text-xs"
            :class="running ? 'bg-green-500/10 text-green-500' : 'bg-muted text-muted-foreground'"
          >
            {{ running ? "运行中" : "已停止" }}
          </span>
          <Button
            size="sm"
            variant="outline"
            class="h-7 text-xs"
            :disabled="refreshing"
            @click="handleRefresh"
          >
            {{ refreshing ? "刷新中..." : "刷新任务" }}
          </Button>
          <Button
            size="sm"
            class="h-7 text-xs"
            :disabled="claiming || !hasTasks"
            @click="handleClaim()"
          >
            {{ claiming ? "领取中..." : "领取奖励" }}
          </Button>
        </div>
      </div>
    </CardHeader>
    <CardContent class="pt-0">
      <div class="space-y-4">
        <!-- 状态行（后端格式化） -->
        <div v-if="statusLine" class="rounded-md bg-muted/50 p-2 text-xs font-mono">
          {{ statusLine }}
        </div>

        <!-- 观看时间 -->
        <div class="flex items-center justify-between text-sm">
          <span class="text-muted-foreground">观看时间</span>
          <span class="font-mono font-medium">{{ watchTimeFormatted }}</span>
        </div>
        <div class="flex items-center justify-between text-sm">
          <span class="text-muted-foreground">预计剩余</span>
          <span class="font-mono font-medium">{{ formatEstimatedRemaining() }}</span>
        </div>

        <!-- 掉宝进度百分比 -->
        <div v-if="progressPercent > 0" class="space-y-1">
          <div class="flex items-center justify-between text-xs text-muted-foreground">
            <span>掉宝进度</span>
            <span>{{ progressPercent }}%</span>
          </div>
          <Progress :value="progressPercent" class="h-2" />
        </div>

        <Separator />

        <!-- 任务列表 -->
        <div v-if="hasTasks" class="space-y-4">
          <div v-for="task in tasks" :key="task.task_id" class="space-y-2">
            <div class="flex items-center justify-between gap-2 text-sm">
              <span class="font-medium">{{ task.title }}</span>
              <div class="flex items-center gap-2">
                <span class="text-muted-foreground">
                  {{ task.progress }} / {{ task.target }}
                </span>
                <span
                  class="rounded-full px-2 py-0.5 text-xs"
                  :class="statusClass(task.status)"
                >
                  {{ task.status }}
                </span>
              </div>
            </div>
            <Progress :value="percentOf(task)" class="h-2" />

            <!-- 奖励列表 -->
            <div v-if="task.rewards.length > 0" class="flex flex-wrap gap-2 pt-1">
              <div
                v-for="reward in task.rewards"
                :key="reward.name"
                class="flex items-center gap-1 rounded-md border border-border bg-muted/50 px-2 py-1 text-xs"
              >
                <span>{{ reward.name }}</span>
                <span class="text-muted-foreground">x{{ reward.count }}</span>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="py-4 text-center text-sm text-muted-foreground">
          {{ refreshing ? "正在查询任务进度..." : "暂无任务进度，点击\"刷新任务\"" }}
        </div>

        <!-- 后端格式化结果 / 错误 -->
        <p
          v-if="actionError"
          class="whitespace-pre-wrap break-all font-mono text-xs text-red-500"
        >
          {{ actionError }}
        </p>
        <p
          v-else-if="statusText"
          class="whitespace-pre-wrap font-mono text-xs text-muted-foreground"
        >
          {{ statusText }}
        </p>
      </div>
    </CardContent>
  </Card>
</template>
