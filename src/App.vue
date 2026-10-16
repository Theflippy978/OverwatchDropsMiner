<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from "vue";
import {
  useIntervalFn,
  refDebounced,
  usePreferredDark,
  useResizeObserver,
  watchThrottled,
} from "@vueuse/core";
import { SplitterGroup, SplitterPanel, SplitterResizeHandle } from "reka-ui";
import { getCurrentWindow, primaryMonitor, availableMonitors, LogicalSize, PhysicalPosition } from "@tauri-apps/api/window";
import { invoke } from "@tauri-apps/api/core";
import { useAccountsStore } from "@/stores/accounts";
import { useConfigStore } from "@/stores/config";
import { useLogsStore } from "@/stores/logs";
import { useTasksStore } from "@/stores/tasks";
import AccountList from "@/components/AccountList.vue";
import ConfigForm from "@/components/ConfigForm.vue";
import LogViewer from "@/components/LogViewer.vue";
import TaskProgress from "@/components/TaskProgress.vue";
import TitleBar from "@/components/TitleBar.vue";
import InputContextMenu from "@/components/InputContextMenu.vue";
import QrLoginDialog from "@/components/QrLoginDialog.vue";
import UpdateDialog from "@/components/UpdateDialog.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import { NOTICE_AUTO_HIDE_MS } from "@/lib/notice";
import { formatIpcError } from "@/lib/ipc-error";
import { installRegionNav } from "@/lib/region-nav";
import {
  TASK_QUERY_INTERVAL_DEFAULT_SECONDS,
  TASK_QUERY_INTERVAL_MAX_SECONDS,
  TASK_QUERY_INTERVAL_MIN_SECONDS,
} from "@/lib/config-limits";

const accountsStore = useAccountsStore();
const configStore = useConfigStore();
const logsStore = useLogsStore();

const darkMode = ref(false);
const showQrLogin = ref(false);
const qrError = ref("");
const themeFollowSystem = ref(true);
/** 系统主题。**响应式**：usePreferredDark 内部走 matchMedia 的 change 事件，
 *  不是轮询 —— 原实现是 5 秒 setInterval 轮询，用户切系统主题后最长 5 秒才跟上。
 *  从手写 MediaQueryList 句柄换成它，顺带消灭了「装/卸监听 + 空值守卫」那套簿记。 */
const systemDark = usePreferredDark();
/** 上一次**请求**切换到的主题；`null` = 还没有过手动/系统切换。
 *
 *  存在的唯一理由：`applyThemeWithTransition` 把 `darkMode.value` 的赋值推迟到
 *  `startViewTransition` 的**异步**回调里，所以「连点两次」时第二次读
 *  `darkMode.value` 拿到的还是旧值 —— 两次算出的目标相同，结果只切了一次。
 *  用这个变量当基准，连点才能真的来回切。 */
let themeRequested: boolean | null = null;
/** 主题 View Transition 是否正在进行。
 *
 *  存在的理由（2026-10-14 CDP 实测）：VT 期间浏览器把命中测试落到 `<html>` 上
 *  （快照层不属于 DOM），所以按钮**收不到**第二次点击 —— 实测间隔 60/120/220ms
 *  时事件都派发到了 `hit: 'HTML'`、`onBtn: false`，而 VT 实测耗时 265~290ms，
 *  300ms 以上才正常。用户的手感是「连点有卡卡的感觉、按了没反应」。
 *
 *  这个拦不住（不是我们的覆盖层吃点击，`::view-transition{pointer-events:none}`
 *  早就加了），所以退而求其次：**把它显示出来** —— 过渡期间按钮降透明度、
 *  光标换成忙碌态，用户知道「正在切」而不是「我是不是没点上」。
 *  刻意**不真禁用按钮**：禁用会让正在聚焦的按钮丢焦点，方向键落回 body、
 *  打断区域导航（这条由 UI 回归门禁锁住）。 */
const themeTransitioning = ref(false);

/** 方向键区域导航的卸载函数（见 onMounted / onUnmounted）。
 *  它挂的是 document 级 keydown，必须在卸载时摘掉 —— 否则热重载或
 *  组件重建会叠加多份 listener，一次按键触发多次跳转。 */
let uninstallRegionNav: (() => void) | null = null;

const THEME_KEY = "ui/theme";

/** 窗口硬下限：防布局崩坏。
 *
 *  **语义前提（2026-10-09 按 Tauri 源码更正）**：`tauri.conf.json` 的
 *  `minWidth` / `minHeight` 与下面的常量**是同一语义 —— 客户区（inner）尺寸**，
 *  两者必须相等，**不存在窗框差值**。Tauri 自己负责把客户区换算成外框：
 *    * `tauri-utils` 的 config.rs 对 `min_width` 只注明 "in logical pixels"；
 *    * `tauri-runtime-wry` 的 lib.rs 走 `window.inner_size_constraints(constraints)`；
 *    * `tao` 的 windows 平台在写 `ptMinTrackSize` 前调用
 *      `util::adjust_size(hwnd, size, is_decorated)`，用 `adjust_window_rect`
 *      把**客户区尺寸换算成外框尺寸**（`PhysicalSize::new(rect.right - rect.left, ...)`）。
 *  历史注释曾写「conf 的 minWidth 是外框宽度、conf 要比客户区下限多 14」，
 *  那是**反的**，会让后续维护者把下限算错 14px，已更正。
 *  实际影响：按旧假设「1030 → 客户区 1016」推导，而真实客户区就是 1030 ——
 *  即当前值比原推导**更宽裕**，因此 1030 / 868 保持不变（偏保守是安全的）。
 *
 *  1030 × 868 的来历：
 *  宽度取「侧栏拉满 420 + 右列四区块 min-content 的最大值」，
 *  挂宝进度卡（检查点行 72 / 240 / 163 + 缩进与内边距）实测需要 538，
 *  配置卡 518，取 538。还必须算进去的一个扣减：
 *    **最坏情况是任务区正在纵向滚动时** —— `.scroll-subtle` 的 thin
 *    纵向滚动条会再吃掉约 8px 任务区宽度（实测行溢出 8px）。
 *  1030 → 检查点行可用 481 ≥ 所需 477，留 4px 余量。
 *
 *  高度裸下限 853（配置卡 297 + 挂宝卡下限 364 + 日志卡折叠 118
 *  + 行距与内边距 38 + 标题栏 36）。**860 → 868 的来历**：三张卡的
 *  纵向内边距统一到 4px 网格（16px）后内容总高 +8px（配置卡 +4、
 *  挂宝卡 +2、日志卡 +2），853 → 861；保留原设计同样的 7px 余量
 *  （用于吸收 3 秒自动消失的行内提示带来的瞬时增高约 30px 中的一部分，
 *  以及 1~2px 的取整误差），861 + 7 = 868，且 868 是 4 的倍数。
 *  取 868 而不是 861 的原因与原设计取 860 而不是 853 相同：
 *  861 那档会把挂宝卡挤到下限以下 1~2px。
 *
 *  **868 是推算值，不是实测值**（860 才是 CDP 逐档扫描实测的），
 *  待真机验收；且上面的宽度推导已按正确语义复核过，无需再减 14px。
 *  首次启动尺寸与此无关（tauri.conf.json 的 width/height 是 1240×900）。
 *  必须与 src-tauri/tauri.conf.json 的 minWidth/minHeight 同源。 */
