<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from "vue";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { useTasksStore } from "@/stores/tasks";
import { useAccountsStore } from "@/stores/accounts";
import { useConfigStore } from "@/stores/config";
import type { CheckPoint, TaskItem } from "@/lib/types";

/** 时长任务标题正则：与后端 task_presenter.py:63 的 DURATION_TASK_RE 同源。
    后端用宽松前缀 ^(.+?)\d+分钟$，此处必须同样宽松，
    否则「累计观看60分钟」这类标题后端会成组、前端当普通任务，两边形态不一致。 */
const DURATION_TASK_RE = /^.+?\d+分钟$/;

/** 未选中账号时的空任务集（模块级常量，避免每次求值建新对象） */
const EMPTY_TASKS = {
  tasks: [] as TaskItem[],
  text: "",
  error: "",
  cur: 0,
  limit: 0,
  handledIds: new Set<string>(),
  pendingIds: new Set<string>(),
  refreshing: false,
  refreshQueued: false,
  queuedManual: false,
  claiming: false,
  claimQueued: false,
} as const;

const props = defineProps<{
  accountId: string | null;
  running: boolean;
  remark: string;
}>();

const tasksStore = useTasksStore();
const accountsStore = useAccountsStore();
const configStore = useConfigStore();
// 未选中账号时用空串键取空任务集（对齐旧版：挂宝进度卡常驻，未选择显示占位）。
// 必须用纯读路径 peekAccountTasks：getAccountTasks 会在 computed 求值期间写
// accountTasksMap，导致渲染期副作用与多余的重新求值。
const accountTasks = computed(
  () => tasksStore.peekAccountTasks(props.accountId ?? "") ?? EMPTY_TASKS,
);

const tasks = computed(() => accountTasks.value.tasks);
const statusText = computed(() => accountTasks.value.text);
const actionError = computed(() => accountTasks.value.error);
const refreshing = computed(() => accountTasks.value.refreshing);
const claiming = computed(() => accountTasks.value.claiming);

const statusLine = ref("");
const progressPercent = ref(0);
const loginInvalidated = ref(false);
const statusError = ref("");
const claimHint = ref("");

let statusTimer: number | null = null;
/** in-flight 守卫：setInterval 在慢响应未回时再次触发会并发两个
    get_account_status（后端无短超时），迟到响应乱序覆盖显示 */
let statusFetching = false;
let statusFailures = 0;

const hasTasks = computed(() => tasks.value.length > 0);

/** 领取按钮不可用的原因（做成 title 提示，避免点了没反应） */
const actionBlockReason = computed(() => {
  if (!props.accountId) return "请先在左侧选择账号";
  if (!configStore.config.task_ids_text) return "请先填写或自动获取任务 ID";
  if (!hasTasks.value) return "暂无任务进度，请先「手动刷新」";
  return "";
});

// 旧版 main_window.py:449-451 的文案：备注（挂宝中）/ 备注（待机）
const statusBadgeText = computed(() => {
  const name = props.remark || props.accountId?.slice(0, 8) || "账号";
  if (props.running) return `${name}（挂宝中）`;
  if (loginInvalidated.value) return `${name}（Cookie 已失效）`;
  return `${name}（待机）`;
});

function percentOf(task: TaskItem) {
  if (task.target <= 0) return 0;
  return Math.min(100, Math.round((task.progress / task.target) * 100));
}

function statusClass(status: string) {
  if (status === "已完成" || status === "已领取") return "bg-signal-success/10 text-signal-success";
  if (status === "进行中") return "bg-signal-info/10 text-signal-info";
  return "bg-muted text-muted-foreground";
}

function shouldShowCheckPoints(task: TaskItem): boolean {
  const cps = task.check_points;
  if (!cps || cps.length === 0) return false;
  if (cps.length > 1) return true;
  const cp = cps[0];
  return cp.alias !== task.title || cp.cur_value !== task.progress || cp.limit_value !== task.target;
}

function checkPointStatus(cp: CheckPoint): string {
  if (cp.status === 6) return "已领取";
  if (cp.is_completed) return "已完成";
  return "进行中";
}

function checkPointStatusClass(cp: CheckPoint): string {
  if (cp.status === 6 || cp.is_completed) return "bg-signal-success/10 text-signal-success";
  return "bg-signal-info/10 text-signal-info";
}

