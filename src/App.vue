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
import QrLoginDialog from "@/components/QrLoginDialog.vue";
import UpdateDialog from "@/components/UpdateDialog.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import { Button } from "@/components/ui/button";

const accountsStore = useAccountsStore();
const configStore = useConfigStore();
const logsStore = useLogsStore();

const darkMode = ref(false);
const showQrLogin = ref(false);
const themeFollowSystem = ref(true);
let themePollTimer: number | null = null;

const THEME_KEY = "ui/theme";

/** 窗口硬下限：防布局崩坏。
 *  宽度 700 = 新版 UI 实测 min-content 675 + 余量（675 起「任务 ID」行两个
 *  「自动获取」按钮会溢出 11px，660 溢出 22px；实测见第六轮记录）。
 *  高度 480：右列自带 overflow-y-auto，低于内容自然高度只是出滚动条，不会崩，
 *  故取比旧版 minimumSizeHint(582, 含窗框) 更宽松的值。
 *  必须与 src-tauri/tauri.conf.json 的 minWidth/minHeight 同源。 */
const MIN_WINDOW_WIDTH = 700;
const MIN_WINDOW_HEIGHT = 480;

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
// 旧版是 QListWidget 的 currentRow（account_panel.py:112-116），删除后 currentRow
// 变 -1 而 current_account_id() 返回 None，按钮随之禁用；重构版此前用 App.vue 的本地
// ref，与 store 里的 selectedAccountId 形成双源，删除后残留孤儿 id 导致底部
// 「备注/删除」仍可点击。
const selectedAccountId = computed<string | null>({
  get: () => accountsStore.selectedAccountId,
  set: (id) => {
    accountsStore.selectedAccountId = id;
  },
});

// 复刻旧版 set_accounts 的选中联动（account_panel.py:100-105）：
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

  startSystemThemePolling();
  startConfigSync();
  startTaskRefresh();
  updateTimer = window.setTimeout(() => void checkUpdate(), 3000);
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
      // 旧版行为（main_window.py:980-992）：有运行中/停止中账号 → 警告并阻止
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
        // 旧版行为（main_window.py:1011-1015）：仅告警仍继续关闭，不阻塞
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

async function checkUpdate() {
  try {
    const result = await invoke<{
      update_available: boolean;
      latest_version: string;
      release_url: string;
    }>("check_update");
    if (result.update_available) {
      updateLatestVersion.value = result.latest_version;
      updateReleaseUrl.value = result.release_url;
      showUpdateDialog.value = true;
    }
  } catch {
  }
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
  try {
    const account = await accountsStore.addAccount(cookie);
    if (account) {
      selectedAccountId.value = account.id;
    }
  } catch (e) {
    alert(`添加账号失败: ${e}`);
  }
}

function selectAccount(accountId: string) {
  selectedAccountId.value = accountId;
}
</script>

<template>
  <div class="flex h-screen flex-col overflow-hidden bg-background px-[14px] pb-3 pt-3 text-foreground">
    <!-- 顶栏（对齐旧版：无边框、不粘顶、无全局进度条；进度条移至配置卡底部） -->
    <header class="mb-2.5 flex shrink-0 items-center gap-3">
      <h1 class="text-[14pt] font-bold">守望先锋直播掉宝助手</h1>
      <span class="text-[10pt] text-muted-foreground">
        {{ anyRunning ? `已运行账号数量: ${runningCount}` : "未运行任何账号" }}
      </span>
      <div class="flex-1"></div>
      <Button variant="outline" size="sm" @click="toggleTheme">切换主题</Button>
    </header>

    <!-- 主内容：左栏 240px 固定 + 右栏独立滚动（窗口 800 下无竖向滚动条） -->
    <main class="flex min-h-0 flex-1 gap-2.5">
      <!-- 账号列表 -->
      <div class="w-60 shrink-0">
        <AccountList
          :selected-id="selectedAccountId"
          @select="selectAccount"
          @qr-login="showQrLogin = true"
        />
      </div>

      <!-- 配置、任务进度和日志（仅此列滚动） -->
      <div class="flex min-h-0 min-w-0 flex-1 flex-col gap-2.5 overflow-y-auto pr-1">
        <ConfigForm />

        <!-- 任务进度（常驻：未选中/账号已删时传 null 显示占位，对齐旧版 task_card）
           min-h-[230px] 是保底高度，不是随意取值：卡片内容为
           header 约 45px + 进度条 20px（含 margin）+ 任务区 min-h 140px + 内边距。
           写 min-h-0 时，展开运行日志会把它压到只剩 header 一行 ——
           任务区整块消失、进度条被裁一半，看上去就是「按钮与日志重叠」。
           给保底高度后，空间不足时压不动本卡，转而由右列 overflow-y-auto
           出滚动条（实测修复后卡片 230px、任务区完整可见、无溢出）。 -->
        <TaskProgress
          class="flex min-h-[230px] flex-1 flex-col"
          :account-id="selectedAccountId"
          :running="selectedAccount?.running ?? false"
          :remark="selectedAccount?.remark ?? ''"
        />

        <!-- 日志查看器 -->
        <LogViewer />
      </div>
    </main>

    <!-- 扫码登录对话框 -->
    <QrLoginDialog
      :open="showQrLogin"
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