const MIN_WINDOW_WIDTH = 1030;
const MIN_WINDOW_HEIGHT = 868;

/** 窗口几何记忆的 localStorage key（值统一为逻辑像素 dip） */
const GEOMETRY_KEY = "window_geometry";

function getSavedTheme(): string | null {
  try {
    return localStorage.getItem(THEME_KEY);
  } catch {
    return null;
  }
}

function saveTheme(theme: string) {
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
  }
}

const showUpdateDialog = ref(false);
const updateLatestVersion = ref("");
const updateReleaseUrl = ref("");
/** 手动检查更新的进行中标志。兼任单飞行锁：后端一次检查最长 10s，
    连点会重复打 GitHub API（未认证 60 次/小时，很容易撞限流）。 */
const checkingUpdate = ref(false);
/** 手动检查更新时「正在检查…」至少要显示多久（毫秒）。
 *
 *  本地开发包的版本号带 dev 标识，后端设计上直接返回、不发网络请求，
 *  invoke 在 1~2ms 内就结束 —— 胶囊的进出动画没有可作用的过程，点下去
 *  只看到文案从运行状态直接跳到结果。补一个下限让过程可见。
 *
 *  取 350ms 是「转半圈菊花 + 淡入淡出」能读懂的量级；再长会让本地包
 *  每次手点都显得迟钝。正式版包走真实网络请求本来就超过这个时长，
 *  启动时的自动检查全程静默、不受此值影响。 */
const CHECK_MIN_VISIBLE_MS = 350;

/** 检查结果提示，由标题栏中段胶囊承载；空串 = 退回显示运行状态 */
const updateNotice = ref("");
const updateNoticeError = ref(false);
/** 胶囊 `:title` 的附加上下文（后端 detail：HTTP 状态码、异常类型）。
 *
 *  与 updateNotice 分开存而不是拼进它：胶囊正文是定宽的（宽度与字数预算
 *  见 TitleBar.vue 的胶囊注释与后端 constants.py 的那份常量），
 *  detail 是排障用的长信息，拼上去会溢出。两者在 TitleBar 里分别接到
 *  正文与 title 上。只在失败/跳过时有值。 */
const updateNoticeDetail = ref("");
/** 提示自动消失的定时器句柄 */
let updateNoticeTimer: number | null = null;
/** 运行中尝试关闭窗口时的模态提示（替代阻塞 WebView 的原生 alert） */
const showCloseBlocked = ref(false);
/** 关闭时保存配置失败的原因（空串 = 无失败），供 UI 提示用户 */
const configSaveFailed = ref("");

/** 关闭链路的兜底配置快照：save() 可能因 sidecar 故障/超时失败甚至
    窗口被强杀，写 localStorage 保证用户编辑不会静默丢失。 */
const CONFIG_STASH_KEY = "config_stash";

function stashConfigLocally() {
  try {
    localStorage.setItem(CONFIG_STASH_KEY, JSON.stringify(configStore.config));
  } catch (e) {
    console.warn("写入配置快照失败:", e);
  }
}

function applySavedTheme() {
  const savedTheme = getSavedTheme();
  if (savedTheme === "dark" || savedTheme === "light") {
    darkMode.value = savedTheme === "dark";
    themeFollowSystem.value = false;
  } else {
    darkMode.value = systemDark.value;
  }
}

const anyRunning = computed(() =>
  accountsStore.accounts.some((a) => a.running)
);

const runningCount = computed(() =>
  accountsStore.accounts.filter((a) => a.running).length
);

// 选中态单一数据源：accounts store。
// Qt 时代删除末行后 currentRow 变 -1 而 current_account_id() 返回 None，
// 按钮随之禁用；本项目此前用 App.vue 的本地 ref，与 store 里的 selectedAccountId
// 形成双源，删除后残留孤儿 id 导致底部「备注/删除」仍可点击。
const selectedAccountId = computed<string | null>({
  get: () => accountsStore.selectedAccountId,
  set: (id) => {
    accountsStore.selectedAccountId = id;
  },
});

// 选中联动沿用 Qt 时代的 set_accounts 语义：
// 原选中仍在列表中 → 保持；否则自动落到首行；列表为空 → 清空选中。
// getter 返回 join 而非数组：map 每次产出新数组，Object.is 恒不相等，
// 会让回调在 getter 每次重算时都执行，正确性隐式依赖函数体的提前返回。
watch(
  () => accountsStore.accounts.map((a) => a.id).join("\u0000"),
  () => {
    const ids = accountsStore.accounts.map((a) => a.id);
    const current = accountsStore.selectedAccountId;
    if (current && ids.includes(current)) return;
    accountsStore.selectedAccountId = ids.length > 0 ? ids[0] : null;
  },
  { immediate: true }
);

const selectedAccount = computed(
  () => accountsStore.accounts.find((a) => a.id === selectedAccountId.value) ?? null
);