interface DurationTaskGroup {
  prefix: string;
  currentMinutes: number;
  targetMinutes: number;
  checkpoints: CheckPoint[];
}

function groupDurationTasks(tasks: TaskItem[]): DurationTaskGroup[] {
  const groups: Record<string, DurationTaskGroup> = {};
  for (const task of tasks) {
    if (!DURATION_TASK_RE.test(task.title)) continue;
    const match = task.title.match(/(\d+)分钟$/);
    const targetMinutes = match ? parseInt(match[1], 10) : 0;
    const prefix = task.title.slice(0, task.title.length - String(targetMinutes).length - 2);
    const key = prefix || task.title;
    if (!groups[key]) {
      groups[key] = {
        prefix: key,
        currentMinutes: 0,
        targetMinutes,
        checkpoints: [],
      };
    }
    if (task.check_points && task.check_points.length > 0) {
      groups[key].checkpoints.push(...task.check_points);
      // 关键：currentMinutes 必须是真实进度（对齐后端
      // task_presenter.py:239 的 max(cur_value)），不是从标题解析出的目标值。
      // 原实现用 Math.max(currentMinutes, minutes)，而 minutes 与 prefix 同源，
      // 是恒等运算 —— 渲染结果永远是「(当前: 60 分钟)」的标题复读，
      // 且与后端 text 里的同一行互相矛盾。
      for (const cp of task.check_points) {
        groups[key].currentMinutes = Math.max(groups[key].currentMinutes, cp.cur_value);
      }
    } else {
      groups[key].checkpoints.push({
        sid: task.task_id,
        alias: task.title,
        status: 0,
        is_completed: task.status === "已完成",
        cur_value: task.progress,
        limit_value: task.target,
        award_name: "",
        award_count: 0,
      });
      groups[key].currentMinutes = Math.max(groups[key].currentMinutes, task.progress);
    }
  }
  return Object.values(groups).sort((a, b) => a.targetMinutes - b.targetMinutes);
}

function hasDurationTasks(tasks: TaskItem[]): boolean {
  return tasks.some((t) => DURATION_TASK_RE.test(t.title));
}

async function handleRefresh() {
  if (!props.accountId) return;
  // 不在前端校验 Cookie：config.cookie 由后端 _load_config 硬编码返回空串
  // （Cookie 只经账号库管理），该判断永远命中导致按钮 100% 走 alert。
  // 前置条件交由后端 _resolve_task_context 返回，错误已存入
  // tasksStore.error 并由模板显示。
  await tasksStore.refreshTasks(props.accountId);
}

async function handleClaim() {
  if (!props.accountId) return;
  if (!configStore.config.task_ids_text) {
    claimHint.value = "请先填写或自动获取任务 ID";
    return;
  }
  claimHint.value = "";
  await tasksStore.claimRewards(props.accountId, false);
}

async function fetchStatus() {
  const accountId = props.accountId;
  if (!accountId || statusFetching) return;
  statusFetching = true;
  try {
    // 走 accountsStore.getStatus 而不是自己 invoke：此前同一个 IPC 有两套
    // 前端封装（store 一份、组件内联一份），类型与错误处理会持续漂移。
    const status = await accountsStore.getStatus(accountId);
    // 身份快照：请求在途期间用户可能已切到别的账号，
    // 迟到响应会污染当前显示（旧账号的分钟数/进度出现在新账号页）
    if (props.accountId !== accountId) return;
    statusLine.value = status.status_line;
    progressPercent.value = status.progress ? status.progress.percent : 0;
    loginInvalidated.value = status.login_invalidated;
    statusError.value = "";
  } catch {
    // 状态查询失败：保留上次数据，但累计失败后给出降级提示
    if (props.accountId !== accountId) return;
    statusFailures += 1;
    if (statusFailures === 3) {
      statusError.value = "状态查询连续失败，可能账号已被外部删除";
    }
  } finally {
    statusFetching = false;
  }
}

/** 状态轮询周期：跟随「任务查询间隔」配置（下限与后端契约一致为 10s） */
function statusIntervalMs(): number {
  const parsed = parseInt(configStore.config.task_query_interval_text, 10);
  const seconds = isNaN(parsed) ? 30 : Math.max(10, Math.min(3600, parsed));
  return seconds * 1000;
}

