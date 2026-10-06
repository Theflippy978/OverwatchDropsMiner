<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from "vue";
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

const accountsStore = useAccountsStore();
const configStore = useConfigStore();
const logsStore = useLogsStore();

const darkMode = ref(false);
const showQrLogin = ref(false);
const qrError = ref("");
const themeFollowSystem = ref(true);
let themePollTimer: number | null = null;

const THEME_KEY = "ui/theme";

/** 窗口硬下限：防布局崩坏。
 *
 *  1030 × 860 是用 CDP 逐档扫描实测出来的，不是估算：
 *  宽度取「侧栏拉满 420 + 右列四区块 min-content 的最大值」，
 *  挂宝进度卡（检查点行 72 / 240 / 163 + 缩进与内边距）实测需要 538，
 *  配置卡 518，取 538。两个必须算进去的额外扣减：
 *   ① **tauri.conf.json 的 minWidth 是外框宽度**，客户区要再减去窗框差
 *      （125% 缩放下实测 14px），所以 conf 要比客户区下限多 14；
 *   ② **最坏情况是任务区正在纵向滚动时** —— `.scroll-subtle` 的 thin
 *      纵向滚动条会再吃掉约 8px 任务区宽度（实测行溢出 8px）。
 *  1030 → 客户区 1016 → 检查点行可用 481 ≥ 所需 477，留 4px 余量。
 *  高度裸下限 851（配置卡 293 + 挂宝卡下限 362 + 日志卡折叠 118
 *  + 行距与内边距 40 + 标题栏 36），取 860 是因为 3 秒自动消失的行内提示
 *  会让配置卡瞬时高约 30px，851/880 下会把挂宝卡挤到下限以下 1~2px。
 *  首次启动尺寸与此相同（tauri.conf.json 的 width/height）。
 *  必须与 src-tauri/tauri.conf.json 的 minWidth/minHeight 同源。 */
const MIN_WINDOW_WIDTH = 1030;
const MIN_WINDOW_HEIGHT = 860;

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

function detectSystemTheme(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
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
    darkMode.value = detectSystemTheme();
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

  loadSidebarWidth();
  window.addEventListener("pointermove", onSidebarResizeMove);
  window.addEventListener("pointerup", onSidebarResizeEnd);
  startSystemThemePolling();
  startConfigSync();
  startTaskRefresh();
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
  if (sidebarPersistHandle !== null) cancelAnimationFrame(sidebarPersistHandle);
  window.removeEventListener("pointermove", onSidebarResizeMove);
  window.removeEventListener("pointerup", onSidebarResizeEnd);
  stopSystemThemePolling();
  stopConfigSync();
  stopTaskRefresh();
  accountsStore.dispose();
  logsStore.dispose();
});

let closeHandlerRegistered = false;
let closing = false;
let configSyncTimer: number | null = null;
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
        configSaveFailed.value = `${e}`;
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

