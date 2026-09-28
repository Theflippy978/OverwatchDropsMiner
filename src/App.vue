<script setup lang="ts">
import { ref, onMounted } from "vue";
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
const taskProgress = ref<any>(null);
const watchTimeSeconds = ref(0);
const showQrLogin = ref(false);

onMounted(async () => {
  await accountsStore.fetchAccounts();
  await configStore.load();
  
  darkMode.value = window.matchMedia("(prefers-color-scheme: dark)").matches;
  updateTheme();
});

function updateTheme() {
  if (darkMode.value) {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }
}

function toggleTheme() {
  darkMode.value = !darkMode.value;
  updateTheme();
}

function selectAccount(accountId: string) {
  selectedAccountId.value = accountId;
}

function handleQrSuccess(cookie: string) {
  accountsStore.addAccount(cookie);
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
    </header>

    <!-- 主内容 -->
    <main class="container mx-auto p-4">
      <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <!-- 账号列表 -->
        <div class="lg:col-span-1">
          <AccountList />
        </div>

        <!-- 配置、任务进度和日志 -->
        <div class="space-y-4 lg:col-span-2">
          <ConfigForm />
          <NotificationSettings />
          
          <!-- 任务进度 -->
          <TaskProgress
            v-if="selectedAccountId"
            :account-id="selectedAccountId"
            :running="accountsStore.accounts.find((a) => a.id === selectedAccountId)?.running ?? false"
            :watch-time-seconds="watchTimeSeconds"
            :task-progress="taskProgress"
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
