<script setup lang="ts">
import { ref, computed, watch } from "vue";
import { useTimeoutPoll, useTransition } from "@vueuse/core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { useTasksStore } from "@/stores/tasks";
import { useAccountsStore } from "@/stores/accounts";
import { useConfigStore } from "@/stores/config";
import { useLogsStore } from "@/stores/logs";
import { useTimedNotice } from "@/lib/notice";
import { TASK_STATUS_CLAIMED } from "@/lib/types";
import { textProgressBar } from "@/lib/progress";
import {
  DURATION_TASK_RE,
  hasMeaningfulCheckPoints as shouldShowCheckPoints,
  visibleTasks,
} from "@/lib/task-view";
import type { CheckPoint, TaskItem } from "@/lib/types";

/** 未选中账号时的空任务集（模块级常量，避免每次求值建新对象） */
const EMPTY_TASKS = {
  tasks: [] as TaskItem[],
  text: "",
  hint: "",
  error: "",
  cur: 0,
  limit: 0,
  handledIds: new Set<string>(),
  pendingIds: new Set<string>(),
  refreshing: false,
  refreshQueued: false,
  refreshSettled: null,
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
const logsStore = useLogsStore();
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

/** store 侧**过程提示**的独立通道（见下方 storeHint 的 watch）。
 *
 *  **必须与 actionError 分开，不能共用一个 useTimedNotice**：共用时
 *  hint 会顶掉 error —— 实测「自动领取失败（红）」显示后，下一轮刷新写
 *  `hint="检测到任务完成，正在自动领取奖励..."` 会把它覆盖成中性色，
 *  且停留时长被从 ERROR_NOTICE_AUTO_HIDE_MS(10s) 重置为 3s。
 *  用户因此看不到真正的失败原因，而错误提示延长到 10s 本就是为了
 *  「来得及看」。
 *
 *  拆开后两条提示各自计时、互不重置；模板里按「error 优先」显示
 *  （两者都有时只显示 error），见模板中的 `actionError || actionHint`。 */
const { text: actionHint, show: showActionHint, clear: clearActionHint } = useTimedNotice();

/** 掉宝进度补间的时长与缓动。
 *
 *  **必须与 style.css 的 @theme token 保持同值**：`--duration-slow` = 400ms、
 *  `--ease-inout` = cubic-bezier(0.4, 0, 0.2, 1)。
 *  这里是 JS 补间、那边是 CSS 过渡，两者不共享变量，改一处不改另一处就会
 *  出现「填充条与文字快慢不一」—— 而没有任何测试会因此变红。
 *
 *  为什么不直接读 CSS 变量：useTransition 每帧都要这两个值，getComputedStyle
 *  触发重排，1 秒轮询下每轮都读会明显拖慢渲染。
 *  要同源就得靠 review 时对照这两处，故把对应关系写死在这条注释里。
 *  改成真同源的前提是先把 token 提到 TS 常量、再由 CSS 引用它，
 *  那是另一个改动，不值得为这两个数引入构建期耦合。 */
const PROGRESS_TWEEN_MS = 400;
const PROGRESS_TWEEN_EASING = [0.4, 0, 0.2, 1] as const;

const statusLine = ref("");
/** 后端下发的原始百分比（整数）。 */
const progressPercentRaw = ref(0);
/** 显示用的补间值。
 *
 *  掉宝进度此前是「填充条靠 CSS 过渡平滑、百分比文字瞬变」—— 同一个控件里
 *  两种节奏，数字看着像在跳。现在改成**一个补间源驱动三处**（填充条宽度、
 *  双层文字的 clip-path、百分比文本），三者天然同步，也不会出现
 *  「JS 补间 + CSS 过渡」叠加成双重缓动。 */
const progressPercent = useTransition(progressPercentRaw, {
  duration: PROGRESS_TWEEN_MS,
  transition: [...PROGRESS_TWEEN_EASING],
});
const loginInvalidated = ref(false);
const { text: statusError, show: showStatusError } = useTimedNotice();
const { text: claimHint, show: showClaimHint } = useTimedNotice();

/** in-flight 守卫：轮询与手动刷新（handleRefresh）都会调 fetchStatus，
    两者撞上时会并发两个 get_account_status（后端无短超时），迟到响应乱序
    覆盖显示。撞上时后来的那次直接落空 —— 轮询周期只有 1s，下一次必然覆盖，
    不会出现「点了手动刷新永远没反应」。 */
let statusFetching = false;
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

/** 检查点进度百分比。limit_value 为 0 时返回 0，避免除零得到 NaN
    —— NaN 会被模板渲染成「NaN%」，而后台不报错。
    **必须截断而非四舍五入**：后端 `browser/task_presenter.py` 的
    `_progress_percent` 用 `int()` 截断，前端若用 Math.round，999/1000
    会显示成「100%」并画满进度条，而任务其实还没完成（后端同一行文字
    仍是 99%）。两端口径必须一致，否则用户会看到「已 100% 却没自动领取」
    的矛盾。 */
function percentOfCheckpoint(cp: CheckPoint) {
  if (cp.limit_value <= 0) return 0;
  return Math.min(100, Math.floor((cp.cur_value / cp.limit_value) * 100));
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

/** 「有无有意义检查点」的判据在 lib/task-view.ts（零 import，可被 Node 直测）。
 *  模板与 plainTasks 都用它，本文件不再另立第二套口径。 */

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

/**
 * 下面四个派生值必须走 computed，**不能**直接在模板里调用函数。
 *
 * 原因：`statusLine` 由 1 秒轮询更新（观看时长几乎每秒都在涨），
 * 于是整个 TaskProgress 每秒重渲染一次 —— 而此前模板里写的是
 *   v-for="(group, i) in groupDurationTasks(tasks)"      // 建 Record + sort
 *   v-for="cp in [...group.checkpoints].sort(...)"        // 复制数组 + sort
 *   v-for="task in tasks.filter(...)"                     // 新建数组 + 跑正则
 * 三处都是普通函数调用，每次重渲染全量重算。computed 会按依赖缓存，
 * 只在 tasks 真正变化时才重算。
 */
const durationGroups = computed(() => groupDurationTasks(tasks.value));

const hasDuration = computed(() => hasDurationTasks(tasks.value));

/** 本活动「该显示」的任务列表。判据（含为什么不能用标题词、为什么隐藏不影响
 *  领取）全部写在 lib/task-view.ts，本文件只调用，不复述。 */
const plainTasks = computed(() => visibleTasks(tasks.value));

/** 时长任务组内检查点按 limit_value 升序的副本，按组前缀缓存 */
const sortedDurationCheckpoints = computed(() => {
  const map = new Map<string, CheckPoint[]>();
  for (const group of durationGroups.value) {
    map.set(
      group.prefix,
      [...group.checkpoints].sort((a, b) => a.limit_value - b.limit_value),
    );
  }
  return map;
});

/** 中间那一格（文字进度条 + 「0/600」）的两列定义。
 *
 *  第二列必须**定宽**，两个理由彼此独立、各挡一次回归：
 *  · 不能随内容变：同卡内「0/60」比「0/600」窄，整组宽度逐行不同 →
 *    条子左边缘错开（用户报过一次「居中你弄那去了」）。
 *  · 不能写死 px：旧写法留 56px，而本卡最长的那串只要 ~30px，多出的 25px
 *    全落在数字**右侧** → 居中的是盒子、墨迹看着偏左（用户报「仍然没居中」）。
 *  取「本卡最长的那串」做定宽：既逐行同宽，又几乎不留余量。
 *
 *  ch = 当前字体「0」的宽度，数字段带 tabular-nums 故每位恰为 1ch；
 *  斜杠按 ~0.6 位估的（**未逐字核过**，改字体或字号后要目视确认）。
 *  这里必须是**一个确定值**（不能写成 minmax(估算, max-content)）：全卡共用同一个
 *  字符串，各行才等宽；若让某行按自己的墨迹加宽，条子左边缘又会逐行错开。
 *  位数取 cur/limit **位数之和**的最大值，所以「360/360」与「0/600」
 *  两种写法都会被算进去。 */
const numberGroupCols = computed(() => {
  let digits = 0;
  const scan = (cps: CheckPoint[]) => {
    for (const cp of cps) {
      digits = Math.max(
        digits,
        String(cp.cur_value).length + String(cp.limit_value).length,
      );
    }
  };
  for (const list of sortedDurationCheckpoints.value.values()) scan(list);
  for (const task of plainTasks.value) {
    if (shouldShowCheckPoints(task)) scan(task.check_points);
  }
  return `auto ${digits + 0.6}ch`;
});

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
  // 已在途（手动刷新撞上轮询）：这一次落空，下一次轮询在 1s 内必到
  if (statusFetching) return;
  statusFetching = true;
  try {
    // 走 accountsStore.getStatus 而不是自己 invoke：此前同一个 IPC 有两套
    // 前端封装（store 一份、组件内联一份），类型与错误处理会持续漂移。
    const status = await accountsStore.getStatus(accountId);
    // 身份快照：请求在途期间用户可能已切到别的账号，
    // 迟到响应会污染当前显示（旧账号的分钟数/进度出现在新账号页）
    if (props.accountId !== accountId) return;
    statusLine.value = status.status_line;
    progressPercentRaw.value = status.progress ? status.progress.percent : 0;
    loginInvalidated.value = status.login_invalidated;
    // 成功即清零：这个计数器要表达的是「**连续**失败」，只加不减会让
    // 几小时里分散的三次偶发失败凑成一次「账号可能已被外部删除」的误报。
    statusFailures = 0;
  } catch {
    // 状态查询失败：保留上次数据，但累计失败后给出降级提示
    if (props.accountId !== accountId) return;
    statusFailures += 1;
    // 每 3 次失败重申一次，而不是只在第 3 次提示一次。
    // 原先写的是 `statusFailures === 3`（精确相等）—— 第 4、5、6… 次
    // 连续失败不再提示，而这条是唯一能告诉用户「账号可能已被外部删除」
    // 的诊断，用户若此刻正在看浏览器就会永久错过它。
    //
    // 为什么用 % 3 而不是 >= 3：1 秒轮询下一直失败时，`>= 3` 会让提示
    // 每秒钟刷新一次倒计时，变成永久常驻且不断闪动；% 3 是每约 3 秒
    // 重申一次，既不会漏也不会刷屏。
    if (statusFailures >= 3 && statusFailures % 3 === 0) {
      const message = "状态查询连续失败，可能账号已被外部删除";
      showStatusError(message);
      // 同时写进日志面板：行内提示 10 秒后仍会消失，而日志可回看。
      // 与 App.vue 关闭失败时写日志的做法一致（那里也是「提示 + 日志」双通道）。
      logsStore.addLog({
        timestamp: new Date().toISOString(),
        account_id: accountId,
        level: "warning",
        message,
      });
    }
  } finally {
    statusFetching = false;
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

/**
 * store 侧的**瞬时过程提示**（如「已有刷新进行中，已排队下一次刷新...」
 * 「检测到任务完成，正在自动领取奖励...」）。
 *
 * 必须监听 `hint` 而不是 `text`：
 *   * `text` 是后端 `refresh_tasks` 下发的**完整格式化任务进度文本**，
 *     每轮刷新都覆盖一次。它的全部信息已并入上方胶囊与结构化列表，
 *     组件里另有注释说明它**刻意不显示**（重复一份会让用户对着两处
 *     数字核对）。把 `text` 接进 UI 会每 30 秒弹出一大段本应隐藏的文本。
 *   * `hint` 才是「刚刚发生了什么」的一次性通知 —— 它此前只被写、
 *     从未被读（tasks.ts 四处赋值、全项目零消费），于是「连点手动刷新
 *     时给出可见反馈」这个写在注释里的设计意图从未生效。
 *
 * 复用页面级的定时提示（与 storeError 的 watch 同构），但**用独立的
 * 通道**（`actionHint` 而不是 `actionError`）：共用时 hint 会顶掉错误
 * 提示，让用户看不到真正的失败原因（见 actionHint 声明处的实测说明）。
 */
const storeHint = computed(() => accountTasks.value.hint || "");

watch(storeHint, (message) => {
  if (!message) return;
  showActionHint(message);
  // 显示后立刻消费掉。不清空的话同一条文案第二次出现时 watch 不会触发
  // （值没变）—— 用户第二次连点「手动刷新」就看不到「已排队」提示了。
  // 已用真实 Vue 运行时复现：不清空时连点两次只提示 1 次，清空后 2 次。
  if (props.accountId) tasksStore.consumeHint(props.accountId);
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

/** 状态轮询。
 *
 *  useTimeoutPoll 的调度是 `await fn(); start()` —— **fn 落定之前不排下一次**。
 *  这正是原先 statusFetching + statusStale + finally 里那个「续跑定时器」
 *  手工实现的东西：setInterval 无条件 tick，慢响应时每次 tick 都撞上在途，
 *  而收尾时又立刻续跑一次 → 两条调度叠加，sidecar 越慢请求越密（正反馈）。
 *  交给它之后节奏严格落回固定周期，statusStale / staleRetryTimer /
 *  startStatusTimer / stopStatusTimer 这一整套簿记都不再需要。
 *
 *  immediateCallback 必须显式开（默认 false）：否则丢掉「启动/换账号后
 *  立刻刷一次」，顶部四字段与掉宝进度条要空等一个周期才出现。
 *  immediate 关掉：轮询的启停由下面的 watch 按 running 决定，不在 setup
 *  阶段就开跑。 */
const { pause: pauseStatusPoll, resume: resumeStatusPoll } = useTimeoutPoll(
  fetchStatus,
  STATUS_REFRESH_INTERVAL_MS,
  { immediate: false, immediateCallback: true },
);

function clearWatchState() {
  statusLine.value = "";
  progressPercentRaw.value = 0;
  loginInvalidated.value = false;
  statusFailures = 0;
  // 换账号/停止时把上一个账号留下的行内提示一并收掉：
  // store 里的任务错误可能还是旧账号的，而本地提示是定时显示的，
  // 不清的话用户会看到「A 账号的失败原因」挂在 B 账号的卡上。
  // hint 通道同理：它是「刚刚发生了什么」的一次性通知，换账号后
  // 「已排队下一次刷新」这类文案已不属于当前账号。
  clearActionError();
  clearActionHint();
}

// 轮询周期随「任务查询间隔」变化，与 App.vue 的任务刷新共用同一个字段，
// 因此由 App.vue 统一在自身定时器里处理，这里不再重复建 watch。
//
// accountId 与 running **必须合并在同一个 watch 里**：两者同源（都来自
// App.vue 的 selectedAccount），从「运行中的账号 A」切到「运行中的账号 B」
// 时它们同时变化。分成两个 watch 会对同一个账号触发两次 handleRefresh ——
// 第二次进入时 refreshing 已为 true，走 tasks.ts 的排队分支置
// refreshQueued，链尾**真的会再跑一轮 refresh_tasks**，一次切换就是
// 两次 sidecar 往返。
//
// immediate: true 替代原先 onMounted 里的那次调用（避免三处重复触发）。
watch(
  () => [props.accountId, props.running] as const,
  ([accountId, running], prev) => {
    const prevAccountId = prev?.[0];
    if (!accountId) {
      // 取消选中/账号被删：停轮询并清空上一个账号的观看态
      pauseStatusPoll();
      clearWatchState();
      return;
    }
    // 换账号时必须清空，否则会短暂显示上一个账号的观看数据
    if (accountId !== prevAccountId) clearWatchState();
    if (running) {
      resumeStatusPoll();
      // 启动挂宝后立刻刷一次任务进度：启动前的任务列表是上一次运行残留的
      // （甚至是昨天的任务 ID），用户点下「启动」后第一眼看到的进度条与
      // 胶囊必须属于本次运行，否则会以为配置没生效。
      void handleRefresh();
    } else {
      // 停止后不再轮询，并清空观看态，避免残留上一次的进度
      pauseStatusPoll();
      clearWatchState();
    }
  },
  { immediate: true }
);

// 轮询在组件卸载时由 useTimeoutPoll 随作用域自动 pause，无需手写 onUnmounted。
</script>

<template>
  <!-- 卡片内边距 18/12/18/14、间距 8px，对齐 Qt 时代的进度面板。

       overflow-hidden 已移除：它是为了「让本卡在右列 grid 里可被压缩」而加的，
       代价是把下方任务展示区的下限也一并压掉 —— 日志一展开，6 个检查点只剩 2 个。
       现在任务区贴合内容（见下方任务展示区注释），卡片高度 = 内容高度，
       窗口有富余高度时由右列让给日志卡下方。

       卡片内部那两个 min-h-0 不是可选优化，见 CardContent 处的长注释：
       没有它们，「内容高度逐环上传」会让卡片高度被内容顶高、无法由内容决定。 -->
  <!-- card-hover：与账号栏、配置卡、日志卡统一 —— 此前只有这一张卡没有
       hover 时的边框提亮，鼠标扫过右列三张卡时它是唯一不响应的。 -->
  <Card data-nav-region="progress" data-nav-order="4" class="card-hover flex flex-col">
    <CardHeader class="px-4 pb-2 pt-3">
      <div class="flex flex-wrap items-center gap-2">
        <!-- 与另两张卡统一为 15px + font-semibold（原为 11pt + font-bold，
             既与正文几乎同大、字重又与 AccountList 不一致）。 -->
        <CardTitle class="text-[15px] font-semibold">挂宝进度</CardTitle>
        <span
          v-if="!accountId"
          class="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
        >
          未选择账号
        </span>
        <!-- transition-colors：运行/失效/待机三态切换时底色与文字色原本是瞬变的
             （全项目只有 TitleBar 的状态胶囊有过渡）。 -->
        <span
          v-else
          class="rounded-full px-2 py-0.5 text-xs transition-colors"
          :class="running ? 'bg-signal-success/10 text-signal-success' : (loginInvalidated ? 'bg-signal-danger/10 text-signal-danger' : 'bg-muted text-muted-foreground')"
        >
          {{ statusBadgeText }}
        </span>
        <div class="flex-1"></div>
        <Tooltip
          label="检测到任务达到 100% 后自动领取；领取失败会在后续刷新时重试"
        >
          <div class="flex items-center gap-1.5">
            <Checkbox
              id="auto-claim"
              :model-value="configStore.config.auto_claim_rewards"
              aria-label="自动领取奖励"
              @update:model-value="configStore.config.auto_claim_rewards = $event === 'indeterminate' ? true : $event"
            />
            <Label for="auto-claim" class="cursor-pointer text-xs">自动领取</Label>
          </div>
        </Tooltip>
        <Tooltip :label="actionBlockReason" :wrap="claiming || !hasTasks || !accountId">
          <Button
            size="sm"
            class="h-7 rounded-md px-3 text-xs"
            :disabled="claiming || !hasTasks || !accountId"
            @click="handleClaim()"
          >
            {{ claimButtonText }}
          </Button>
        </Tooltip>
        <Tooltip :label="!accountId ? '请先在左侧选择账号' : ''" :wrap="refreshing || !accountId">
          <Button
            size="sm"
            variant="outline"
            class="h-7 rounded-md px-3 text-xs"
            :disabled="refreshing || !accountId"
            @click="handleRefresh"
          >
            {{ refreshing ? "刷新中..." : "手动刷新" }}
          </Button>
        </Tooltip>
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
    <!-- px-4 / pb-4（均 16px）：统一到 4px 网格，与另两张卡四边一致
         （原为 18px 横向 + 14px 纵向的任意值）。
         纵向 +2px 已计入最小窗口高度从 860 抬到 868（见 App.vue）。
         注释刻意不复写旧类名 —— Tailwind v4 会扫源码原文并生成，
         注释里的类名同样会污染产物。 -->
    <CardContent class="flex min-h-0 flex-1 flex-col px-4 pb-4 pt-0">
      <div class="flex min-h-0 flex-1 flex-col gap-3">
        <!-- 状态行：后端 format_watch_status_line 返回「A | B | C | D」四段，
             这里按 | 拆成字段格渲染（见 statusSegments）。
             占位文案必须与后端四段结构一致：原实现在无账号分支用了
             已废弃的「本次有效观看」三段式，与有账号时字段结构不一致。
             刻意不加 title：整行文字已在四个格子里可见，悬浮重复一遍
             只会遮挡内容。 -->
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
          :aria-valuenow="Math.round(progressPercent)"
        >
          <!-- 三处都读同一个补间值，因此不再各自写 CSS 过渡：
               过渡交给 progressPercent（useTransition）统一驱动，
               否则会变成「JS 补间 + CSS 过渡」的双重缓动，比原来还慢。 -->
          <div
            class="h-full bg-primary"
            :style="{ width: `${progressPercent}%` }"
          />
          <span
            class="absolute inset-0 flex items-center justify-center px-2.5 text-xs font-semibold text-primary-foreground"
          >
            掉宝进度 {{ Math.round(progressPercent) }}%
          </span>
          <span
            class="absolute inset-0 flex items-center justify-center px-2.5 text-xs font-semibold text-foreground"
            :style="{ clipPath: `inset(0 0 0 ${progressPercent}%)` }"
          >
            掉宝进度 {{ Math.round(progressPercent) }}%
          </span>
        </div>

        <!-- 任务展示区：**固定 210px**（用户 2026-10-15 定：剩下的垂直空间给任务区，
             任务区高度恒定，多出来的任务在区内滚动）。

             为什么不能有 `flex-1`：右列 grid 原本给本卡一行
             `minmax(364px, 1fr)`，剩下的高度全被 `flex-1` 的任务区吃掉，
             检查点只有 6 行时列表底部多出 40~60px 空白。那段空白是
             **拉伸出来的**，不是内容高度 —— 所以把 min-h 从 220 一路降到 190
             对它一点作用都没有（用户连着两轮报「还是有很大的间距」）。
             现在右列三行全部按内容取高（见 App.vue 的 grid-rows），
             本区不再有 `flex-1`，高度富余时落在日志卡下方。

             ⚠ min-h 与 max-h 必须**写同一个值**，两个都不能省：
               * 只写 min-h → 内容多时向下延伸，把日志栏挤没（用户实测报过）；
               * 只写 max-h → CSS 规范里 min-height 优先于 max-height，
                 若日后有人把 min-h 调大，上限会静默失效、既不封顶也不滚动；
               * 门禁要求保留 `min-h-[`（高度保底），所以两个都写。

             210 来自实测反推（估算在本项目已错过两次）：最小窗口 1030×868 下
             实测得线性关系  日志面板高 = 275 − 任务区高
             （任务区 170 → 面板 105；226 → 49，斜率恰为 1，因为多出来的高度
             全部来自彼此抢空间的三张卡）。
             **但按这个关系算出的 65px 面板，实测只放得下一行日志**（一行需
             行高 24 + 内边距 12 + 边框 2 = 38，两行需 64 —— 差额出在截距 275
             本身：算它时用的是「右列可视 832」，没扣掉日志卡的卡头）。
             用户看过实窗口后拍板「一行也行，就这样设计」，故 210 保留。
             ⚠ 想真放进两行，得把任务区再降 ~30px 并重新实测截距；
             改任一来源（--log-row-h、日志卡头/内边距、状态四格行、卡头、
             配置卡高度、最小窗口尺寸）都会让 275 这个截距变化，必须重新实测。 -->
        <div class="scroll-subtle min-h-[210px] max-h-[210px] overflow-y-auto rounded-md border border-input bg-input/40 p-2">
          <!-- 有任务 / 空态之间加过渡。父容器的最小高度（上面那个固定值）
               保证 out-in 期间不会塌陷，两个分支的高度差因此不会变成
               「整块跳一下」。
               注释刻意不复写高度类名：Tailwind v4 按源码原始文本扫描，
               注释里出现的类名会被真生成进产物 CSS 成为死规则。 -->
          <Transition name="panel-switch" mode="out-in">
          <div v-if="hasTasks" key="tasks" class="space-y-3">
          <!-- 时长任务聚合 -->
          <div v-if="hasDuration" class="space-y-2">
            <div v-for="(group, index) in durationGroups" :key="group.prefix" class="space-y-1">
              <div class="text-sm font-medium">
                {{ index + 1 }}. {{ group.prefix }} (当前: {{ group.currentMinutes }} 分钟)
              </div>
              <!-- 检查点用左侧竖线表达层级：比单纯左缩进 16px 更明确，
                   且不与任务名的悬挂缩进混淆。
                   （注释刻意不写缩进的 Tailwind 类名：Tailwind v4 按源码
                   原始文本扫描，注释里的类名会被生成进产物 CSS） -->
              <div class="space-y-1 border-l-2 border-border pl-3">
                <!-- 检查点单行三段：左=总时间+任务ID，中=文字进度条+数字，
                     右=状态+奖励。

                     **「进度条+数字」要居中，唯一可行的写法是左右两格各占一半
                     富余（两条相等的可压缩轨道）、中间按内容取宽。** 一侧 1fr、
                     另一侧 auto 时 1fr 会吃掉全部富余、把中间推到边上 ——
                     普通任务行上一版正是那种列结构，所以用户两轮反馈
                     「仍然不作为一个整体居中」。

                     **两条轨道的下限必须是 0**（可压缩），否则别名/任务 ID
                     一长就把那一格撑到内容宽、中心点整体偏移 —— 与
                     「可压缩容器装不可压缩内容」是同一种病，而且因为溢出被
                     居中分配在轨道内，scrollWidth 都不变，扫描器查不出来。

                     段内各列仍是定宽：以前由内容决定时「60/60」比「360/360」
                     窄 21px、「已完成」比「已领取」宽，同一份数据在不同行之间
                     对不上竖线，扫读时每行都得重新找位置。 -->
                <div
                  v-for="cp in sortedDurationCheckpoints.get(group.prefix) ?? []"
                  :key="cp.sid"
                  class="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-x-2 gap-y-0.5 py-0.5 text-xs"
                >
                  <div class="flex min-w-0 items-center gap-1.5">
                    <span class="shrink-0 font-medium tabular-nums text-foreground">
                      {{ cp.limit_value }}分
                    </span>
                    <Tooltip :label="cp.sid">
                      <span class="font-mono text-[11px] text-muted-foreground">
                        {{ cp.sid.slice(-4) }}
                      </span>
                    </Tooltip>
                  </div>
                  <!-- 整条进度条都是灰阶：填充段与后面的数字同色，未填充的
                       `-` 再淡一档。此前填充段用 signal-info 蓝，蓝色进度条夹在
                       两串灰数字中间会显得是另一个控件 —— 用户要的是「进度条和
                       它的数字读起来是一件事」，填充/未填充改由 `#` 与 `-` 的
                       字形本身承担。两处形态（时长任务组 / 普通任务）必须一致。

                       「紧贴 + 逐行对齐 + 整体居中」三个条件同时成立靠两件事：
                       数字列定宽取**本卡最长的那串**（见 numberGroupCols），
                       以及左右两格等分富余（见上面那段）。
                       数字在列内左对齐：右对齐会让它贴住列的右边界，与条子之间
                       隔一段随位数变化的空白，看着就是"没紧贴"。列间 4px。 -->
                  <div
                    class="grid min-w-max items-center gap-1"
                    :style="{ gridTemplateColumns: numberGroupCols }"
                  >
                    <span class="font-mono text-[11px] leading-none tracking-tighter">
                      <span class="text-muted-foreground/70">[</span><span class="text-muted-foreground">{{ barFilled(cp) }}</span><span class="text-muted-foreground/50">{{ barEmpty(cp) }}</span><span class="text-muted-foreground/70">]</span>
                    </span>
                    <span class="tabular-nums text-muted-foreground">
                      {{ cp.cur_value }}/{{ cp.limit_value }}
                    </span>
                  </div>
                  <div class="flex min-w-0 items-center justify-end gap-1.5">
                    <span
                      class="shrink-0 rounded-full px-1.5 py-0.5 text-[11px] font-medium transition-colors"
                      :class="checkPointStatusClass(cp)"
                    >
                      {{ checkPointStatus(cp) }}
                    </span>
                    <!-- 奖励名列定宽 88px：5 个汉字（12px/字 = 60px）+ 间隔 2px
                         + 「×N」约 16px，再留 10px 富余（字体度量各档略有出入）。
                         可截断字数由用户 2026-10-15 定为 5 个（原 8 字要预留
                         112px，会把中段挤得没地方）。
                         上一版按 76px 算小了：扣掉间隔与 ×N 只剩 58px，
                         满 5 字的名字（如「香蕉猫头像」）被截成省略号。
                         没有宽度约束时截断类在「宽度由内容决定」的列里根本不生效
                         （列被内容撑开），奖励名一长就把整行顶宽。
                         min-w-0 挂在名字上而不是外层：外层是 shrink-0 的定宽盒子，
                         截断必须发生在名字本身。 -->
                    <Tooltip
                      v-if="cp.award_name"
                      :label="`${cp.award_name} ×${cp.award_count}`"
                    >
                      <span class="flex w-[88px] shrink-0 items-baseline gap-0.5">
                        <span class="min-w-0 flex-1 truncate text-muted-foreground">
                          {{ cp.award_name }}
                        </span>
                        <span class="shrink-0 text-muted-foreground">×{{ cp.award_count }}</span>
                      </span>
                    </Tooltip>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 普通任务列表（过滤掉已被时长分组消费的任务） -->
          <div
            v-for="task in plainTasks"
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
                  class="rounded-full px-1.5 py-0.5 text-[11px] font-medium transition-colors"
                  :class="statusClass(task.status)"
                >
                  {{ task.status }}
                </span>
              </div>
            </div>
            <!-- 此前这里是一条 Progress 细轨道（h-1.5）。删掉的理由：
                 任务级进度已由下方逐检查点的 `[####----] 0/60` 精确表达，
                 这条轨道在 0% 时是**一条纯灰线**，用户认作「分割线」而不是进度条
                 （2026-10-15 实测反馈），而它承载的信息量为零。
                 顶部那条「掉宝进度」大条仍在（它是整体指标，且做了双层文字保证
                 100% 时也可读），本卡不需要第二条。 -->

            <!-- 检查点明细：与时长任务组的胶囊行**列结构完全一致**
                 （两处形态必须一模一样，否则时长任务与普通任务的检查点
                 在同一张卡里会呈现两套对齐基准）。
                 三段中只有中间那格按内容取宽、左右两格等分富余，
                 居中与逐行对齐都靠它，理由见时长任务组那段的说明。
                 别名（第 1 格）可长、可截断。 -->
            <div v-if="shouldShowCheckPoints(task)" class="mt-2 space-y-1 border-l-2 border-border pl-3">
              <div
                v-for="cp in task.check_points"
                :key="cp.sid"
                class="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-x-2 gap-y-0.5 text-xs"
              >
                <Tooltip :label="cp.alias">
                  <span class="block min-w-0 truncate text-muted-foreground">{{ cp.alias }}</span>
                </Tooltip>
                <div
                  class="grid min-w-max items-center gap-1"
                  :style="{ gridTemplateColumns: numberGroupCols }"
                >
                  <span class="font-mono text-[11px] leading-none tracking-tighter">
                    <span class="text-muted-foreground/70">[</span><span class="text-muted-foreground">{{ barFilled(cp) }}</span><span class="text-muted-foreground/50">{{ barEmpty(cp) }}</span><span class="text-muted-foreground/70">]</span>
                  </span>
                  <span class="tabular-nums text-muted-foreground">
                    {{ cp.cur_value }}/{{ cp.limit_value }}
                  </span>
                </div>
                <div class="flex min-w-0 items-center justify-end gap-1.5">
                  <span
                    class="shrink-0 rounded-full px-1.5 py-0.5 text-[11px] font-medium transition-colors"
                    :class="checkPointStatusClass(cp)"
                  >
                    {{ checkPointStatus(cp) }}
                  </span>
                  <Tooltip
                    v-if="cp.award_name"
                    :label="`${cp.award_name} ×${cp.award_count}`"
                  >
                    <span class="flex w-[88px] shrink-0 items-baseline gap-0.5">
                      <span class="min-w-0 flex-1 truncate text-muted-foreground">
                        {{ cp.award_name }}
                      </span>
                      <span class="shrink-0 text-muted-foreground">×{{ cp.award_count }}</span>
                    </span>
                  </Tooltip>
                </div>
              </div>
            </div>
          </div>
        </div>
          <div v-else key="empty" class="py-4 text-center text-sm text-muted-foreground">
            {{ !accountId ? "请先在左侧选择账号" : (refreshing ? "正在查询任务进度..." : "暂无任务进度，点击\"手动刷新\"") }}
          </div>
          </Transition>
        </div>

        <!-- 任务提示。两类消息走**两个独立通道**（各自计时、互不重置）：
               * 后端错误（刷新失败、领取失败）→ actionError，红 + role="alert"；
               * 过程提示（「已排队下一次刷新」「正在自动领取奖励」）→ actionHint，
                 中性色 + role="status"。

             两者共用同一个 p 且 **error 优先**：同时存在时只显示 error，
             因为错误是用户必须看到的（hint 只是过程说明）。
             早前两者共用一个 useTimedNotice 时，hint 会把 error 顶掉、
             并把停留时长从 10s 重置为 3s —— 用户看不到真正的失败原因。
             两者不能都涂成红色：过程提示被染红会让用户以为出错了。 -->
        <p
          v-if="actionError || actionHint"
          class="notice-appear whitespace-pre-wrap break-all font-mono text-xs transition-colors"
          :class="actionError ? 'text-signal-danger' : 'text-muted-foreground'"
          :role="actionError ? 'alert' : 'status'"
        >
          {{ actionError || actionHint }}
        </p>
      </div>
    </CardContent>
  </Card>
</template>