onMounted(async () => {
  // 几何恢复与关闭钩子不依赖 sidecar IPC，必须最先就位：
  // 否则 sidecar 冷启动慢/失败时，窗口既不按记忆位置恢复，关闭也不保存
  registerCloseHandler();

  // 主题必须在窗口显示之前定好。原先它排在 4 次 await（含一次完整
  // sidecar 往返的 fetchAccounts）之后，而 restoreWindowGeometry 只需
  // 2 次 IPC 就会 .finally(showWindow) —— 结果暗色用户每次启动都先看到
  // 一闪而过的白底。主题解析与应用是纯同步 + localStorage，不需要 await。
  applySavedTheme();
  updateTheme();

  // 窗口以 visible:false 创建（tauri.conf），几何恢复完成（含异常路径）后再显示，
  // 消除「先中央出现、再瞬间跳到记忆位置」的首显跳动；3s 兜底防恢复卡死导致窗口永不显示
  const showWindow = () => {
    getCurrentWindow().show().catch((e) => console.error("显示窗口失败:", e));
  };
  showFallbackTimer = window.setTimeout(showWindow, 3000);
  restoreWindowGeometry().finally(showWindow);

  // 每一步独立容错：原先 fetchAccounts 失败会冒泡中断 ensureLoaded，
  // 导致 config.loaded 停在 false，此后 save() 被守卫拦成静默空操作，
  // 用户的线程数/房间号/通知地址全部丢失且无任何 UI 提示。
  await runStep("日志监听", () => logsStore.initListeners());
  await runStep("账号监听", () => accountsStore.initListeners());
  await runStep("账号列表", () => accountsStore.fetchAccounts());
  await runStep("配置加载", () => configStore.ensureLoaded());

  // 方向键区域导航：把 ↑/↓ 从「只有账号列表能用」扩展到全界面。
  // 在这里装而不是各组件各装一份 —— 它本质是**跨区块**的导航，
  // 属主只能是应用级；组件级安装会变成多个 listener 互相抢按键。
  uninstallRegionNav = installRegionNav();
  updateTimer = window.setTimeout(() => void checkUpdate(false), 3000);
});

/** 初始化各步骤的统一容错包装：单步失败不影响后续步骤 */
async function runStep(name: string, fn: () => Promise<unknown>): Promise<void> {
  try {
    await fn();
  } catch (e) {
    console.error(`初始化「${name}」失败:`, e);
  }
}

onUnmounted(() => {
  if (showFallbackTimer !== null) clearTimeout(showFallbackTimer);
  if (updateTimer !== null) clearTimeout(updateTimer);
  if (updateNoticeTimer !== null) clearTimeout(updateNoticeTimer);
  // 主题过渡改用 View Transitions 后，不再有摘类定时器与轮询需要清理
  // （过渡由浏览器托管，没有我们持有的句柄）。
  // 配置同步 / 任务刷新 / 系统主题监听 / 拖拽把手监听的清理由 VueUse 随
  // 作用域托管，这里不再逐个摘除。
  uninstallRegionNav?.();
  uninstallRegionNav = null;
  accountsStore.dispose();
  logsStore.dispose();
});

let closeHandlerRegistered = false;
let closing = false;
let configSyncInFlight = false;
let showFallbackTimer: number | null = null;
let updateTimer: number | null = null;

/** 关闭路径专用：带超时的 invoke，超时/失败一律返回 null，绝不阻塞窗口销毁 */
function invokeBounded<T>(command: string, timeoutMs: number): Promise<T | null> {
  return new Promise((resolve) => {
    let done = false;
    // timer 必须提前声明：finish 引用它，而 finish 理论上可能在
    // timer 初始化之前被调用（同步 resolve 场景）。
    let timer = 0;
    const finish = (value: T | null) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      resolve(value);
    };
    timer = window.setTimeout(() => finish(null), timeoutMs);
    invoke<T>(command).then(finish, (e) => {
      // 保留失败原因：shutdown 这类关键命令报错时毫无诊断价值
      console.warn(`命令 ${command} 失败:`, e);
      finish(null);
    });
  });
}

function registerCloseHandler() {
  if (closeHandlerRegistered) return;
  closeHandlerRegistered = true;
  const win = getCurrentWindow();
  win.onCloseRequested(async (event) => {
    // 统一由本流程控制关闭：先阻止默认行为，最后一定 destroy。
    // preventDefault 必须是 handler 的第一条同步语句（Tauri 契约要求
    // "Must be called before the handler returns"）。
    event.preventDefault();
    // 重入保护：整条链路最长约 12s，期间双击 X 或连按 Alt+F4 会并发跑
    // 第二遍 —— 两次 save 互相踩；第二次的 saveWindowGeometry 可能在
    // 第一次 destroy 之后执行（几何永久丢失）；两次 shutdown 里第二次
    // 会看到假的 closed:true。Tauri 不会因为 handler 在 await 期间就
    // 阻止新的 CloseRequested 事件进入。
    if (closing) return;
    if (anyRunning.value) {
      // 有运行中/停止中账号 → 警告并阻止，沿用 Qt 时代的行为
      closing = true;
      showCloseBlocked.value = true;
      closing = false;
      return;
    }
    closing = true;
    try {
      // 先把待存配置写 localStorage 再走 IPC：即使后续 save 失败、
      // 窗口被销毁或进程崩溃，下次启动仍能恢复用户编辑，
      // 不会出现「代码看起来已经等过了，实际配置静默丢失」。
      stashConfigLocally();
      try {
        // 不能用 Promise.race 伪装超时：race 只停止等待，不取消
        // configStore.save()，超时后继续 destroy 会让配置在落盘前丢失。
        await configStore.save();
        configSaveFailed.value = "";
      } catch (e) {
        console.error("保存会话配置失败", e);
        // formatIpcError 不带 context：下方 message 已经拼了「保存配置失败：」前缀，
        // 这里再传一次会变成「保存配置失败：保存配置失败：…」。
        configSaveFailed.value = formatIpcError(e);
      }
      try {
        await saveWindowGeometry();
      } catch (e) {
        console.error("保存窗口几何失败", e);
      }
      await invokeBounded("qr_cancel", 1000);
      const r = await invokeBounded<{ closed: boolean }>("shutdown", 6000);
      // 反转判断：invokeBounded 超时返回 null，那才是真正「清理未完成」
      // 的场景；原先判 r.closed === false 而 Rust 侧硬编码 true，
      // 该告警是永不可达的死代码。
      if (!r || r.closed !== true) {
        // 仅告警仍继续关闭，不阻塞（沿用 Qt 时代的行为）
        console.warn("sidecar 未在预算时间内干净退出，浏览器/驱动进程可能残留，请手动检查任务管理器。");
        logsStore.addLog({
          timestamp: new Date().toISOString(),
          account_id: null,
          level: "warning",
          message: "关闭时 sidecar 未干净退出，浏览器进程可能残留，请检查任务管理器",
        });
      }
      try {
        await win.destroy();
      } catch (e) {
        console.error("销毁窗口失败，重试一次", e);
        await win.destroy().catch(() => {});
      }
    } finally {
      closing = false;
    }
  });
}

/** 配置同步：每 2 秒把当前配置推给正在运行的矿工。
 *
 *  定时器交给 useIntervalFn —— 它随组件作用域自动清理，因此不再需要
 *  手写 setInterval + 句柄 + 「已在跑就不再起」的幂等守卫那一套。 */
