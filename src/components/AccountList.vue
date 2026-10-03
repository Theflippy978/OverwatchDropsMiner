<script setup lang="ts">
import { ref } from "vue";
import { useAccountsStore } from "@/stores/accounts";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from "@/components/ui/dropdown-menu";
import ConfirmDialog from "@/components/ConfirmDialog.vue";

const accountsStore = useAccountsStore();

const props = defineProps<{
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
const captureError = ref("");

const showRemoveConfirm = ref(false);
const removeTargetId = ref("");
const removeTargetRemark = ref("");
const removing = ref(false);

const pendingAction = ref("");
/** 统一的操作错误提示区。
    原实现用原生 alert()，与 App.vue:60-61 已确立的「不用阻塞 WebView 的
    原生弹窗」决策冲突（alert 在 WebView2 里是阻塞式 modal）。 */
const actionError = ref("");

function showError(prefix: string, e: unknown) {
  actionError.value = `${prefix}: ${e}`;
}

function clearError() {
  actionError.value = "";
}

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
  clearError();
  try {
    await accountsStore.renameAccount(renameTargetId.value, remark);
    showRenameDialog.value = false;
  } catch (e) {
    showError("重命名失败", e);
  } finally {
    renaming.value = false;
  }
}

async function handleAddAccount() {
  if (!newCookie.value.trim()) return;
  adding.value = true;
  clearError();
  try {
    const account = await accountsStore.addAccount(newCookie.value.trim());
    newCookie.value = "";
    showAddDialog.value = false;
    if (account) emit("select", account.id);
  } catch (e) {
    showError("添加账号失败", e);
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
  clearError();
  try {
    await accountsStore.removeAccount(removeTargetId.value);
    showRemoveConfirm.value = false;
  } catch (e) {
    showError("删除账号失败", e);
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
  clearError();
  try {
    await accountsStore.startMiner(accountId);
    // 对齐原 _finish_account_started：启动后自动选中该账号
    emit("select", accountId);
  } catch (e) {
    showError("启动失败", e);
  } finally {
    pendingAction.value = "";
  }
}

async function handleStop(accountId: string) {
  if (pendingAction.value) return;
  pendingAction.value = `${accountId}:stop`;
  clearError();
  try {
    await accountsStore.stopMiner(accountId);
  } catch (e) {
    showError("停止失败", e);
  } finally {
    pendingAction.value = "";
  }
}

function handleCaptureCookie() {
  captureError.value = "";
  showCaptureConfirm.value = true;
}

async function confirmCaptureCookie() {
  if (capturing.value) return;
  captureError.value = "";
  capturing.value = true;
  try {
    const cookie = await accountsStore.browserCapture();
    if (!cookie) {
      captureError.value = "未捕获到 Cookie，请确认浏览器中已登录 B 站";
      return;
    }
    const account = await accountsStore.addAccount(cookie);
    showCaptureConfirm.value = false;
    if (account) emit("select", account.id);
  } catch (e) {
    // 捕获期间保持对话框打开，失败文案显示在框内供重试
    captureError.value = String(e);
  } finally {
    capturing.value = false;
  }
}

function cancelCaptureCookie() {
  showCaptureConfirm.value = false;
  captureError.value = "";
}

// 底部「备注/删除」作用于当前选中账号（对齐旧版：行内只保留启动/停止）
function handleBottomRename() {
  if (!props.selectedId) return;
  const acc = accountsStore.accounts.find((a) => a.id === props.selectedId);
  openRenameDialog(props.selectedId, acc?.remark ?? "");
}

function handleBottomRemove() {
  if (!props.selectedId) return;
  handleRemoveAccount(props.selectedId);
}
</script>

<template>
  <!-- 卡片内边距对齐旧版 account_panel.py:45 的 setContentsMargins(14, 12, 14, 14)、
       间距 10px；h-full 拉满左栏：列表区弹性伸缩，操作按钮固定在卡底 -->
  <Card class="card-hover flex h-full flex-col">
    <CardHeader class="px-3.5 pb-2.5 pt-3">
        <div class="flex items-center justify-between">
          <CardTitle class="text-[11pt] font-semibold">账号</CardTitle>
          <span class="text-xs text-muted-foreground">{{ accountsStore.accounts.length }} 个</span>
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
                <Label for="new-cookie" class="text-sm font-medium">Cookie</Label>
                <Input
                  id="new-cookie"
                  v-model="newCookie"
                  type="password"
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
                <Button
                  size="sm"
                  :disabled="adding || !newCookie.trim()"
                  @click="handleAddAccount"
                >
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
                <Label for="rename-value" class="text-sm font-medium">备注名称</Label>
                <Input
                  id="rename-value"
                  v-model="renameValue"
                  placeholder="输入新的备注名称..."
                  maxlength="32"
                  :disabled="renaming"
                  @keydown.enter="handleRenameAccount"
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
    <CardContent class="min-h-0 flex-1 px-3.5 pt-0">
      <!-- 列表容器对齐旧版 QListWidget QSS（theme.py:226-233）：
           输入框底色 + 1px 边框 + radius 8px + 内 padding 4px -->
      <ScrollArea class="h-full rounded-lg border border-input bg-input/40 p-1">
        <div v-if="accountsStore.loading" class="py-8 text-center text-sm text-muted-foreground">
          加载中...
        </div>
        <!-- 错误态：缺了它，sidecar 起不来时 accounts 保持 []，
             下面会渲染「暂无账号」，把故障伪装成空列表 -->
        <div
          v-else-if="accountsStore.error"
          class="space-y-2 py-8 text-center"
          role="alert"
        >
          <p class="break-all text-sm text-signal-danger">{{ accountsStore.error }}</p>
          <Button size="sm" variant="outline" @click="accountsStore.fetchAccounts()">
            重试
          </Button>
        </div>
        <div v-else-if="accountsStore.accounts.length === 0" class="py-8 text-center text-sm text-muted-foreground">
          暂无账号，点击下方按钮添加
        </div>
        <TransitionGroup
          v-else
          name="account-list"
          tag="div"
          class="space-y-0.5"
          role="listbox"
          aria-label="账号列表"
        >
          <div
            v-for="account in accountsStore.accounts"
            :key="account.id"
            role="option"
            tabindex="0"
            :aria-selected="account.id === selectedId"
            :aria-label="`${account.remark}，${account.running ? '运行中' : '未运行'}`"
            class="mx-px flex cursor-pointer items-center justify-between rounded-md border px-2.5 py-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            :class="[
              account.running ? 'account-row-running' : 'border-border',
              account.id === selectedId
                ? 'bg-accent shadow-[inset_0_0_0_1px_var(--color-primary)]'
                : 'hover:bg-accent/50',
            ]"
            @click="emit('select', account.id)"
            @keydown.enter.prevent="emit('select', account.id)"
            @keydown.space.prevent="emit('select', account.id)"
          >
            <div class="flex min-w-0 items-center gap-2">
              <!-- 运行状态由行级 aria-label 提供，圆点本身对读屏隐藏 -->
              <span
                aria-hidden="true"
                class="h-2.5 w-2.5 shrink-0 rounded-full"
                :class="account.running ? 'bg-signal-success' : 'bg-muted'"
              />
              <p
                class="truncate text-sm font-medium"
                :class="account.running ? 'text-signal-success' : 'text-foreground'"
              >
                {{ account.remark }}
              </p>
            </div>
            <div class="flex shrink-0 items-center gap-1">
              <Button
                v-if="!account.running"
                size="sm"
                variant="outline"
                class="h-7 rounded-md px-3 text-xs"
                :disabled="pendingAction !== ''"
                @click.stop="handleStart(account.id)"
              >
                {{ pendingLabel(account.id, "启动") }}
              </Button>
              <Button
                v-else
                size="sm"
                variant="destructive"
                class="h-7 rounded-md px-3 text-xs"
                :disabled="pendingAction !== ''"
                @click.stop="handleStop(account.id)"
              >
                {{ pendingLabel(account.id, "停止") }}
              </Button>
            </div>
          </div>
        </TransitionGroup>
      </ScrollArea>
    </CardContent>

    <!-- 底部操作区（对齐旧版 account_panel.py:62-71）：添加账号全宽 + 备注/删除对半 -->
    <div class="flex flex-col gap-2.5 px-3.5 pb-3.5 pt-2.5">
      <p
        v-if="actionError"
        class="break-all text-xs text-signal-danger"
        role="alert"
        aria-live="polite"
      >
        {{ actionError }}
      </p>
      <DropdownMenu>
        <DropdownMenuTrigger as-child>
          <Button class="w-full rounded-md">添加账号</Button>
        </DropdownMenuTrigger>
        <!-- 旧版弹到按钮正上方（account_panel.py:136-140，注释：避免被窗口底部截断） -->
        <DropdownMenuContent align="center" side="top" class="w-40">
          <DropdownMenuItem @select="emit('qr-login')">扫码登录</DropdownMenuItem>
          <DropdownMenuItem @select="showAddDialog = true">手动粘贴 Cookie</DropdownMenuItem>
          <DropdownMenuItem @select="handleCaptureCookie">浏览器自动捕获</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <div class="grid grid-cols-2 gap-1.5">
        <Button
          variant="outline"
          class="rounded-md"
          :disabled="!selectedId"
          @click="handleBottomRename"
        >
          备注
        </Button>
        <Button
          variant="outline"
          class="rounded-md text-destructive hover:bg-destructive/10"
          :disabled="!selectedId || pendingAction !== ''"
          @click="handleBottomRemove"
        >
          删除
        </Button>
      </div>
    </div>
  </Card>

  <Dialog v-model:open="showCaptureConfirm">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>从浏览器捕获 Cookie</DialogTitle>
        <DialogDescription v-if="!capturing">
          即将打开浏览器捕获 B 站 Cookie，请确保已登录 B 站。捕获过程可能需要 1-2 分钟。
        </DialogDescription>
        <DialogDescription v-else>
          正在打开浏览器捕获 Cookie，请在浏览器完成 B 站登录并耐心等待（最长 120 秒）...
        </DialogDescription>
      </DialogHeader>
      <p v-if="captureError" class="text-sm text-signal-danger" role="alert">
        捕获失败: {{ captureError }}
      </p>
      <div class="flex justify-end gap-2">
        <Button variant="outline" size="sm" @click="cancelCaptureCookie">
          {{ capturing ? "关闭（后台继续）" : "取消" }}
        </Button>
        <Button size="sm" :disabled="capturing" @click="confirmCaptureCookie">
          {{ capturing ? "捕获中..." : captureError ? "重试" : "确认捕获" }}
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

