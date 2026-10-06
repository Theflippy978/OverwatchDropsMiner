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
import { useTimedNotice } from "@/lib/notice";
import { TASK_STATUS_CLAIMED } from "@/lib/types";
import { textProgressBar } from "@/lib/progress";
import type { CheckPoint, TaskItem } from "@/lib/types";

/** 时长任务标题正则：与后端 `browser/task_presenter.py` 的 DURATION_TASK_RE 同源。
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
  taskIdsKey: "",
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
const refreshing = computed(() => accountTasks.value.refreshing);
const claiming = computed(() => accountTasks.value.claiming);

/** 后端任务错误（刷新任务失败、领取失败等）。
    原本是 `computed(() => accountTasks.value.error)`，纯派生、无清除时机，
    需求是「3 秒后自动消失」，所以改成以 store 的错误为**触发源**、
    由本地定时提示负责展示（见下方 storeError 的 watch）。 */
const {
  text: actionError,
  show: showActionError,
  clear: clearActionError,
} = useTimedNotice();

const statusLine = ref("");
const progressPercent = ref(0);
const loginInvalidated = ref(false);
const { text: statusError, show: showStatusError } = useTimedNotice();
const { text: claimHint, show: showClaimHint } = useTimedNotice();

let statusTimer: number | null = null;
/** in-flight 守卫：定时器在慢响应未回时再次触发会并发两个
    get_account_status（后端无短超时），迟到响应乱序覆盖显示。 */
let statusFetching = false;
/** 在途期间又有人要状态（手动刷新 / 轮询 tick / 1s 定时器）。
    原实现是「在途就直接 return」—— 1s 定时器几乎永远占着 in-flight，
    手动刷新的那次请求因此被静默丢弃，顶部四字段与掉宝进度条停留在上一次
    的结果，用户看到的就是「点了手动刷新没反应」。改为记一个待办，
    由在途那次在 finally 里续跑一次：永不丢请求，也不会并发。 */
let statusStale = false;
let statusFailures = 0;

const hasTasks = computed(() => tasks.value.length > 0);

/** 后端状态行的占位文案（无账号时），四段结构须与有账号时一致 */
const STATUS_PLACEHOLDER =
  "状态: 已暂停 | 有效观看(B站): -- | 本地连接: -- | 预计剩余: --";

/**
 * 把后端返回的单行状态拆成字段块渲染。
 *
 * 后端 format_watch_status_line 返回「A | B | C | D」四段挤在一行，
 * 靠空格对齐、字号一致，扫读时无法快速定位「我关心的那一段」。
 * 这里按分隔符拆开各占一格 —— 纯前端改动，不动后端契约。
 */
const statusSegments = computed(() => {
  const raw = statusLine.value || STATUS_PLACEHOLDER;
  return raw
    .split("|")
    .map((s) => s.trim())
    .filter(Boolean);
});

/** 「掉宝进度」是唯一的整体指标，单独强调；其余三段是参考值 */
const STATUS_PRIMARY = "状态";

/** 领取按钮不可用的原因（做成 title 提示，避免点了没反应） */
const actionBlockReason = computed(() => {
  if (!props.accountId) return "请先在左侧选择账号";
  if (!configStore.config.task_ids_text) return "请先填写或自动获取任务 ID";
  if (!hasTasks.value) return "暂无任务进度，请先「手动刷新」";
  return "";
});

/**
 * 领取中的按钮文案。
 *
 * 必须写明预期时长：后端要串行领取每个检查点（限频 1.2s + 退避
 * 0/1.5/3.0s + WBI 签名），单个账号可能耗时数十秒。用户看到「领取中…」
 * 却不知道要等多久，会反复点击，每次点击都会排一轮新的领取
 * （tasksStore 的 claimQueued 只留一个布尔，不会合并）。
 */
const claimButtonText = computed(() =>
  claiming.value ? "领取中，可能需十几秒" : "领取奖励",
);