useIntervalFn(() => {
  if (!anyRunning.value) return;
  // in-flight 去重：任一账号响应超 2s 时，tick 会无上限地叠加并发
  // invoke，把 Rust 侧 tokio 工作线程与 sidecar 都压垮。
  if (configSyncInFlight) return;
  configSyncInFlight = true;
  invoke("sync_config_to_miners")
    .catch((e) => {
      // 原来完全吞掉错误：sidecar 挂掉时用户只看到「改了配置不生效」，
      // 没有任何线索。
      console.error("同步配置到矿工失败:", e);
    })
    .finally(() => {
      configSyncInFlight = false;
    });
}, 2000);

/** 「任务查询间隔」（毫秒），带 300ms 防抖。
 *
 *  输入框是 ConfigForm 的 v-model，**每敲一个字符**就会改这个值。
 *  没有防抖时每次击键都会重建定时器，把已经走过一半的计时整个归零 ——
 *  用户慢慢输入「3600」的过程中，自动任务刷新可能长时间不触发。
 *  输入过程中的中间态也不该生效：清空输入框时 parseInt("") 得到 NaN，
 *  落到默认值兜底才不会把周期跳成一个意外的小值。
 *
 *  300ms 是「打字停顿」的量级：足够合并连续击键，又不会让用户觉得
 *  「改完了没反应」。这里的范围钳制取自 lib/config-limits.ts，
 *  与 config.ts 保存时同源 —— 不要在这重写数字。 */
const taskQueryIntervalMs = refDebounced<number>(
  computed(
    () =>
      Math.max(
        TASK_QUERY_INTERVAL_MIN_SECONDS,
        Math.min(
          TASK_QUERY_INTERVAL_MAX_SECONDS,
          parseInt(configStore.config.task_query_interval_text, 10) ||
            TASK_QUERY_INTERVAL_DEFAULT_SECONDS,
        ),
      ) * 1000,
  ),
  300,
);

/** 按「任务查询间隔」周期性刷新所有运行中账号的任务。
 *
 *  useIntervalFn 在 interval 是 ref/getter 时会**监视它、变化即重建定时器**
 *  （clear + 重建），这正是原先 watch + 手写防抖 + startTaskRefresh 那段
 *  在做的事；清理由作用域托管，所以 stopTaskRefresh 也一并消失。 */
useIntervalFn(() => {
  const runningAccounts = accountsStore.accounts.filter((a) => a.running);
  for (const account of runningAccounts) {
    void useTasksStore().refreshTasks(account.id, false);
  }
}, () => taskQueryIntervalMs.value);

/**
 * 更新检查。
 *
 * 两条调用路径，只有 force 不同：
 * - 启动 3s 后自动检查（force=false）：受 sidecar 侧 update_channel 门禁约束，
 *   dev 渠道不去打扰 GitHub API（未认证限流 60 次/小时）；**不成功也不吭声**
 *   （启动阶段弹错误只会干扰用户点账号）。
 * - 标题栏按钮手动检查（force=true）：绕过**渠道**门禁真去查一次；无论成败
 *   都给用户可见反馈。
 *
 * 后端返回的是 status 四态（up_to_date / update_available / skipped / failed），
 * 不是「有没有新版」的布尔值 —— 后者会把「网络失败」「GitHub 限流」
 * 「版本号是占位串」统统显示成「已是最新版本」。手动检查必须把这四种情况
 * 分开说清楚，用户才知道是该重试、该换版本、还是确实已经最新。
 *
 * 单飞行：checkingUpdate 兼作锁。GitHub 未认证 API 限流是 60 次/小时，
 * 连点几下就会开始返回 403 —— 现在它会如实显示「限流」，而不是「已是最新」。
 */
async function checkUpdate(force = false) {
  if (checkingUpdate.value) return;
  checkingUpdate.value = true;
  if (force) {
    // 进入「正在检查」先清掉上一次的排障 detail：胶囊正文此时换成「正在检查…」，
    // 若 title 还留着上次失败的原因，hover 会显示「正在检查…：GitHub 返回 HTTP 403」
    // 这种自相矛盾的话。detail 只能在这里清，不能挪进 showUpdateNotice ——
    // 那会连带本次刚设的新值一起清掉（见 showUpdateNotice 的注释）。
    updateNoticeDetail.value = "";
    showUpdateNotice("正在检查…", false);
  }
  const startedAt = performance.now();
  // 结果提示**不能**在 invoke 返回时就写 —— 本地开发包的 invoke 1~2ms 就返回，
  // 写进去会把「正在检查…」立刻顶掉，用户连一帧都看不到。
  // 所以先攒成一个函数，等 finally 里补足最短可见时长后再调用。
  let announce: (() => void) | null = null;
  try {
    const result = await invoke<{
      update_available: boolean;
      status: string;
      message: string;
      detail?: string;
      latest_version: string;
      release_url: string;
    }>("check_update", { force });
    if (result.status === "update_available") {
      updateLatestVersion.value = result.latest_version;
      updateReleaseUrl.value = result.release_url;
      showUpdateDialog.value = true;
      // 弹窗才是主反馈，胶囊不再重复提示「发现新版本」
      if (force) {
        announce = () =>
          showUpdateNotice(`发现新版本 ${result.latest_version}`, false);
      }
    } else if (force) {
      // 只有真正比对完、且本地不落后才说「已是最新」；
      // 失败（网络 / 限流 / 远端异常）与跳过（版本号不可比较）都如实说原因。
      const upToDate = result.status === "up_to_date";
      // **胶囊只显示后端的 message**，detail 不许拼进来。
      // 胶囊是定宽的，宽度预算只在后端常量里写一份
      // （python_sidecar/backend/constants.py 的 CAPSULE_MESSAGE_MAX_CHARS，
      // 像素真相见 TitleBar.vue 的胶囊注释），这里不复述数字。
      // 而 detail 是「HTTP 403」这类排障信息，长度不可控；拼上去必然溢出 ——
      // 2026-10-13 用户报告「还是显示超过 6 个字」，就是因为上一版在这里
      // 用 join("：") 把两者拼成了一串，胶囊与 title 拿到的是同一个长句。
      //
      // 现在二者分离：胶囊显示 message，detail 由 updateNoticeDetail 单独
      // 带给 TitleBar 作 title，需要完整原因的用户 hover 即可看到。
      const text = upToDate ? "已是最新版本" : result.message || "检查更新失败";
      updateNoticeDetail.value = upToDate ? "" : result.detail || "";
      announce = () => showUpdateNotice(text, !upToDate);
    }
  } catch (e) {
    // 自动检查保持静默：启动阶段弹错误只会干扰用户点账号
    if (force) announce = () => showUpdateNotice(formatIpcError(e, "检查失败"), true);
  } finally {
    // 本地开发包的版本号带 dev 标识，后端按「不拿 dev 版去比 release」
    // 的设计直接返回、不发网络请求。整个 invoke 在 1~2ms 内结束，
    // 标题栏胶囊的进出动画没有可作用的过程。补足到 CHECK_MIN_VISIBLE_MS
    // 再显示结果，按钮的菊花与禁用态也一并多亮这段时间。
    //
    // 只对 force 生效：启动 3 秒后的自动检查全程静默，补时长没有意义；
    // 正式版包走真实网络请求本来就超过这个时长，两条路径都不受影响。
    if (force) {
      const elapsed = performance.now() - startedAt;
      if (elapsed < CHECK_MIN_VISIBLE_MS) {
        await new Promise((resolve) =>
          window.setTimeout(resolve, CHECK_MIN_VISIBLE_MS - elapsed),
        );
      }
    }
announce?.();
    checkingUpdate.value = false;
  }
}