function startStatusTimer() {
  stopStatusTimer();
  // 未运行的账号不轮询（mount 路径此前绕过了 running 判定）
  if (!props.accountId || !props.running) return;
  void fetchStatus();
  statusTimer = window.setInterval(() => {
    void fetchStatus();
  }, statusIntervalMs());
}

function stopStatusTimer() {
  if (statusTimer) {
    clearInterval(statusTimer);
    statusTimer = null;
  }
}

function clearWatchState() {
  statusLine.value = "";
  progressPercent.value = 0;
  loginInvalidated.value = false;
  statusError.value = "";
  statusFailures = 0;
}

watch(
  () => props.accountId,
  () => {
    if (!props.accountId) {
      // 取消选中/账号被删：停轮询并清空上一个账号的观看态
      stopStatusTimer();
      clearWatchState();
      return;
    }
    // 切到另一个账号时也必须清空，否则会短暂显示上一个账号的观看数据
    clearWatchState();
    startStatusTimer();
    void handleRefresh();
  }
);

watch(
  () => props.running,
  (running) => {
    if (running) {
      startStatusTimer();
    } else {
      // 停止后不再轮询，并清空观看态，避免残留上一次的进度
      stopStatusTimer();
      clearWatchState();
    }
  }
);

// 轮询周期随「任务查询间隔」变化，与 App.vue 的任务刷新共用同一个字段，
// 因此由 App.vue 统一在自身定时器里处理，这里不再重复建 watch。
onMounted(() => {
  startStatusTimer();
  void handleRefresh();
});

onUnmounted(() => {
  stopStatusTimer();
});
</script>