// 文案沿用 Qt 时代的「备注（挂宝中）/ 备注（待机）」形态
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

/** 检查点进度百分比。limit_value 为 0 时返回 0，避免除零得到 NaN
    —— NaN 会被模板渲染成「NaN%」，而后台不报错。 */
function percentOfCheckpoint(cp: CheckPoint) {
  if (cp.limit_value <= 0) return 0;
  return Math.min(100, Math.round((cp.cur_value / cp.limit_value) * 100));
}

/** 进度条的已填充段（`#`），宽度与后端 BAR_WIDTH 同源 */
function barFilled(cp: CheckPoint) {
  return textProgressBar(percentOfCheckpoint(cp)).filled;
}

/** 进度条的未填充段（`-`）。与已填充段拆开是为了分别上色。 */
function barEmpty(cp: CheckPoint) {
  return textProgressBar(percentOfCheckpoint(cp)).empty;
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

/**
 * 检查点状态胶囊的文案。
 *
 * 「已领取」有两个来源，必须都认：
 * 1. 服务端 status 为 TASK_STATUS_CLAIMED；
 * 2. 本会话领取成功（handledIds 里有它）。B站接口对已领检查点仍可能
 *    返回「已完成」，sidecar 也不缓存检查点状态，所以只看服务端字段时，
 *    用户刚领完奖励刷新一下又变回「已完成」。
 *
 * handledIds 是本会话的权威集合，与服务端字段取并集而不是互相覆盖。
 */
function checkPointStatus(cp: CheckPoint): string {
  if (
    cp.status === TASK_STATUS_CLAIMED ||
    accountTasks.value.handledIds.has(cp.sid)
  ) {
    return "已领取";
  }
  if (cp.is_completed) return "已完成";
  return "进行中";
}

function checkPointStatusClass(cp: CheckPoint): string {
  if (
    cp.status === TASK_STATUS_CLAIMED ||
    accountTasks.value.handledIds.has(cp.sid) ||
    cp.is_completed
  ) {
    return "bg-signal-success/10 text-signal-success";
  }
  return "bg-signal-info/10 text-signal-info";
}

interface DurationTaskGroup {
  prefix: string;
  currentMinutes: number;
  targetMinutes: number;
  checkpoints: CheckPoint[];
}

/** 合成检查点：任务没有 check_points 时的回落。
    status 必须从任务级文案映射，不能固定 0 —— 否则「已领取」任务
    在聚合行里会被渲染成「进行中」。 */
function synthesizedCheckpoint(task: TaskItem): CheckPoint {
  return {
    sid: task.task_id,
    alias: task.title,
    status: task.status === "已领取" ? TASK_STATUS_CLAIMED : 0,
    is_completed: task.status === "已完成" || task.status === "已领取",
    cur_value: task.progress,
    limit_value: task.target,
    award_name: "",
    award_count: 0,
  };
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
      // browser/task_presenter.py 的 max(cur_value)），不是从标题解析出的目标值。
      // 原实现用 Math.max(currentMinutes, minutes)，而 minutes 与 prefix 同源，
      // 是恒等运算 —— 渲染结果永远是「(当前: 60 分钟)」的标题复读，
      // 且与后端 text 里的同一行互相矛盾。
      for (const cp of task.check_points) {
        groups[key].currentMinutes = Math.max(groups[key].currentMinutes, cp.cur_value);
      }
    } else {
      groups[key].checkpoints.push(synthesizedCheckpoint(task));
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
  // 必须 await 到「含排队轮」真正结束：顶部四个字段与掉宝进度条只由
  // fetchStatus 更新，不走 refreshTasks，不等它就会拿旧数据去同步，
  // 表现为「点了手动刷新，下面的进度一动不动」。
  await tasksStore.refreshTasks(props.accountId);
  await fetchStatus();
}

async function handleClaim() {
  if (!props.accountId) return;
  if (!configStore.config.task_ids_text) {
    showClaimHint("请先填写或自动获取任务 ID");
    return;
  }
  await tasksStore.claimRewards(props.accountId, false);
}

async function fetchStatus() {
  const accountId = props.accountId;
  if (!accountId) return;
  if (statusFetching) {
    // 已在途：记下「还要再来一次」，由在途那次收尾时续跑。
    statusStale = true;
    return;
  }
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
  } catch {
    // 状态查询失败：保留上次数据，但累计失败后给出降级提示
    if (props.accountId !== accountId) return;
    statusFailures += 1;
    if (statusFailures === 3) {
      showStatusError("状态查询连续失败，可能账号已被外部删除");
    }
  } finally {
    statusFetching = false;
    if (statusStale) {
      statusStale = false;
      void fetchStatus();
    }
  }
}