/**
 * 在标题栏胶囊显示一条 3 秒后自动消失的提示。
 *
 * 复用 notice.ts 的时长常量而非另定一个：配置保存/导入等提示都按 3 秒，
 * 用户已经形成「提示会自己消失」的预期，这里改成别的时长会显得不一致。
 *
 * detail 不在这里清：它由 checkUpdate 在调本函数前按本次结果现填，
 * 清空会连带正确的那次结果一起丢掉。
 */
function showUpdateNotice(text: string, isError: boolean) {
  if (updateNoticeTimer !== null) clearTimeout(updateNoticeTimer);
  updateNotice.value = text;
  updateNoticeError.value = isError;
  updateNoticeTimer = window.setTimeout(() => {
    updateNoticeTimer = null;
    updateNotice.value = "";
    // 正文消失时 title 的上下文也要跟着走，否则 hover 空白处仍弹出旧原因
    updateNoticeDetail.value = "";
  }, NOTICE_AUTO_HIDE_MS);
}

async function restoreWindowGeometry() {
  try {
    const win = getCurrentWindow();
    // 单位统一为逻辑像素（dip）：
    // tauri.conf.json 的 minWidth/minHeight 是逻辑单位，若这里传
    // PhysicalSize（物理像素），运行时 setMinSize 会覆盖 conf，
    // 150% 缩放下真实最小窗口远小于设计值（700 物理像素 = 466 dip）。
    await win.setMinSize(new LogicalSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT));

    const saved = localStorage.getItem(GEOMETRY_KEY);
    if (!saved) return;

    const geo = JSON.parse(saved) as Record<string, unknown>;
    // 严格校验：原先用 !width 判断，"abc" 能通过检查，随后
    // Math.max("abc", 700) 得到 NaN，setSize(invoke) 失败被吞，
    // 且 adjusted 回写在 setSize 之后 —— 损坏值永久留在 localStorage，
    // 每次启动重试重失败。
    const nums = [geo.width, geo.height, geo.x, geo.y];
    if (!nums.every((v) => typeof v === "number" && Number.isFinite(v))) {
      console.warn("窗口几何数据损坏，已清除记忆位置");
      localStorage.removeItem(GEOMETRY_KEY);
      return;
    }
    let { width, height, x, y } = geo as unknown as {
      width: number;
      height: number;
      x: number;
      y: number;
    };
    if (width <= 0 || height <= 0) return;

    let adjusted = false;

    // 先钳到硬下限：否则小尺寸记忆会把窗口恢复成布局崩坏的状态
    if (width < MIN_WINDOW_WIDTH || height < MIN_WINDOW_HEIGHT) {
      width = Math.max(width, MIN_WINDOW_WIDTH);
      height = Math.max(height, MIN_WINDOW_HEIGHT);
      adjusted = true;
    }

    // 对照所有显示器裁剪（仅认主屏会把副屏位置每次拉回主屏居中）
    const monitors = await availableMonitors();
    if (monitors.length === 0) return;

    const MIN_OVERLAP_X = 100;
    const MIN_OVERLAP_Y = 50;
    let target = monitors.find((m) => {
      const overlapX = Math.max(0, Math.min(x + width, m.position.x + m.size.width) - Math.max(x, m.position.x));
      const overlapY = Math.max(0, Math.min(y + height, m.position.y + m.size.height) - Math.max(y, m.position.y));
      return overlapX >= MIN_OVERLAP_X && overlapY >= MIN_OVERLAP_Y;
    });

    if (!target) {
      // 所有显示器上都几乎不可见（拔屏/极端坐标）→ 主屏居中
      const primary = (await primaryMonitor()) ?? monitors[0];
      target = primary;
      x = primary.position.x + (primary.size.width - width) / 2;
      y = primary.position.y + (primary.size.height - height) / 2;
      adjusted = true;
    }

    const clampedW = Math.min(width, target.size.width);
    const clampedH = Math.min(height, target.size.height);
    if (clampedW !== width || clampedH !== height) {
      width = clampedW;
      height = clampedH;
      adjusted = true;
    }
    const maxX = target.position.x + target.size.width - width;
    const maxY = target.position.y + target.size.height - height;
    const clampedX = Math.min(Math.max(x, target.position.x), Math.max(target.position.x, maxX));
    const clampedY = Math.min(Math.max(y, target.position.y), Math.max(target.position.y, maxY));
    if (clampedX !== x || clampedY !== y) {
      x = clampedX;
      y = clampedY;
      adjusted = true;
    }

    await win.setSize(new LogicalSize(width, height));
    // setPosition 语义是窗口外框原点，保存端必须同样存 outerPosition（曾因存客户区坐标每次漂移 +9/+38px）
    await win.setPosition(new PhysicalPosition(x, y));

    if (adjusted) {
      localStorage.setItem(GEOMETRY_KEY, JSON.stringify({ width, height, x, y }));
    }
  } catch (e) {
    console.error("恢复窗口几何失败:", e);
  }
}

async function saveWindowGeometry() {
  try {
    const win = getCurrentWindow();
    // 用 scaleFactor 换算成逻辑像素（dip）保存，与 restore 端的
    // LogicalSize 以及 conf 的 minWidth/minHeight 同单位。
    // 原先存 innerSize() 的物理像素却拿去和逻辑常量比较，
    // 150% 缩放时方向相反，既不会被钳制又低于 UI 设计最小可用尺寸。
    const size = await win.innerSize();
    const pos = await win.outerPosition();
    const scale = await win.scaleFactor();
    localStorage.setItem(GEOMETRY_KEY, JSON.stringify({
      width: Math.round(size.width / scale),
      height: Math.round(size.height / scale),
      x: pos.x,
      y: pos.y,
    }));
  } catch (e) {
    console.error("保存窗口几何失败:", e);
  }
}

