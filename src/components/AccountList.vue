<script setup lang="ts">
import { ref } from "vue";
import { useAccountsStore } from "@/stores/accounts";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import ConfirmDialog from "@/components/ConfirmDialog.vue";

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

const showCaptureConfirm = ref(false);

const showRemoveConfirm = ref(false);
const removeTargetId = ref("");
const removeTargetRemark = ref("");
const removing = ref(false);

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
  } catch (e) {
    alert(`重命名失败: ${e}`);
  } finally {
    renaming.value = false;
  }
}

async function handleAddAccount() {
  if (!newCookie.value.trim()) return;
  adding.value = true;
  try {
    const account = await accountsStore.addAccount(newCookie.value.trim());
    newCookie.value = "";
    showAddDialog.value = false;
    if (account) emit("select", account.id);
  } catch (e) {
    alert(`添加账号失败: ${e}`);
  } finally {
    adding.value = false;
  }
}

function handleRemoveAccount(accountId: string) {
  const account = accountsStore.accounts.find((a) => a.id === accountId);
  removeTargetId.value = accountId;
  removeTargetRemark.value = account?.remark || accountId.slice(0, 8);
  showRemoveConfirm.value = true;
}

async function confirmRemoveAccount() {
  if (!removeTargetId.value) return;
  removing.value = true;
  try {
    await accountsStore.removeAccount(removeTargetId.value);
    showRemoveConfirm.value = false;
  } catch (e) {
    alert(`删除账号失败: ${e}`);
  } finally {
    removing.value = false;
    removeTargetId.value = "";
  }
}

function cancelRemoveAccount() {
  showRemoveConfirm.value = false;
  removeTargetId.value = "";
}

async function handleStart(accountId: string) {
  if (pendingAction.value) return;
  pendingAction.value = `${accountId}:start`;
  try {
    await accountsStore.startMiner(accountId);
    // 对齐原 _finish_account_started：启动后自动选中该账号
    emit("select", accountId);
  } catch (e) {
    alert(`启动失败: ${e}`);
  } finally {
    pendingAction.value = "";
  }
}

async function handleStop(accountId: string) {
  if (pendingAction.value) return;
  pendingAction.value = `${accountId}:stop`;
  try {
    await accountsStore.stopMiner(accountId);
  } catch (e) {
    alert(`停止失败: ${e}`);
  } finally {
    pendingAction.value = "";
  }
}

function handleCaptureCookie() {
  showCaptureConfirm.value = true;
}

async function confirmCaptureCookie() {
  showCaptureConfirm.value = false;
  capturing.value = true;
  try {
    const cookie = await accountsStore.browserCapture();
    if (cookie) {
      const account = await accountsStore.addAccount(cookie);
      if (account) emit("select", account.id);
    }
  } catch (e) {
    alert(`捕获 Cookie 失败: ${e}`);
  } finally {
    capturing.value = false;
  }
}

function cancelCaptureCookie() {
  showCaptureConfirm.value = false;
}
</script>

<template>
  <Card class="h-full">
    <CardHeader class="pb-3">
        <div class="flex items-center justify-between">
          <CardTitle class="text-sm">账号列表</CardTitle>
          <div class="flex items-center gap-2">
            <div class="group relative">
              <Button size="sm" class="h-7 text-xs">
                + 添加账号
              </Button>
              <div class="pointer-events-none absolute right-0 top-full z-50 mt-1 w-40 rounded-md border border-border bg-popover p-1 text-xs text-popover-foreground opacity-0 shadow-md transition-opacity group-hover:opacity-100">
                <button
                  class="block w-full rounded px-2 py-1.5 text-left hover:bg-accent"
                  @click="emit('qr-login')"
                >
                  扫码登录
                </button>
                <button
                  class="block w-full rounded px-2 py-1.5 text-left hover:bg-accent"
                  @click="showAddDialog = true"
                >
                  手动粘贴 Cookie
                </button>
                <button
                  class="block w-full rounded px-2 py-1.5 text-left hover:bg-accent"
                  @click="handleCaptureCookie"
                >
                  浏览器自动捕获
                </button>
              </div>
            </div>
          </div>
        </div>

        <Dialog v-model:open="showAddDialog">
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
                  @click="handleCaptureCookie"
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
                :title="account.running ? '运行中' : '未运行'"
              />
              <div>
                <p
                  class="text-sm font-medium"
                  :class="account.running ? 'text-green-500' : 'text-foreground'"
                  :title="account.running ? '运行中' : '未运行'"
                >
                  {{ account.remark }}
                </p>
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

  <Dialog v-model:open="showCaptureConfirm">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>从浏览器捕获 Cookie</DialogTitle>
        <DialogDescription>
          即将打开浏览器捕获 B 站 Cookie，请确保已登录 B 站。捕获过程可能需要 1-2 分钟。
        </DialogDescription>
      </DialogHeader>
      <div class="flex justify-end gap-2">
        <Button variant="outline" size="sm" @click="cancelCaptureCookie">
          取消
        </Button>
        <Button size="sm" @click="confirmCaptureCookie">
          确认捕获
        </Button>
      </div>
    </DialogContent>
  </Dialog>

  <!-- 删除账号确认（替代原生 confirm，避免阻塞 WebView） -->
  <ConfirmDialog
    :open="showRemoveConfirm"
    title="删除账号"
    :message="`确定要删除账号「${removeTargetRemark}」吗？该操作不可撤销。`"
    confirm-text="删除"
    variant="destructive"
    :loading="removing"
    @update:open="showRemoveConfirm = $event"
    @confirm="confirmRemoveAccount"
    @cancel="cancelRemoveAccount"
  />
</template>

