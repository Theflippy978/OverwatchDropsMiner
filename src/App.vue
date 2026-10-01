<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from "vue";
import { getCurrentWindow, primaryMonitor, PhysicalSize, PhysicalPosition } from "@tauri-apps/api/window";
import { invoke } from "@tauri-apps/api/core";
import { useAccountsStore } from "@/stores/accounts";
import { useConfigStore } from "@/stores/config";
import { useLogsStore } from "@/stores/logs";
import { useTasksStore } from "@/stores/tasks";
import AccountList from "@/components/AccountList.vue";
import ConfigForm from "@/components/ConfigForm.vue";
import LogViewer from "@/components/LogViewer.vue";
import TaskProgress from "@/components/TaskProgress.vue";
import NotificationSettings from "@/components/NotificationSettings.vue";
import QrLoginDialog from "@/components/QrLoginDialog.vue";
import UpdateDialog from "@/components/UpdateDialog.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";

const accountsStore = useAccountsStore();
const configStore = useConfigStore();
const logsStore = useLogsStore();

const darkMode = ref(false);
const selectedAccountId = ref<string | null>(null);
const showQrLogin = ref(false);
const themeFollowSystem = ref(true);
let themePollTimer: number | null = null;

const THEME_KEY = "ui/theme";

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

const anyRunning = computed(() =>
  accountsStore.accounts.some((a) => a.running)
);

onMounted(async () => {
  await logsStore.initListeners();
  await accountsStore.initListeners();
  await accountsStore.fetchAccounts();
  await configStore.ensureLoaded();

  const savedTheme = getSavedTheme();
  if (savedTheme === "dark" || savedTheme === "light") {
    darkMode.value = savedTheme === "dark";
    themeFollowSystem.value = false;
  } else {
    darkMode.value = detectSystemTheme();
  }
  updateTheme();
  startSystemThemePolling();
  restoreWindowGeometry();
  registerCloseHandler();
  startConfigSync();
  startTaskRefresh();
  setTimeout(() => checkUpdate(), 3000);
});

onUnmounted(() => {
  stopSystemThemePolling();
  stopConfigSync();
  stopTaskRefresh();
  accountsStore.dispose();
  logsStore.dispose();
});

let closeHandlerRegistered = false;
let configSyncTimer: number | null = null;

/** 关闭路径专用：带超时的 invoke，超时/失败一律返回 null，绝不阻塞窗口销毁 */
function invokeBounded<T>(command: string, timeoutMs: number): Promise<T | null> {
  return new Promise((resolve) => {
    let done = false;
    const finish = (value: T | null) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      resolve(value);
    };
    const timer = window.setTimeout(() => finish(null), timeoutMs);
    invoke<T>(command).then(finish, () => finish(null));
  });
}

function registerCloseHandler() {
  if (closeHandlerRegistered) return;
  closeHandlerRegistered = true;
  const win = getCurrentWindow();
  win.onCloseRequested(async (event) => {
    // 统一由本流程控制关闭：先阻止默认行为，最后一定 destroy
    event.preventDefault();
    if (anyRunning.value) {
      // 旧版行为（main_window.py:980-992）：有运行中/停止中账号 → 警告并阻止
      showCloseBlocked.value = true;
      return;
    }
    try {
      await Promise.race([
        configStore.save(),
        new Promise((_, reject) => setTimeout(() => reject(new Error("保存超时")), 5000)),
      ]);
    } catch (e) {
      console.error("保存会话配置失败", e);
    }
    try {
      await saveWindowGeometry();
    } catch (e) {
      console.error("保存窗口几何失败", e);
    }
    await invokeBounded("qr_cancel", 1000);
    const r = await invokeBounded<{ closed: boolean }>("shutdown", 6000);
    if (r && r.closed === false) {
      // 旧版行为（main_window.py:1011-1015）：仅告警仍继续关闭，不阻塞
      console.warn("浏览器嗅探线程未在预算时间内退出，浏览器/驱动进程可能残留，请手动检查任务管理器。");
      logsStore.addLog({
        timestamp: new Date().toISOString(),
        account_id: null,
        level: "warning",
        message: "关闭时浏览器嗅探线程未在预算时间内退出，进程可能残留，请检查任务管理器",
      });
    }
    try {
      await win.destroy();
    } catch (e) {
      console.error("销毁窗口失败，重试一次", e);
      await win.destroy().catch(() => {});
    }
  });
}