function updateTheme() {
  if (darkMode.value) {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }
}

/** 主题切换：用浏览器原生的 View Transitions API 做「揭示」。
 *
 *  **为什么不再手写「挂过渡类 → 改类 → 等结束摘类」**（2026-10-09 重构）：
 *  那套写法实测反复出问题，且每一次都只能修掉表面症状：
 *    ① 挂类与改变量同帧 → 没有可插值的起始值，全部瞬变；
 *    ② 改用 requestAnimationFrame 延后 → **仍然同帧**（实测两次 class
 *       变化只隔 0.6ms，而一帧 21ms）；
 *    ③ 改用「强制读计算样式」→ 过渡确实发生了，但固定 280ms 摘类会在
 *       过渡中途截断，颜色被强行拉向终值；
 *    ④ 改用 transitionend → **更糟**：该事件为每个元素、每个属性各触发
 *       一次，第一个到达就摘类，把还在跑的过渡截断 —— 用户看到的是
 *       **「闪烁两次」**（实测曲线在 t=260ms 与 t=530ms 各掉回一次）。
 *  根因是这套机制要手工协调「全树元素的过渡时长」，而元素的时长本就
 *  不一致（按钮 150ms、主题过渡 220ms、进度条 400ms），且摘类这个动作
 *  本身又会改变 transition 声明、触发第二轮过渡。**结构上无法做对。**
 *
 *  View Transitions 把这层交给浏览器：它给旧状态拍一张快照、新状态拍一张，
 *  然后在两张之间做过渡。没有「挂类/摘类」，也就没有「哪个元素先变」的问题。
 *
 *  **⚠ 但交叉淡变本身在浅↔深之间不可用**（2026-10-10 逐帧实测推翻）：
 *  两套主题各以 50% 叠加时，背景（浅 #FFF → 深 #1A1A1A）与文字
 *  （深 #111 → 浅 #EEE）会在中点相遇 —— bg ≈ #8C8C8C、text ≈ #7F7F7F，
 *  对比度掉到约 **1.03:1**，实测帧里整屏是一片灰糊、按钮文字几乎看不见。
 *  这正是用户报的「部分字会闪烁」。**数学上无解**：只要背景与前景同时插值，
 *  它们必然在某一时刻亮度相等。所以最终改成**揭示**（旧快照不动、
 *  新快照 clip-path 圆形展开），每个像素任一时刻只显示一套主题 —— 见 style.css。
 *
 *  **一次测量教训（必须记住）**：我最初验证这个改动时，测的是
 *  「body 背景亮度是否单调」（22 个中间值、无反转 → 判定通过），
 *  但**用户抱怨的是文字**。测「背景单调」根本证明不了「文字可读」——
 *  背景可以完美单调，而文字在同一时刻已经和背景同亮度了。
 *  **验证观感问题时，必须测用户实际抱怨的那个对象，而不是它旁边那个好测的。**
 *
 *  **实测数据**（真实 exe + Edge 152 WebView2，CDP 抓帧）：
 *    * `document.startViewTransition` 可用；
 *    * 连抓 13 帧检查视口四角与中心的亮度差，**未发现边缘闪白**
 *      （视口边缘闪白这一疑点至此实测排除）。
 *
 *  **降级**：仅「API 不可用（老 WebView2）」时直接切 ——
 *  与 MDN 的官方示例一致（先判 `document.startViewTransition` 是否存在）。
 *  系统「减少动态效果」不触发降级，见函数内注释。 */
function applyThemeWithTransition(next: boolean) {
  // 同步记下「请求切到哪」：`startViewTransition` 的回调是**异步**跑的，
  // 连点两次时第二次读 `darkMode.value` 还是旧值 → 两次算出的 next 相同 →
  // 只切了一次（双击看起来像没反应）。`toggleTheme` 用这个值当基准。
  themeRequested = next;

  const applyNow = () => {
    darkMode.value = next;
    updateTheme();
  };

  // 降级路径：老 WebView2 没有 View Transitions API 时直接切
  // （与 MDN 的官方示例一致，先判 `document.startViewTransition` 是否存在）。
  //
  // **刻意不因「系统减少动态效果」而降级**（2026-10-13 用户明确要求）：
  // 圆形揭示是本项目唯一的大幅动效，且它从用户刚点的那个按钮扩散开 ——
  // 是有明确指向性的视觉反馈，不是装饰。系统那个开关针对的是
  // 「满屏乱飞 / 大幅位移」那类动效，把一个 220ms 的定点揭示也关掉属于
  // 过度降级：用户得到的是「点了主题按钮、屏幕硬闪一下」。
  // 真要为它降级的话，判据应该是「本次切换的位移距离」，而不是系统开关。
  if (typeof document.startViewTransition !== "function") {
    applyNow();
    return;
  }

  // 从这里起才置「进行中」：上面的降级分支不产生 VT、也就不会冻结命中测试，
  // 提前置位会让按钮永久停在禁用态（finally 没有对应的 finished 来摘）。
  themeTransitioning.value = true;

  // **回调必须 await 到 Vue 把 DOM 更新完**：`startViewTransition` 会等回调返回的
  // promise 落定之后才拍「新快照」，而 Vue 的组件更新是**微任务**（`nextTick`）。
  // 不 await 的话新快照可能仍是旧状态 —— 具体表现是标题栏那个日/月图标
  // （`TitleBar` 的 `:dark="darkMode"`）在整段揭示动画里显示旧图标，
  // 动画结束后才「啪」地翻过来。
  // 圆心对齐标题栏的主题按钮：写死的百分比在窗口尺寸变化、或按钮位置被
  // 调整之后就会偏，而「揭示从哪一点扩散」是这段动效的全部观感来源。
  // 拿不到按钮元素时保留 CSS 里的兜底值。
  const themeToggle = document.querySelector<HTMLElement>("[data-theme-toggle]");
  if (themeToggle) {
    const rect = themeToggle.getBoundingClientRect();
    const origin = document.documentElement.style;
    origin.setProperty(
      "--vt-origin-x",
      `${(((rect.left + rect.width / 2) / window.innerWidth) * 100).toFixed(2)}%`,
    );
    origin.setProperty(
      "--vt-origin-y",
      `${(((rect.top + rect.height / 2) / window.innerHeight) * 100).toFixed(2)}%`,
    );
  }

  document.startViewTransition(async () => {
    applyNow();
    await nextTick();
    // finished 在过渡被 skip/abort 时会 reject，而 .finally() 返回的新 promise
    // 会沿用这个 reject —— 不 catch 就是一条未处理的 promise rejection
    // （本项目日志门禁会把 console.error 记进日志流）。
  }).finished.catch(() => undefined).finally(() => {
    themeTransitioning.value = false;
  });
}
function toggleTheme() {
  themeFollowSystem.value = false;
  // 基准值取「上一次**请求**切到的主题」而不是 `darkMode.value`：
  // 后者在过渡回调跑完之前仍是旧值（见 applyThemeWithTransition 的说明）。
  const next = !(themeRequested ?? darkMode.value);
  // saveTheme 必须在 applyThemeWithTransition **之前**用算好的 next 落盘：
  // applyThemeWithTransition 把 darkMode.value 的赋值推迟到了过渡回调里
  // （startViewTransition 的回调是异步调用的），所以在它之后读
  // darkMode.value 拿到的仍是**旧值** —— 那会把主题存反，下次启动
  // applySavedTheme 读到反的主题，表现为「切到浅色、重启变深色」。
  saveTheme(next ? "dark" : "light");
  applyThemeWithTransition(next);
}

