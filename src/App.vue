<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import { getCurrentWindow, PhysicalSize, PhysicalPosition } from "@tauri-apps/api/window";
import { invoke } from "@tauri-apps/api/core";
import { useAccountsStore } from "@/stores/accounts";
import { useConfigStore } from "@/stores/config";
import { useLogsStore } from "@/stores/logs";
import AccountList from "@/components/AccountList.vue";
import ConfigForm from "@/components/ConfigForm.vue";
import LogViewer from "@/components/LogViewer.vue";
import TaskProgress from "@/components/TaskProgress.vue";
import NotificationSettings from "@/components/NotificationSettings.vue";
import QrLoginDialog from "@/components/QrLoginDialog.vue";

const accountsStore = useAccountsStore();
const configStore = useConfigStore();
const logsStore = useLogsStore();

const darkMode = ref(false);
const selectedAccountId = ref<string | null>(null);
const showQrLogin = ref(false);
const themeFollowSystem = ref(true);
let themePollTimer: number | null = null;

const anyRunning = computed(() =>
  accountsStore.accounts.some((a) => a.running)
);

onMounted(async () => {
  await logsStore.initListeners();
  await accountsStore.initListeners();
  await accountsStore.fetchAccounts();
  await configStore.ensureLoaded();

  darkMode.value = window.matchMedia("(prefers-color-scheme: dark)").matches;
  updateTheme();
  startSystemThemePolling();
  restoreWindowGeometry();
  registerCloseHandler();
  startConfigSync();
});

onUnmounted(() => {
  stopSystemThemePolling();
  stopConfigSync();
});

let closeHandlerRegistered = false;
let configSyncTimer: number | null = null;

function registerCloseHandler() {
  if (closeHandlerRegistered) return;
  closeHandlerRegistered = true;
  const win = getCurrentWindow();
  win.onCloseRequested(async (event) => {
    if (anyRunning.value) {
      event.preventDefault();
      return;
    }
    saveWindowGeometry();
    invoke("shutdown").catch(() => {});
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

async function restoreWindowGeometry() {
  try {
    const saved = localStorage.getItem("window_geometry");
    if (saved) {
      const geo = JSON.parse(saved);
      const win = getCurrentWindow();
      if (geo.width && geo.height) {
        await win.setSize(new PhysicalSize(geo.width, geo.height));
      }
      if (geo.x !== undefined && geo.y !== undefined) {
        await win.setPosition(new PhysicalPosition(geo.x, geo.y));
      }
    }
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

function handleQrSuccess(cookie: string) {
  accountsStore.addAccount(cookie);
}

function selectAccount(accountId: string) {
  selectedAccountId.value = accountId;
}
</script>

<template>
  <div class="min-h-screen bg-background text-foreground">
    <!-- 顶栏 -->
    <header class="sticky top-0 z-10 border-b border-border bg-card/95 backdrop-blur">
      <div class="container mx-auto flex h-14 items-center justify-between px-4">
        <h1 class="text-lg font-bold">守望先锋直播掉宝助手</h1>
        <div class="flex items-center gap-3">
          <span class="text-sm text-muted-foreground">
            {{ accountsStore.accounts.filter((a) => a.running).length }} 个账号运行中
          </span>
          <button
            class="rounded-md p-2 hover:bg-accent transition-colors"
            @click="toggleTheme"
          >
            {{ darkMode ? "☀️" : "🌙" }}
          </button>
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
  </div>
</template>