/** 本会话已领取的检查点 ID 变化时不必重建任务列表：
    该集合只影响状态胶囊文案，而胶囊由 checkPointStatus 在渲染时
    现算，不缓存成模板数据，所以无需任何 watch。 */

/**
 * store 侧的任务错误：只作为「该提示一次」的触发源。
 *
 * 不能直接在模板里渲染它 —— 那是派生值，store 什么时候清空不受前端控制，
 * 而需求是 3 秒后自动消失。每当它变成非空就把文案搬进本地定时提示；
 * 同一文案在 store 里没变化时不重复提示（用户已经看过一次）。
 */
const storeError = computed(() => accountTasks.value.error || "");

watch(storeError, (message) => {
  if (message) showActionError(message, true);
});

/** 状态刷新周期：1s。
 *
 * 原本跟随「任务查询间隔」（10~3600s，默认 30s），但该配置的含义是
 * 「多久向 B站查一次任务进度」，而 get_account_status 读的是本地计时器
 * 与缓存值，不产生任何外部请求。本地连接时长因此以分钟为粒度跳动，
 * 看上去像卡住了。
 *
 * 固定 1s 而不是两个定时器：四条字段共用同一份响应，增量没有意义，
 * 多一个定时器只会多一次 IPC 往返。
 */
const STATUS_REFRESH_INTERVAL_MS = 1000;