function startConfigSync() {
  if (configSyncTimer !== null) return;
  configSyncTimer = window.setInterval(() => {
    if (!anyRunning.value) return;
    invoke("sync_config_to_miners").catch(() => {});
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
    const saved = localStorage.getItem("window_geometry");
    if (saved) {
      const geo = JSON.parse(saved);
      const win = getCurrentWindow();
      const primary = await primaryMonitor();

      let { width, height, x, y } = geo;
      let adjusted = false;

      if (primary) {
        const pPos = primary.position;
        const pSize = primary.size;
        const overlapX = Math.max(0, Math.min(x + width, pPos.x + pSize.width) - Math.max(x, pPos.x));
        const overlapY = Math.max(0, Math.min(y + height, pPos.y + pSize.height) - Math.max(y, pPos.y));

        if (overlapX < 100 || overlapY < 50) {
          x = pPos.x + (pSize.width - width) / 2;
          y = pPos.y + (pSize.height - height) / 2;
          adjusted = true;
        }

        width = Math.min(width, pSize.width);
        height = Math.min(height, pSize.height);
      }

      if (width && height) {
        await win.setSize(new PhysicalSize(width, height));
      }
      if (x !== undefined && y !== undefined) {
        await win.setPosition(new PhysicalPosition(x, y));
      }

      if (adjusted) {
        localStorage.setItem("window_geometry", JSON.stringify({ width, height, x, y }));
      }
    }
    const win = getCurrentWindow();
    await win.setMinSize(new PhysicalSize(800, 600));
  } catch (e) {
    console.error("恢复窗口几何失败:", e);
  }
}

async function saveWindowGeometry() {
  try {
    const win = getCurrentWindow();
    const size = await win.innerSize();
    const pos = await win.innerPosition();
    localStorage.setItem("window_geometry", JSON.stringify({
      width: size.width,
      height: size.height,
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
  <div class="bg-background text-foreground">
    <!-- 顶栏 -->
    <header class="sticky top-0 z-10 border-b border-border bg-card/95 backdrop-blur">
      <div class="container mx-auto flex h-14 items-center justify-between px-4">
        <h1 class="text-lg font-bold">守望先锋直播掉宝助手</h1>
        <div class="flex items-center gap-3">
          <span class="text-sm text-muted-foreground">
            {{ accountsStore.accounts.filter((a) => a.running).length }} 个账号运行中
          </span>
          <div class="group relative">
            <button
              class="rounded-md p-2 hover:bg-accent transition-colors"
              :title="themeFollowSystem ? '当前跟随系统主题' : '已手动切换主题'"
              @click="toggleTheme"
            >
              {{ darkMode ? "☀️" : "🌙" }}
            </button>
            <div class="pointer-events-none absolute right-0 top-full z-50 mt-1 w-48 rounded-md border border-border bg-popover p-2 text-xs text-popover-foreground opacity-0 shadow-md transition-opacity group-hover:opacity-100">
              {{ themeFollowSystem ? "当前跟随系统主题" : "已手动切换主题" }}
              <br />
              点击切换深/浅色模式
            </div>
          </div>
        </div>
      </div>
      <!-- 运行中全局 indeterminate 进度动画 -->
      <div
        v-if="anyRunning"
        class="relative h-1.5 w-full overflow-hidden bg-secondary"
      >
        <div class="progress-indeterminate absolute h-full w-1/3 bg-primary" />
      </div>
    </header>

    <!-- 主内容 -->
    <main class="container mx-auto p-4">
      <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <!-- 账号列表 -->
        <div class="lg:col-span-1">
          <AccountList
            :selected-id="selectedAccountId"
            @select="selectAccount"
            @qr-login="showQrLogin = true"
          />
        </div>

        <!-- 配置、任务进度和日志 -->
        <div class="space-y-4 lg:col-span-2">
          <ConfigForm />
          <NotificationSettings />
          
          <!-- 任务进度 -->
          <TaskProgress
            v-if="selectedAccountId && accountsStore.accounts.some((a) => a.id === selectedAccountId)"
            :account-id="selectedAccountId"
            :running="accountsStore.accounts.find((a) => a.id === selectedAccountId)?.running ?? false"
          />

          <!-- 日志查看器 -->
          <LogViewer />
        </div>
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
  </div>
</template>

