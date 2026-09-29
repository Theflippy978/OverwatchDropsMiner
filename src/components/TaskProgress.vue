<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useConfigStore } from "@/stores/config";

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

interface RefreshTasksResult {
  tasks: TaskItem[];
  text: string;
}

interface ClaimRewardsResult {
  success: boolean;
  results: Array<{
    task_id: string;
    reward_name: string;
    success: boolean;
    skipped: boolean;
    message: string;
  }>;
  text: string;
}

const props = defineProps<{
  accountId: string;
  running: boolean;
}>();

const tasks = ref<TaskItem[]>([]);
const statusText = ref("");
const watchTimeSeconds = ref(0);
const refreshing = ref(false);
const claiming = ref(false);
const actionError = ref("");

const configStore = useConfigStore();
// 已自动领取过的任务 ID（对齐原 _auto_claim_handled_ids：防领取后状态
// 未及时刷新造成的重复触发；成功/已领取的记录，失败的下次重试）
const autoClaimHandled = new Set<string>();

let statusTimer: number | null = null;
let autoRefreshTimer: number | null = null;

const AUTO_REFRESH_INTERVAL = 30_000;

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

function statusClass(status: string) {
  if (status === "已完成" || status === "已领取") return "bg-green-500/10 text-green-500";
  if (status === "进行中") return "bg-blue-500/10 text-blue-500";
  return "bg-muted text-muted-foreground";
}

async function handleRefresh() {
  if (refreshing.value) return;
  refreshing.value = true;
  actionError.value = "";
  try {
    const result = await invoke<RefreshTasksResult>("refresh_tasks", {
      accountId: props.accountId,
    });
    tasks.value = result.tasks;
    statusText.value = result.text;
    maybeAutoClaim();
  } catch (e) {
    actionError.value = `刷新任务失败: ${e}`;
  } finally {
    refreshing.value = false;
  }
}

// 对齐原 task_controller.refresh 的自动领取触发：开关开启时，
// 刷新后存在"已完成且未处理"的任务即自动领取
function maybeAutoClaim() {
  if (!configStore.config.auto_claim_rewards) return;
  if (claiming.value) return;
  const pendingClaim = tasks.value.some(
    (t) => t.status === "已完成" && !autoClaimHandled.has(t.task_id.trim())
  );
  if (!pendingClaim) return;
  statusText.value = "检测到任务完成，正在自动领取奖励...";
  void handleClaim(true);
}

async function handleClaim(automatic = false) {
  if (claiming.value) return;
  claiming.value = true;
  actionError.value = "";
  try {
    const result = await invoke<ClaimRewardsResult>("claim_rewards", {
      accountId: props.accountId,
    });
    for (const item of result.results) {
      if ((item.success || item.skipped) && item.task_id.trim()) {
        autoClaimHandled.add(item.task_id.trim());
      }
    }
    statusText.value =
      (automatic ? "自动领取\n" : "") + result.text;
    if (result.results.length > 0) {
      await handleRefresh();
    }
  } catch (e) {
    actionError.value = `${automatic ? "自动领取" : "领取奖励"}失败: ${e}`;
  } finally {
    claiming.value = false;
  }
}

async function fetchStatus() {
  try {
    const status = await invoke<{ watch_time_seconds: number }>(
      "get_account_status",
      { accountId: props.accountId }
    );
    watchTimeSeconds.value = status.watch_time_seconds;
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

// 对齐原 GUI _schedule_task_refresh：账号运行中每 30s 自动刷新任务进度，
// 无运行账号则不重排定时器。
function syncAutoRefresh() {
  stopAutoRefresh();
  if (props.running && props.accountId) {
    autoRefreshTimer = window.setInterval(() => {
      void handleRefresh();
    }, AUTO_REFRESH_INTERVAL);
  }
}

function stopAutoRefresh() {
  if (autoRefreshTimer) {
    clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
  }
}

watch(
  () => props.accountId,
  () => {
    tasks.value = [];
    statusText.value = "";
    actionError.value = "";
    autoClaimHandled.clear();
    startStatusTimer();
    syncAutoRefresh();
    void handleRefresh();
  }
);

watch(
  () => props.running,
  (running) => {
    if (running) startStatusTimer();
    syncAutoRefresh();
  }
);

onMounted(() => {
  startStatusTimer();
  syncAutoRefresh();
  void handleRefresh();
});

onUnmounted(() => {
  stopStatusTimer();
  stopAutoRefresh();
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
        <!-- 观看时间 -->
        <div class="flex items-center justify-between text-sm">
          <span class="text-muted-foreground">观看时间</span>
          <span class="font-mono font-medium">{{ watchTimeFormatted }}</span>
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