function startStatusTimer() {
  stopStatusTimer();
  // 未运行的账号不轮询（mount 路径此前绕过了 running 判定）
  if (!props.accountId || !props.running) return;
  void fetchStatus();
  statusTimer = window.setInterval(() => {
    void fetchStatus();
  }, STATUS_REFRESH_INTERVAL_MS);
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
  statusFailures = 0;
  // 换账号/停止时把上一个账号留下的行内提示一并收掉：
  // store 里的任务错误可能还是旧账号的，而本地提示是定时显示的，
  // 不清的话用户会看到「A 账号的失败原因」挂在 B 账号的卡上。
  clearActionError();
  // 换账号/停止时把「还要再刷一次」的待办一并丢弃：它属于上一个账号，
  // 带到新账号上会打一次多余的请求并可能覆盖刚设置的状态。
  statusStale = false;
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
      // 启动挂宝后立刻刷一次任务进度：启动前的任务列表是上一次运行残留的
      // （甚至是昨天的任务 ID），用户点下「启动」后第一眼看到的进度条与
      // 胶囊必须属于本次运行，否则会以为配置没生效。
      void handleRefresh();
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
  <!-- 卡片内边距 18/12/18/14、间距 8px，对齐 Qt 时代的进度面板。

       overflow-hidden 已移除：它是为了「让本卡在右列 grid 里可被压缩」而加的，
       代价是把下方任务展示区的下限也一并压掉 —— 日志一展开，6 个检查点只剩 2 个。
       现在任务区贴合内容（见下方任务展示区注释），卡片高度 = 内容高度，
       窗口有富余高度时由右列让给日志卡下方。

       卡片内部那两个 min-h-0 不是可选优化，见 CardContent 处的长注释：
       没有它们，「内容高度逐环上传」会让卡片高度被内容顶高、无法由内容决定。 -->
  <Card class="flex flex-col">
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
          {{ claimButtonText }}
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
    <!-- min-h-0（CardContent + 内层容器）不是可选优化。
         flex 项目的 `min-height: auto` 会解析成**内容高度**，
         于是「CardContent → 内层 flex 列 → 任务区」这条链上的每一环都把
         下面的内容高度当成自己的下限（实测：任务区内容 335px → 内层下限 452
         → CardContent 下限 466），卡片被压到 411 时内容直接溢出。
         显式 `min-height: 0` 把这条链断开，卡片的高度才只由内容决定。

         这两个 min-h-0 现在是「高度由内容决定」的必要条件而非内部滚动的必要条件：
         任务区已不再有 flex-1（见下方任务展示区注释），卡片高度 = 各部分内容
         高度之和，多出来的窗口高度由右列的 align-content: start 让给日志卡下方。 -->
    <CardContent class="flex min-h-0 flex-1 flex-col px-[18px] pb-3.5 pt-0">
      <div class="flex min-h-0 flex-1 flex-col gap-3">
        <!-- 状态行：后端 format_watch_status_line 返回「A | B | C | D」四段，
             这里按 | 拆成字段格渲染（见 statusSegments）。
             占位文案必须与后端四段结构一致：原实现在无账号分支用了
             已废弃的「本次有效观看」三段式，与有账号时字段结构不一致。
             刻意不加 title：整行文字已在四个格子里可见，悬浮重复一遍
             只会遮挡内容（需求 21）。 -->
        <div
          class="grid grid-cols-2 gap-1.5 sm:grid-cols-4"
        >
          <div
            v-for="(seg, i) in statusSegments"
            :key="i"
            class="rounded-md border border-border/70 bg-muted/40 px-2.5 py-1.5"
            :class="seg.startsWith(STATUS_PRIMARY) ? 'col-span-2 sm:col-span-1' : ''"
          >
            <!-- 段内形如「状态: 已暂停」，冒号前是字段名、后跟值 -->
            <span class="block text-[11px] leading-tight text-muted-foreground">
              {{ seg.split(":")[0] }}
            </span>
            <span
              class="block truncate text-sm font-medium tabular-nums leading-tight"
              :class="seg.startsWith(STATUS_PRIMARY) ? 'text-foreground' : 'text-muted-foreground'"
            >
              {{ seg.split(":").slice(1).join(":") || "--" }}
            </span>
          </div>
        </div>
        <p v-if="statusError" class="text-xs text-signal-danger" role="alert">
          {{ statusError }}
        </p>
        <p v-if="claimHint" class="text-xs text-signal-warning" role="alert">
          {{ claimHint }}
        </p>

        <!-- 掉宝进度（对齐 Qt 时代：20px、内部文字、始终显示）

             文字必须渲染**两遍**，这是唯一能同时保证「填充段」与「未填充段」
             都可读的写法（100% 时单层文字与 bg-primary 同色，
             浅色主题下整条变成黑底黑字，完全看不见）：
               底层 text-primary-foreground 铺满，压在填充上可读
                     （浅色：近白字压近黑填充；深色：近黑字压近白填充，两向都 ≥17:1）
               上层同文案 text-foreground，用 clip-path 只保留右侧未填充段
             上下两层同速过渡，文字不会「先变色再跟进度」。
             role="progressbar" 会让子节点对读屏呈 presentational，
             两份文案不会被念两遍。 -->
        <div
          class="relative h-5 w-full shrink-0 overflow-hidden rounded-lg border border-border bg-secondary"
          role="progressbar"
          aria-label="掉宝进度"
          aria-valuemin="0"
          aria-valuemax="100"
          :aria-valuenow="progressPercent"
        >
          <div
            class="h-full bg-primary transition-[width] duration-[var(--duration-slow)] ease-[var(--ease-inout)]"
            :style="{ width: `${progressPercent}%` }"
          />
          <span
            class="absolute inset-0 flex items-center justify-center px-2.5 text-xs font-semibold text-primary-foreground"
          >
            掉宝进度 {{ progressPercent }}%
          </span>
          <span
            class="absolute inset-0 flex items-center justify-center px-2.5 text-xs font-semibold text-foreground transition-[clip-path] duration-[var(--duration-slow)] ease-[var(--ease-inout)]"
            :style="{ clipPath: `inset(0 0 0 ${progressPercent}%)` }"
          >
            掉宝进度 {{ progressPercent }}%
          </span>
        </div>

        <!-- 任务展示区：**贴合内容**，不吸收任何多余高度。

             为什么不能有 `flex-1`：右列 grid 原本给本卡一行
             `minmax(364px, 1fr)`，剩下的高度全被 `flex-1` 的任务区吃掉，
             检查点只有 6 行时列表底部多出 40~60px 空白。那段空白是
             **拉伸出来的**，不是内容高度 —— 所以把 min-h 从 220 一路降到 190
             对它一点作用都没有（用户连着两轮报「还是有很大的间距」）。
             现在右列三行全部按内容取高（见 App.vue 那一行的
             `grid-rows-[auto_auto_auto] content-start`），本区不再有
             `flex-1`，高度富余时落在日志卡下方。

             min-h-[170px] 只在内容不足时起作用：一组时长任务典型是
             6 个检查点（B站「观看直播」当前 60/120/240/360/360/600 分共 6 条），
             逐行算下来约 180px，所以 6 个检查点时 min-h 不生效、零空白；
             少于 6 个时面板仍有 170px 保底，不会缩成一条缝。

             overflow-y-auto 现在不会真的触发（没有高度上限就不产生溢出），
             保留它是无害的双保险：将来若给本区加 max-height，内部滚动立刻可用。
             检查点非常多时改为由右列统一滚动，这与「展开日志时日志向下伸出
             视口下半部分、靠滚轮下翻」是同一套机制。 -->
        <div class="scroll-subtle min-h-[170px] overflow-y-auto rounded-md border border-input bg-input/40 p-2">
          <div v-if="hasTasks" class="space-y-3">
          <!-- 时长任务聚合 -->
          <div v-if="hasDurationTasks(tasks)" class="space-y-2">
            <div v-for="(group, index) in groupDurationTasks(tasks)" :key="group.prefix" class="space-y-1">
              <div class="text-sm font-medium">
                {{ index + 1 }}. {{ group.prefix }} (当前: {{ group.currentMinutes }} 分钟)
              </div>
              <!-- 检查点用左侧竖线表达层级：比 pl-4 缩进更明确，
                   且不与任务名的悬挂缩进混淆 -->
              <div class="space-y-1 border-l-2 border-border pl-3">
                <!-- 检查点单行三段：左=总时间+任务ID，中=文字进度条+##/##+百分比，
                     右=状态+奖励。

                     三段全部**固定列宽**。此前第 2、3 段用
                     `auto` / `1fr`：宽度由内容决定，于是「60/60」比「360/360」
                     窄 21px、「已完成」比「已领取」宽，同一份数据在不同行之间
                     完全对不上竖线，扫读时每行都得重新找位置。

                     中段用 `minmax(240px, 1fr)` 而不是 `1fr`/`minmax(0,1fr)`：
                     1fr 让中段在左右两段之间居中，内部三列
                     （进度条 auto / ##/## 定宽 / 百分比定宽）保证每行内部对齐。
                     进度条列写 auto 而不是写死 px：它是 22 个等宽字符
                     （`[####################]`，宽度恒定），内容宽度即精确宽度，
                     写死 px 反而会在字体回退时与实际渲染脱节。
                     **下限必须写死 240px**：写 minmax(0,1fr) 时这一列能被压到
                     237px 以下，里面的 min-w-max 组并不撑开轨道（轨道下限是 0），
                     而是居中溢出 —— 左右各压 18px 到相邻列上，
                      与「可压缩容器装不可压缩内容」是同一种病，
                      而且因为是居中溢出，scrollWidth 都不变，扫描器查不出来。 -->
                <div
                  v-for="cp in [...group.checkpoints].sort((a, b) => a.limit_value - b.limit_value)"
                  :key="cp.sid"
                  class="grid grid-cols-[72px_minmax(240px,1fr)_auto] items-center gap-x-2 gap-y-0.5 py-0.5 text-xs"
                >
                  <div class="flex w-[72px] shrink-0 items-center gap-1.5">
                    <span class="font-medium tabular-nums text-foreground">
                      {{ cp.limit_value }}分
                    </span>
                    <span
                      class="font-mono text-[11px] text-muted-foreground"
                      :title="cp.sid"
                    >
                      {{ cp.sid.slice(-4) }}
                    </span>
                  </div>
                  <div class="flex min-w-0 items-center justify-center">
                    <!-- 文字进度条整条都是灰阶：`#` 与后面的「60/60」「100%」
                         同为 text-muted-foreground，未填充的 `-` 再淡一档
                         （muted-foreground/50）。此前 `#` 用 signal-info 蓝，
                         蓝色进度条夹在两串灰数字中间会显得是另一个控件，
                         而这一行的进度数字就在它右边 60px 处 —— 用户要的是
                         「进度条和它的数字读起来是一件事」。
                         填充/未填充的区分改由 `#` 与 `-` 的字形本身承担。
                         两处形态（时长任务组 / 普通任务）必须一致。 -->
                    <div class="grid min-w-max grid-cols-[auto_64px_36px] items-center gap-2">
                      <span class="font-mono text-[11px] leading-none tracking-tighter">
                        <span class="text-muted-foreground/70">[</span><span class="text-muted-foreground">{{ barFilled(cp) }}</span><span class="text-muted-foreground/50">{{ barEmpty(cp) }}</span><span class="text-muted-foreground/70">]</span>
                      </span>
                      <span class="text-right tabular-nums text-muted-foreground">
                        {{ cp.cur_value }}/{{ cp.limit_value }}
                      </span>
                      <span class="text-right tabular-nums text-muted-foreground">
                        {{ percentOfCheckpoint(cp) }}%
                      </span>
                    </div>
                  </div>
                  <div class="flex shrink-0 items-center justify-end gap-1.5">
                    <span
                      class="shrink-0 rounded-full px-1.5 py-0.5 text-[11px] font-medium"
                      :class="checkPointStatusClass(cp)"
                    >
                      {{ checkPointStatus(cp) }}
                    </span>
                    <!-- 奖励名固定预留 8 个汉字（96px @text-xs）+ 「×N」16px。
                         此前没有宽度约束，`truncate` 在 grid 的 auto 列里
                         实际不生效（列宽由内容撑开），奖励名一长就把整行
                         顶宽、把中段的百分比挤出可视区。
                         min-w-0 挂在名字上而不是外层：外层是 shrink-0 的
                         定宽盒子，截断必须发生在名字本身。 -->
                    <span
                      v-if="cp.award_name"
                      class="flex w-28 shrink-0 items-baseline gap-0.5"
                      :title="`${cp.award_name} ×${cp.award_count}`"
                    >
                      <span class="min-w-0 flex-1 truncate text-muted-foreground">
                        {{ cp.award_name }}
                      </span>
                      <span class="shrink-0 text-muted-foreground">×{{ cp.award_count }}</span>
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 普通任务列表（过滤掉已被时长分组消费的任务） -->
          <div
            v-for="task in tasks.filter(t => !DURATION_TASK_RE.test(t.title))"
            :key="task.task_id"
            class="rounded-md border border-border/60 bg-background/40 p-2"
          >
            <div class="flex items-baseline justify-between gap-2">
              <span class="text-sm font-medium leading-snug">{{ task.title }}</span>
              <div class="flex shrink-0 items-baseline gap-2">
                <!-- tabular-nums：进度数字位数变化时不会左右抖动 -->
                <span class="text-xs tabular-nums text-muted-foreground">
                  {{ task.progress }} / {{ task.target }}
                </span>
                <span
                  class="rounded-full px-1.5 py-0.5 text-[11px] font-medium"
                  :class="statusClass(task.status)"
                >
                  {{ task.status }}
                </span>
              </div>
            </div>
            <Progress :value="percentOf(task)" class="mt-1.5 h-1.5" />

            <!-- 检查点明细：与时长任务组的胶囊行**逐列同宽**。
                 第 1 列是别名（可长、可截断），所以是 1fr；
                 第 2、3 列的内部结构与列宽和上面完全一致，
                 两处形态必须一模一样，否则时长任务与普通任务的检查点
                 在同一张卡里会呈现两套对齐基准。 -->
            <div v-if="shouldShowCheckPoints(task)" class="mt-2 space-y-1 border-l-2 border-border pl-3">
              <div
                v-for="cp in task.check_points"
                :key="cp.sid"
                class="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-x-2 gap-y-0.5 text-xs"
              >
                <span class="truncate text-muted-foreground">{{ cp.alias }}</span>
                <div class="flex min-w-0 items-center justify-center">
                  <div class="grid min-w-max grid-cols-[auto_64px_36px] items-center gap-2">
                    <span class="font-mono text-[11px] leading-none tracking-tighter">
                      <span class="text-muted-foreground/70">[</span><span class="text-muted-foreground">{{ barFilled(cp) }}</span><span class="text-muted-foreground/50">{{ barEmpty(cp) }}</span><span class="text-muted-foreground/70">]</span>
                    </span>
                    <span class="text-right tabular-nums text-muted-foreground">
                      {{ cp.cur_value }}/{{ cp.limit_value }}
                    </span>
                    <span class="text-right tabular-nums text-muted-foreground">
                      {{ percentOfCheckpoint(cp) }}%
                    </span>
                  </div>
                </div>
                <div class="flex shrink-0 items-center justify-end gap-1.5">
                  <span
                    class="shrink-0 rounded-full px-1.5 py-0.5 text-[11px] font-medium"
                    :class="checkPointStatusClass(cp)"
                  >
                    {{ checkPointStatus(cp) }}
                  </span>
                  <span
                    v-if="cp.award_name"
                    class="flex w-28 shrink-0 items-baseline gap-0.5"
                    :title="`${cp.award_name} ×${cp.award_count}`"
                  >
                    <span class="min-w-0 flex-1 truncate text-muted-foreground">
                      {{ cp.award_name }}
                    </span>
                    <span class="shrink-0 text-muted-foreground">×{{ cp.award_count }}</span>
                  </span>
                </div>
              </div>
            </div>

            <!-- 奖励：扁平 chip 而非带边框的盒子，减少嵌套层级 -->
            <div
              v-if="task.rewards.length > 0"
              class="mt-2 flex flex-wrap gap-1.5 border-l-2 border-border pl-3"
            >
              <span
                v-for="reward in task.rewards"
                :key="reward.name"
                class="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground"
              >
                {{ reward.name }} ×{{ reward.count }}
              </span>
            </div>
          </div>
        </div>
          <div v-else class="py-4 text-center text-sm text-muted-foreground">
            {{ !accountId ? "请先在左侧选择账号" : (refreshing ? "正在查询任务进度..." : "暂无任务进度，点击\"手动刷新\"") }}
          </div>
        </div>

        <!-- 后端错误。正常态的文本化进度不再显示：它的全部信息（时长、
             已看时长、进度、状态）已并入上方胶囊，重复一份只会让
             用户对着两处数字核对，且两处来源不同容易不一致。 -->
        <p
          v-if="actionError"
          class="whitespace-pre-wrap break-all font-mono text-xs text-signal-danger"
          role="alert"
        >
          {{ actionError }}
        </p>
      </div>
    </CardContent>
  </Card>
</template>