<template>
  <!-- 卡片内边距对齐旧版 main_layout.py:212 的 setContentsMargins(18, 12, 18, 14)、间距 8px；
       flex column + min-h-0 让内容区随窗口高度伸缩（对齐 task_card 占 stretch 1）；
       overflow-hidden 是必需的：右侧日志展开后本卡被压缩，而下方任务展示区有
       min-h-[140px] 的下限，撑破卡片会让「自动领取 / 领取奖励 / 手动刷新」
       一行溢出到日志卡上（实测按钮重叠） -->
  <Card class="flex min-h-0 flex-col overflow-hidden">
    <CardHeader class="px-[18px] pb-2 pt-3">
      <div class="flex flex-wrap items-center gap-2">
        <CardTitle class="text-[11pt] font-bold">挂宝进度</CardTitle>
        <span
          v-if="!accountId"
          class="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
        >
          未选择账号
        </span>
        <span
          v-else
          class="rounded-full px-2 py-0.5 text-xs"
          :class="running ? 'bg-signal-success/10 text-signal-success' : (loginInvalidated ? 'bg-signal-danger/10 text-signal-danger' : 'bg-muted text-muted-foreground')"
          :title="running ? '挂宝中' : (loginInvalidated ? 'Cookie 已失效' : '待机')"
        >
          {{ statusBadgeText }}
        </span>
        <div class="flex-1"></div>
        <div class="flex items-center gap-1.5">
          <Checkbox
            id="auto-claim"
            :model-value="configStore.config.auto_claim_rewards"
            aria-label="自动领取奖励"
            title="检测到任务达到 100% 后自动领取；领取失败会在后续刷新时重试"
            @update:model-value="configStore.config.auto_claim_rewards = $event === 'indeterminate' ? true : $event"
          />
          <Label for="auto-claim" class="cursor-pointer text-xs">自动领取</Label>
        </div>
        <Button
          size="sm"
          class="h-7 rounded-md px-3 text-xs"
          :disabled="claiming || !hasTasks || !accountId"
          :title="actionBlockReason"
          @click="handleClaim()"
        >
          {{ claiming ? "领取中..." : "领取奖励" }}
        </Button>
        <Button
          size="sm"
          variant="outline"
          class="h-7 rounded-md px-3 text-xs"
          :disabled="refreshing || !accountId"
          :title="!accountId ? '请先在左侧选择账号' : undefined"
          @click="handleRefresh"
        >
          {{ refreshing ? "刷新中..." : "手动刷新" }}
        </Button>
      </div>
    </CardHeader>
    <CardContent class="flex min-h-0 flex-1 flex-col px-[18px] pb-3.5 pt-0">
      <div class="flex min-h-0 flex-1 flex-col gap-3">
        <!-- 状态行：后端 format_watch_status_line 已按旧版格式返回单行
             （状态 | 有效观看(B站) | 本地连接 | 预计剩余），对齐 main_layout.py:238。
             占位文案必须与后端四段结构一致：原实现在无账号分支用了
             已废弃的「本次有效观看」三段式，与有账号时字段结构不一致。 -->
        <div class="rounded-md bg-muted/50 p-2 font-mono text-xs">
          {{ statusLine || "状态: 已暂停 | 有效观看(B站): -- | 本地连接: -- | 预计剩余: --" }}
        </div>
        <p v-if="statusError" class="text-xs text-signal-danger" role="alert">
          {{ statusError }}
        </p>
        <p v-if="claimHint" class="text-xs text-signal-warning" role="alert">
          {{ claimHint }}
        </p>

        <!-- 掉宝进度（对齐旧版 main_layout.py:243-249 + theme.py:254-259：20px、内部文字、始终显示） -->
        <div
          class="relative h-5 w-full shrink-0 overflow-hidden rounded-lg border border-border bg-secondary"
          role="progressbar"
          aria-label="掉宝进度"
          aria-valuemin="0"
          aria-valuemax="100"
          :aria-valuenow="progressPercent"
        >
          <div
            class="h-full bg-primary transition-all duration-500"
            :style="{ width: `${progressPercent}%` }"
          />
          <span class="absolute inset-0 flex items-center justify-center px-2.5 text-xs font-semibold">
            掉宝进度 {{ progressPercent }}%
          </span>
        </div>

        <!-- 任务展示区：对齐旧版 task_text（main_layout.py:251-261）min-height 140 + 随卡拉伸 + 独立滚动 -->
        <div class="min-h-[140px] flex-1 overflow-y-auto rounded-md border border-input bg-input/40 p-1.5">
          <div v-if="hasTasks" class="space-y-4">
          <!-- 时长任务聚合 -->
          <div v-if="hasDurationTasks(tasks)" class="space-y-2">
            <div v-for="(group, index) in groupDurationTasks(tasks)" :key="group.prefix" class="space-y-1">
              <div class="text-sm font-medium">
                {{ index + 1 }}. {{ group.prefix }} (当前: {{ group.currentMinutes }} 分钟)
              </div>
              <div
                v-for="cp in group.checkpoints"
                :key="cp.sid"
                class="flex items-center justify-between gap-2 text-xs pl-4"
              >
                <span class="text-muted-foreground">
                  - {{ cp.limit_value }}分 [{{ cp.sid.slice(-4) }}]
                </span>
                <div class="flex items-center gap-2">
                  <span
                    class="rounded-full px-2 py-0.5 text-xs"
                    :class="checkPointStatusClass(cp)"
                  >
                    {{ checkPointStatus(cp) }}
                  </span>
                  <span v-if="cp.award_name" class="text-muted-foreground">
                    {{ cp.award_name }} x{{ cp.award_count }}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <!-- 普通任务列表（过滤掉已被时长分组消费的任务） -->
          <div v-for="task in tasks.filter(t => !DURATION_TASK_RE.test(t.title))" :key="task.task_id" class="space-y-2">
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

            <!-- 检查点明细 -->
            <div v-if="shouldShowCheckPoints(task)" class="space-y-1 pl-2">
              <div
                v-for="cp in task.check_points"
                :key="cp.sid"
                class="flex items-center justify-between gap-2 text-xs"
              >
                <span class="text-muted-foreground">{{ cp.alias }}</span>
                <div class="flex items-center gap-2">
                  <span class="text-muted-foreground">
                    {{ cp.cur_value }} / {{ cp.limit_value }}
                  </span>
                  <span
                    class="rounded-full px-2 py-0.5 text-xs"
                    :class="checkPointStatusClass(cp)"
                  >
                    {{ checkPointStatus(cp) }}
                  </span>
                  <span v-if="cp.award_name" class="text-muted-foreground">
                    {{ cp.award_name }} x{{ cp.award_count }}
                  </span>
                </div>
              </div>
            </div>

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
            {{ !accountId ? "请先在左侧选择账号" : (refreshing ? "正在查询任务进度..." : "暂无任务进度，点击\"手动刷新\"") }}
          </div>
        </div>

        <!-- 后端格式化结果 / 错误 -->
        <p
          v-if="actionError"
          class="whitespace-pre-wrap break-all font-mono text-xs text-signal-danger"
          role="alert"
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