/** 跟随系统主题变化。
 *
 *  监听交给 usePreferredDark（内部走 matchMedia 的 change 事件，**不是轮询**）：
 *  更早的实现是 5 秒 setInterval 轮询，用户在系统里切主题后最长 5 秒才跟上。
 *
 *  从手写的 start/stopSystemThemeWatch 换成 watch：清理由 Vue 托管，
 *  不再有「忘了卸监听」或「重复装监听」的可能，也就不需要那对函数了。 */
watch(systemDark, (isDark) => {
  // 用户手动选过主题就不再跟随（与轮询版的判据一致）
  if (!themeFollowSystem.value) return;
  // 跟随系统变化也走过渡：否则用户在系统里切主题、本程序却是硬切
  applyThemeWithTransition(isDark);
});

async function handleQrSuccess(cookie: string) {
  qrError.value = "";
  try {
    const account = await accountsStore.addAccount(cookie);
    if (account) {
      selectedAccountId.value = account.id;
    }
  } catch (e) {
    // 不能用 alert()：WebView2 里它是阻塞式 modal，弹出后窗口停止响应
    // 指针事件，「备注」「删除」全部点不动，唯一出路是杀进程。
    // 这个串会经 QrLoginDialog 的 addError prop 直接渲染给用户，
    // 所以必须走 formatIpcError（否则露出 Rust 命令名与超时秒数）。
    qrError.value = formatIpcError(e, "添加账号失败");
    showQrLogin.value = true;
  }
}

function selectAccount(accountId: string) {
  selectedAccountId.value = accountId;
}

/* ---------------- 侧栏宽度（可拖拽） ---------------- */

/** 侧栏宽度上下限。
 *  **没有图标条模式**：曾加过「拖窄折叠成 52px 图标条」，用户明确取消后
 *  彻底删除（`SIDEBAR_RAIL` / `SIDEBAR_COLLAPSE_AT` / `toggleSidebar` /
 *  `pendingSidebarCollapse` 与 AccountList 的 `collapsed` 分支全部随之移除）。
 *  取消后拖拽语义回归单一：宽度 = 松手时的面板宽度，夹在 [200, 420]。
 *
 *  三个常量以 `size-unit="px"` 交给 reka 的 Splitter：它的 px 模式在组尺寸
 *  变化时会重算百分比以**保持像素不变**（reka-ui 的 utils/units.js
 *  `recalculateLayoutForPixelPanels`），语义与原先手写的 `width: Npx` 一致 ——
 *  窗口拉宽时侧栏不会跟着变宽。 */
const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 420;
const SIDEBAR_DEFAULT = 240;
const SIDEBAR_KEY = "ui/sidebar_width";

const sidebarWidth = ref(SIDEBAR_DEFAULT);
/** 侧栏面板元素。宽度不再由我们写内联 style 决定 —— Splitter 拥有布局，
 *  我们只把它的实际宽度镜像回来。 */
const sidebarEl = ref<HTMLElement | null>(null);

function loadSidebarWidth() {
  try {
    const raw = localStorage.getItem(SIDEBAR_KEY);
    if (!raw) return;
    const n = Number(raw);
    if (!Number.isFinite(n)) {
      localStorage.removeItem(SIDEBAR_KEY);
      return;
    }
    // 图标条模式取消前的遗留值是 0（当时用它表示「已折叠」）。
    // 直接夹到 SIDEBAR_MIN 会让用户莫名其妙得到一条 200px 的窄侧栏，
    // 而 0 本身已不是任何有效状态 —— 归到默认值并顺手清掉。
    if (n <= 0) {
      localStorage.removeItem(SIDEBAR_KEY);
      return;
    }
    sidebarWidth.value = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, n));
  } catch {
    /* localStorage 不可用时用默认值即可，不阻塞 UI */
  }
}

// **必须在 setup 阶段读，不能留在 onMounted**：SplitterPanel 的 `default-size`
// 只在面板注册时读一次，等挂载后再改 sidebarWidth 已经晚了（面板会停在默认宽）。
loadSidebarWidth();

/** 把 Splitter 的实际宽度镜像回 sidebarWidth。
 *
 *  鼠标拖拽与键盘调整（SplitterResizeHandle 自带方向键支持）都会改 flex
 *  布局，两条路径都由 ResizeObserver 收口 —— 比监听 reka 的 resize 事件更可靠，
 *  也不必去猜它 emit 出来的尺寸是什么单位。 */
useResizeObserver(sidebarEl, (entries) => {
  const width = entries[0]?.contentRect.width;
  if (width) sidebarWidth.value = Math.round(width);
});

/** 拖拽中按节流写入：拖拽每秒可触发上百次。
 *
 *  watchThrottled 是「最多每 16ms 一次 + 尾沿补一次」：比原先的
 *  requestAnimationFrame 合并多一次尾沿写，保证松手后最后那个宽度一定落盘，
 *  也因此不需要在拖拽结束处再显式写一次。 */
watchThrottled(
  sidebarWidth,
  (width) => {
    try {
      localStorage.setItem(SIDEBAR_KEY, String(Math.round(width)));
    } catch {
      /* 忽略写入失败 */
    }
  },
  { throttle: 16 },
);
</script>

