<script setup lang="ts">
import { ref } from "vue";
import { useAccountsStore } from "@/stores/accounts";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";

const accountsStore = useAccountsStore();

defineProps<{
  selectedId: string | null;
}>();

const emit = defineEmits<{
  select: [accountId: string];
  "qr-login": [];
}>();

const showAddDialog = ref(false);
const newCookie = ref("");
const adding = ref(false);
const capturing = ref(false);

const showRenameDialog = ref(false);
const renameTargetId = ref("");
const renameValue = ref("");
const renaming = ref(false);

const pendingAction = ref("");

function pendingLabel(accountId: string, idle: string) {
  if (!pendingAction.value.startsWith(`${accountId}:`)) return idle;
  return pendingAction.value.endsWith(":start") ? "启动中..." : "停止中...";
}

function openRenameDialog(accountId: string, currentRemark: string) {
  renameTargetId.value = accountId;
  renameValue.value = currentRemark;
  showRenameDialog.value = true;
}

async function handleRenameAccount() {
  const remark = renameValue.value.trim();
  if (!remark || !renameTargetId.value) return;
  renaming.value = true;
  try {
    await accountsStore.renameAccount(renameTargetId.value, remark);
    showRenameDialog.value = false;
  } finally {
    renaming.value = false;
  }
}

async function handleBrowserCapture() {
  capturing.value = true;
  try {
    const cookie = await accountsStore.browserCapture();
    if (cookie) newCookie.value = cookie;
  } catch {
    // 捕获失败时保持输入框原内容
  } finally {
    capturing.value = false;
  }
}

async function handleAddAccount() {
  if (!newCookie.value.trim()) return;
  adding.value = true;
  try {
    await accountsStore.addAccount(newCookie.value.trim());
    newCookie.value = "";
    showAddDialog.value = false;
  } finally {
    adding.value = false;
  }
}

async function handleRemoveAccount(accountId: string) {
  if (confirm("确定要删除该账号吗？")) {
    await accountsStore.removeAccount(accountId);
  }
}

async function handleStart(accountId: string) {
  if (pendingAction.value) return;
  pendingAction.value = `${accountId}:start`;
  try {
    const config = {
      room_ids: [],
      thread_count: 60,
      reconnect_delay_seconds: 8,
      task_ids: [],
      task_query_interval_seconds: 30,
      notify_urls: [],
    };
    await accountsStore.startMiner(accountId, config);
    // 对齐原 _finish_account_started：启动后自动选中该账号
    emit("select", accountId);
  } finally {
    pendingAction.value = "";
  }
}

async function handleStop(accountId: string) {
  if (pendingAction.value) return;
  pendingAction.value = `${accountId}:stop`;
  try {
    await accountsStore.stopMiner(accountId);
  } finally {
    pendingAction.value = "";
  }
}
</script>

<template>
  <Card class="h-full">
    <CardHeader class="pb-3">
      <div class="flex items-center justify-between">
        <CardTitle class="text-sm">账号列表</CardTitle>
        <div class="flex items-center gap-2">
          <Button size="sm" variant="outline" class="h-7 text-xs" @click="emit('qr-login')">
            扫码登录
          </Button>
        <Dialog v-model:open="showAddDialog">
          <DialogTrigger as-child>
            <Button size="sm" class="h-7 text-xs">
              + 添加账号
            </Button>
          </DialogTrigger>
          <DialogContent class="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>添加账号</DialogTitle>
              <DialogDescription>
                粘贴 B 站 Cookie 以添加新账号
              </DialogDescription>
            </DialogHeader>
            <div class="space-y-4 py-4">
              <div class="space-y-2">
                <label class="text-sm font-medium">Cookie</label>
                <Input
                  v-model="newCookie"
                  placeholder="粘贴 B 站 Cookie..."
                  class="font-mono text-xs"
                />
                <Button
                  variant="secondary"
                  size="sm"
                  class="mt-2 h-7 w-full text-xs"
                  :disabled="capturing"
                  @click="handleBrowserCapture"
                >
                  {{ capturing ? "捕获中，请在浏览器完成登录..." : "从浏览器捕获" }}
                </Button>
              </div>
              <div class="flex justify-end gap-2">
                <Button variant="outline" size="sm" @click="showAddDialog = false">
                  取消
                </Button>
                <Button size="sm" :disabled="adding" @click="handleAddAccount">
                  {{ adding ? "添加中..." : "添加" }}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
        </div>

        <Dialog v-model:open="showRenameDialog">
          <DialogContent class="sm:max-w-sm">
            <DialogHeader>
              <DialogTitle>重命名账号</DialogTitle>
              <DialogDescription>
                修改该账号的备注名称，便于区分多个账号
              </DialogDescription>
            </DialogHeader>
            <div class="space-y-4 py-4">
              <div class="space-y-2">
                <label class="text-sm font-medium">备注名称</label>
                <Input
                  v-model="renameValue"
                  placeholder="输入新的备注名称..."
                  maxlength="32"
                  @keyup.enter="handleRenameAccount"
                />
              </div>
              <div class="flex justify-end gap-2">
                <Button variant="outline" size="sm" @click="showRenameDialog = false">
                  取消
                </Button>
                <Button size="sm" :disabled="renaming || !renameValue.trim()" @click="handleRenameAccount">
                  {{ renaming ? "保存中..." : "保存" }}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </CardHeader>
    <CardContent class="pt-0">
      <ScrollArea class="h-[calc(100vh-280px)]">
        <div v-if="accountsStore.loading" class="py-8 text-center text-sm text-muted-foreground">
          加载中...
        </div>
        <div v-else-if="accountsStore.accounts.length === 0" class="py-8 text-center text-sm text-muted-foreground">
          暂无账号，点击上方按钮添加
        </div>
        <div v-else class="space-y-2">
          <div
            v-for="account in accountsStore.accounts"
            :key="account.id"
            class="flex cursor-pointer items-center justify-between rounded-lg border p-3 transition-colors"
            :class="
              account.id === selectedId
                ? 'border-primary bg-accent/60'
                : 'border-border hover:bg-accent/50'
            "
            @click="emit('select', account.id)"
          >
            <div class="flex items-center gap-3">
              <span
                class="h-2.5 w-2.5 rounded-full"
                :class="account.running ? 'bg-green-500' : 'bg-muted'"
              />
              <div>
                <p class="text-sm font-medium">{{ account.remark }}</p>
                <p class="text-xs text-muted-foreground">{{ account.id.slice(0, 12) }}...</p>
              </div>
            </div>
            <div class="flex items-center gap-1">
              <Button
                v-if="!account.running"
                size="sm"
                variant="outline"
                class="h-7 text-xs"
                :disabled="pendingAction !== ''"
                @click.stop="handleStart(account.id)"
              >
                {{ pendingLabel(account.id, "启动") }}
              </Button>
              <Button
                v-else
                size="sm"
                variant="destructive"
                class="h-7 text-xs"
                :disabled="pendingAction !== ''"
                @click.stop="handleStop(account.id)"
              >
                {{ pendingLabel(account.id, "停止") }}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                class="h-7 text-xs text-muted-foreground hover:text-foreground"
                @click.stop="openRenameDialog(account.id, account.remark)"
              >
                改名
              </Button>
              <Button
                size="sm"
                variant="ghost"
                class="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                :disabled="pendingAction !== ''"
                @click.stop="handleRemoveAccount(account.id)"
              >
                ✕
              </Button>
            </div>
          </div>
        </div>
      </ScrollArea>
    </CardContent>
  </Card>
</template>