function startConfigSync() {
  if (configSyncTimer !== null) return;
  configSyncTimer = window.setInterval(() => {
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
}

function stopConfigSync() {
  if (configSyncTimer !== null) {
    clearInterval(configSyncTimer);
    configSyncTimer = null;
  }
}

let taskRefreshTimer: number | null = null;

function startTaskRefresh() {
  stopTaskRefresh();
  const interval = Math.max(10, Math.min(3600, parseInt(configStore.config.task_query_interval_text, 10) || 30));
  taskRefreshTimer = window.setInterval(() => {
    const runningAccounts = accountsStore.accounts.filter((a) => a.running);
    for (const account of runningAccounts) {
      void useTasksStore().refreshTasks(account.id, false);
    }
  }, interval * 1000);
}

function stopTaskRefresh() {
  if (taskRefreshTimer !== null) {
    clearInterval(taskRefreshTimer);
    taskRefreshTimer = null;
  }
}

// 「任务查询间隔」改动后立即按新周期重建定时器
watch(
  () => configStore.config.task_query_interval_text,
  () => startTaskRefresh()
);

/**
 * 更新检查。
 *
 * 两条调用路径，只有 force 不同：
 * - 启动 3s 后自动检查（force=false）：受 sidecar 侧 update_channel 门禁约束，
 *   dev 渠道不去打扰 GitHub API（未认证限流 60 次/小时）；无更新时完全静默。
 * - 标题栏按钮手动检查（force=true）：绕过**渠道**门禁真去查一次；结果一律
 *   给用户可见反馈。
 *
 * 注意 force 绕的只是渠道，不是「版本号能不能比较」：版本号必须是可数值比较的
 * 真实版本（`_version.py` 的 `APP_VERSION`，与 tauri.conf.json 同源）。若把它
 * 写成 `0.0.0+dev` 这类占位串，手动检查会被判为无意义比较而直接返回 ——
 * 按钮的菊花与 3 秒提示都正常，却永远显示「已是最新版本」，无从察觉。
 *
 * 单飞行：checkingUpdate 兼作锁。GitHub 未认证 API 限流是 60 次/小时，
 * 连点几下就会开始返回 403，而 403 与「没有新版本」在响应里长得一样，
 * 用户只会看到「已是最新」这种错误结论。
 */
async function checkUpdate(force = false) {
  if (checkingUpdate.value) return;
  checkingUpdate.value = true;
  if (force) showUpdateNotice("正在检查…", false);
  const startedAt = performance.now();
  // 结果提示**不能**在 invoke 返回时就写 —— 本地开发包的 invoke 1~2ms 就返回，
  // 写进去会把「正在检查…」立刻顶掉，用户连一帧都看不到。
  // 所以先攒成一个函数，等 finally 里补足最短可见时长后再调用。
  let announce: (() => void) | null = null;
  try {
    const result = await invoke<{
      update_available: boolean;
      latest_version: string;
      release_url: string;
    }>("check_update", { force });
    if (result.update_available) {
      updateLatestVersion.value = result.latest_version;
      updateReleaseUrl.value = result.release_url;
      showUpdateDialog.value = true;
      // 弹窗才是主反馈，胶囊不再重复提示「发现新版本」
      if (force) {
        announce = () =>
          showUpdateNotice(`发现新版本 ${result.latest_version}`, false);
      }
    } else if (force) {
      announce = () => showUpdateNotice("已是最新版本", false);
    }
  } catch (e) {
    // 自动检查保持静默：启动阶段弹错误只会干扰用户点账号
    if (force) announce = () => showUpdateNotice(`检查失败：${e}`, true);
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
 */
function showUpdateNotice(text: string, isError: boolean) {
  if (updateNoticeTimer !== null) clearTimeout(updateNoticeTimer);
  updateNotice.value = text;
  updateNoticeError.value = isError;
  updateNoticeTimer = window.setTimeout(() => {
    updateNoticeTimer = null;
    updateNotice.value = "";
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

function toggleTheme() {
  themeFollowSystem.value = false;
  darkMode.value = !darkMode.value;
  updateTheme();
  saveTheme(darkMode.value ? "dark" : "light");
  stopSystemThemePolling();
}

function startSystemThemePolling() {
  if (themePollTimer !== null) return;
  themePollTimer = window.setInterval(() => {
    if (!themeFollowSystem.value) return;
    const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    if (systemDark !== darkMode.value) {
      darkMode.value = systemDark;
      updateTheme();
    }
  }, 5000);
}

function stopSystemThemePolling() {
  if (themePollTimer !== null) {
    clearInterval(themePollTimer);
    themePollTimer = null;
  }
}

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
    qrError.value = `添加账号失败: ${e}`;
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
 *  取消后拖拽语义回归单一：宽度 = 松手时的指针位置，夹在 [200, 420]。 */
const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 420;
const SIDEBAR_DEFAULT = 240;
const SIDEBAR_KEY = "ui/sidebar_width";

const sidebarWidth = ref(SIDEBAR_DEFAULT);
const resizingSidebar = ref(false);

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

/** 拖拽中按帧写入：pointermove 每秒可触发上百次 */
let sidebarPersistHandle: number | null = null;
function persistSidebarWidth() {
  if (sidebarPersistHandle !== null) return;
  sidebarPersistHandle = window.requestAnimationFrame(() => {
    sidebarPersistHandle = null;
    try {
      localStorage.setItem(SIDEBAR_KEY, String(Math.round(sidebarWidth.value)));
    } catch {
      /* 忽略写入失败 */
    }
  });
}

function onSidebarResizeMove(event: PointerEvent) {
  if (!resizingSidebar.value) return;
  // 用鼠标 X 减去 root 左边界：不依赖事件落在哪个元素上，
  // 拖出侧栏范围时也不会断
  const rootLeft = document
    .querySelector<HTMLElement>("[data-sidebar-host]")
    ?.getBoundingClientRect().left ?? 0;
  sidebarWidth.value = Math.min(
    SIDEBAR_MAX,
    Math.max(SIDEBAR_MIN, event.clientX - rootLeft)
  );
}

function onSidebarResizeEnd() {
  if (!resizingSidebar.value) return;
  resizingSidebar.value = false;
  document.body.style.cursor = "";
  document.body.style.userSelect = "";
  persistSidebarWidth();
}

function onSidebarResizeStart(event: PointerEvent) {
  // 只响应主键，避免右键/中键也进入拖拽态
  if (event.button !== 0) return;
  resizingSidebar.value = true;
  // 拖拽期间禁用全局光标与选中，否则会选中文本、鼠标在侧栏上变成 text
  document.body.style.cursor = "col-resize";
  document.body.style.userSelect = "none";
  event.preventDefault();
}

const sidebarStyle = computed(() => ({
  width: `${Math.round(sidebarWidth.value)}px`,
}));
</script>

<template>
  <div
    class="flex h-screen flex-col overflow-hidden bg-background text-foreground"
    data-sidebar-host
  >
    <!-- 自绘标题栏（配合 decorations:false）。原本的顶栏信息已并入其中 -->
    <TitleBar
      :running-count="runningCount"
      :dark="darkMode"
      :checking-update="checkingUpdate"
      :update-notice="updateNotice"
      :update-notice-error="updateNoticeError"
      @toggle-theme="toggleTheme"
      @check-update="checkUpdate(true)"
    />

    <!-- 主内容：左栏可拖拽宽度 + 右栏网格 -->
    <main class="flex min-h-0 flex-1">
      <!-- 账号列表：宽度由用户拖拽决定，space-x 由侧栏内部自行管理 -->
      <div
        class="relative shrink-0 border-r border-border"
        :style="sidebarStyle"
      >
        <AccountList
          :selected-id="selectedAccountId"
          @select="selectAccount"
          @qr-login="showQrLogin = true"
        />

        <!-- 拖拽把手：放在侧栏右缘内侧，hover 时高亮 2px 竖条。
             用 pointerdown + window 级 move/up，而不是 HTML5 drag：
             后者无法控制宽度、且拖拽时 iframe/webview 下容易失效。 -->
        <div
          class="group absolute inset-y-0 right-0 z-10 w-1.5 cursor-col-resize
                 transition-colors hover:bg-signal-info/40"
          :class="resizingSidebar ? 'bg-signal-info/60' : ''"
          role="separator"
          aria-orientation="vertical"
          aria-label="拖拽调整账号栏宽度"
          :aria-valuenow="Math.round(sidebarWidth)"
          :aria-valuemin="SIDEBAR_MIN"
          :aria-valuemax="SIDEBAR_MAX"
          tabindex="0"
          @pointerdown="onSidebarResizeStart"
        />
      </div>

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
      <div
        class="grid min-h-0 min-w-0 flex-1 scroll-hidden content-start grid-rows-[auto_auto_1fr]
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