<template>
  <div class="flex h-screen flex-col overflow-hidden bg-background text-foreground">
    <!-- 自绘标题栏（配合 decorations:false）。原本的顶栏信息已并入其中 -->
    <TitleBar
      :running-count="runningCount"
      :dark="darkMode"
      :checking-update="checkingUpdate"
      :update-notice="updateNotice"
      :update-notice-detail="updateNoticeDetail"
      :update-notice-error="updateNoticeError"
      :theme-transitioning="themeTransitioning"
      @toggle-theme="toggleTheme"
      @check-update="checkUpdate(true)"
    />

    <!-- 主内容：左栏可拖拽宽度 + 右栏网格。
         宽度分割交给 reka 的 Splitter（而不是手写 pointerdown + window 级
         move/up）：它自带命中区域、拖拽光标、键盘调整与边界钳制，
         px 模式又保证侧栏是固定像素宽而不是随窗口缩放。 -->
    <main class="flex min-h-0 flex-1">
      <SplitterGroup direction="horizontal" class="min-h-0 min-w-0 flex-1">
        <!-- 账号列表：宽度由 Splitter 管理，space-x 由侧栏内部自行管理 -->
        <SplitterPanel
          :size-unit="'px'"
          :min-size="SIDEBAR_MIN"
          :max-size="SIDEBAR_MAX"
          :default-size="sidebarWidth"
          as-child
        >
          <div ref="sidebarEl" class="relative min-h-0 border-r border-border">
            <AccountList
              :selected-id="selectedAccountId"
              @select="selectAccount"
              @qr-login="showQrLogin = true"
            />
          </div>
        </SplitterPanel>

        <!-- 拖拽把手：视觉仍是窄竖条，但命中区域由 reka 的 hitAreaMargins
             撑开（默认 15/5px），比手写版更容易抓住；hover 与拖拽态读它
             暴露的 data-resize-handle-state，不再需要本地 resizing 布尔。

             focus-visible 的 ring 不能省：SplitterResizeHandle 是 role="slider"
             且自带 tabindex，键盘方向键就能调宽 —— 这是把手换成 reka 组件后
             **唯一新增的能力**（手写版只响应鼠标）。它若不显示焦点，用户按 Tab
             走到这里看不出焦点在哪，等于新增能力不可发现。配色沿用主题按钮那一套
             ring token；用 inset 是因为把手只有 6px 宽，外扩的 ring 会盖住相邻面板。 -->
        <SplitterResizeHandle
          class="z-10 w-1.5 cursor-col-resize transition-colors
                 hover:bg-signal-info/40 data-[resize-handle-state=drag]:bg-signal-info/60
                 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset
                 focus-visible:ring-ring"
          aria-orientation="vertical"
          aria-label="拖拽调整账号栏宽度"
          :aria-valuenow="Math.round(sidebarWidth)"
          :aria-valuemin="SIDEBAR_MIN"
          :aria-valuemax="SIDEBAR_MAX"
        />

      <!-- 右栏：配置 / 挂宝进度 / 日志。用 grid 而非单列 flex ——
           单列时三块内容天然均分高度，日志一展开就把任务进度压扁。

           前两行按内容取高（`auto`），**第三行 `1fr` 吃掉全部剩余高度**
           给日志面板。窗口有多高，日志面板就有多高、日志行数自动变多，
           任何窗口高度下都不会出现「日志卡下方空一块」。

           为什么只能给日志面板：三张卡的内容高度都是固定的
           （配置 293 + 挂宝 350 + 日志卡头与内边距 ~120），
           窗口比它们的总和高出来的部分必须有容器去接，不接就是空白。
           挂宝进度的任务区不能接（接了就是你报过两轮的
           「挂宝进度下方大量空白」——它是有限内容的列表框）；
           配置卡更不能接（固定内容 + 下方一大片留白，最难看）。
           日志面板是唯一「内容多少都合理」的流式区域，
           它内部的空档与 VSCode 控制台同构，看不出是布局 bug。

           content-start 仍需保留：内容**溢出**时（窗口不够高）它让轨道
           从顶部开始排布而不是被拉伸压缩，日志卡因此永远从任务卡下沿
           开始、只向下延伸，不会出现「展开日志时日志卡整体上移」。 -->
        <SplitterPanel class="min-h-0 min-w-0">
          <!-- SplitterPanel 会给自己挂一条 inline 的 overflow: hidden
               （reka 的 computePanelFlexBoxStyle 硬编码），inline 优先于 class，
               所以滚动不能写在面板自己身上 —— 交给里面这一层，与 Splitter 解耦。 -->
          <div
            class="grid h-full min-h-0 scroll-hidden content-start grid-rows-[auto_auto_1fr]
                   gap-2.5 overflow-y-auto p-2.5"
          >
            <ConfigForm class="row-span-1" />

            <TaskProgress
              class="row-span-1"
              :account-id="selectedAccountId"
              :running="selectedAccount?.running ?? false"
              :remark="selectedAccount?.remark ?? ''"
            />

            <LogViewer class="row-span-1" />
          </div>
        </SplitterPanel>
      </SplitterGroup>
    </main>

    <!-- 全局右键策略的唯一属主：吞掉 WebView2 原生菜单，只在输入框上
         给出撤销/复制/粘贴/粘贴为纯文本/全选。挂在模板里是为了让它在整个
         应用生命周期内常驻（它靠 Teleport 渲染，不需要 Trigger 锚点）。 -->
    <InputContextMenu />

    <!-- 扫码登录对话框 -->
    <QrLoginDialog
      :open="showQrLogin"
      :add-error="qrError"
      @update:open="showQrLogin = $event"
      @success="handleQrSuccess"
    />

    <!-- 更新对话框 -->
    <UpdateDialog
      v-model:open="showUpdateDialog"
      :latest-version="updateLatestVersion"
      :release-url="updateReleaseUrl"
    />

    <!-- 运行中阻止关闭的模态提示 -->
    <ConfirmDialog
      :open="showCloseBlocked"
      title="暂不能关闭"
      message="存在正在运行或正在停止的挂宝账号，请等待其完全停止后再关闭窗口。"
      confirm-text="知道了"
      :show-cancel="false"
      @update:open="showCloseBlocked = $event"
      @confirm="showCloseBlocked = false"
      @cancel="showCloseBlocked = false"
    />

    <!-- 关闭时配置保存失败：必须告知用户。
         原实现只有 console.error，窗口照常销毁，用户以为配置已保存。
         关闭链路的 stashConfigLocally() 已经把编辑写进 localStorage，
         下次启动会恢复；但用户此刻也需要知道发生了什么。 -->
    <ConfirmDialog
      :open="configSaveFailed !== ''"
      title="配置未保存"
      :message="`保存配置失败：${configSaveFailed}。程序仍将继续关闭，但你本次的编辑已存为本地快照，下次启动会恢复。`"
      confirm-text="知道了"
      :show-cancel="false"
      @update:open="configSaveFailed = ''"
      @confirm="configSaveFailed = ''"
      @cancel="configSaveFailed = ''"
    />
  </div>
</template>

