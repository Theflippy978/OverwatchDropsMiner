<script setup lang="ts">
import { ref } from "vue";
import { useAccountsStore } from "@/stores/accounts";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { useTimedNotice } from "@/lib/notice";
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
/** 重命名失败的原因。必须留在 Dialog 内部：Dialog 打开时全屏遮罩会吃掉
    指针事件，页面底部的错误条既看不见也点不到，用户只会认为程序卡死。
    同时保证失败后对话框不自动关闭——自动关闭会让用户丢掉刚输入的内容。 */
const renameError = ref("");

const showCaptureConfirm = ref(false);
const captureError = ref("");

const showRemoveConfirm = ref(false);
const removeTargetId = ref("");
const removeTargetRemark = ref("");
const removing = ref(false);
/** 正在进行中的操作，元素形如 `${accountId}:start` / `${accountId}:stop`。
    用 Set 而不是单个字符串：禁用范围收窄到「当前操作行」之后，
    单值会被后一次操作覆盖掉前一个（同时启停两个账号时按错的行禁用）。
    Vue 3 的 ref 会把 Set 变成响应式集合，add/delete 本身即触发更新。 */
const pendingActions = ref(new Set<string>());

/** 该账号是否有操作在途。禁用只针对这一个账号，
    早期实现是 `pendingAction !== ''` —— 一行在操作，全部账号行一起变灰。 */
function isPending(accountId: string): boolean {
  return (
    pendingActions.value.has(`${accountId}:start`) ||
    pendingActions.value.has(`${accountId}:stop`)
  );
}

/** 页内错误提示，只用于不涉及弹窗的操作（启动/停止），3 秒自动消失。
    凡是在 Dialog / ConfirmDialog 内失败的操作，提示必须放进那个框里**且
    绝不能自动消失**：弹窗打开时全屏遮罩会吃掉指针事件并盖住页面上的任何提示，
    用户既看不到错误也点不掉弹窗，只会认为程序卡死。
    （`addError` / `renameError` / `captureError` / `removeError` 四处保持常驻。） */
const {
  text: actionError,
  show: showActionError,
  clear: clearActionError,
} = useTimedNotice();
const addError = ref("");
const removeError = ref("");

function openRenameDialog(accountId: string, currentRemark: string) {
  renameTargetId.value = accountId;
  renameValue.value = currentRemark;
  renameError.value = "";
  showRenameDialog.value = true;
}

async function handleRenameAccount() {
  const remark = renameValue.value.trim();
  if (!remark || !renameTargetId.value) return;
  renaming.value = true;
  renameError.value = "";
  try {
    await accountsStore.renameAccount(renameTargetId.value, remark);
    showRenameDialog.value = false;
  } catch (e) {
    renameError.value = `${e}`;
  } finally {
    renaming.value = false;
  }
}

async function handleAddAccount() {
  if (!newCookie.value.trim()) return;
  adding.value = true;
  addError.value = "";
  try {
    const account = await accountsStore.addAccount(newCookie.value.trim());
    newCookie.value = "";
    showAddDialog.value = false;
    if (account) emit("select", account.id);
  } catch (e) {
    addError.value = `添加账号失败: ${e}`;
  } finally {
    adding.value = false;
  }
}

function handleRemoveAccount(accountId: string) {
  const account = accountsStore.accounts.find((a) => a.id === accountId);
  removeTargetId.value = accountId;
  removeTargetRemark.value = account?.remark || accountId.slice(0, 8);
  removeError.value = "";
  showRemoveConfirm.value = true;
}

async function confirmRemoveAccount() {
  if (!removeTargetId.value) return;
  removing.value = true;
  removeError.value = "";
  try {
    await accountsStore.removeAccount(removeTargetId.value);
    showRemoveConfirm.value = false;
    removeTargetId.value = "";
  } catch (e) {
    // 失败时保留 removeTargetId：清空它会让框内的错误提示无法重试，
    // 用户只能关掉重来。
    removeError.value = `删除账号失败: ${e}`;
  } finally {
    removing.value = false;
  }
}

function cancelRemoveAccount() {
  showRemoveConfirm.value = false;
  removeTargetId.value = "";
}

/** 启停的等待期只靠 disabled 表达，按钮文案必须恒为「启动」/「停止」。
    早前会把文案换成「启动中...」「停止中...」，而按钮只有 px-3 没有固定宽，
    文案一变宽就变 —— 整行跟着左右抖，在多账号列表里尤其明显。
    换成图标（旋转 spinner）能兼顾两者，但那样 disabled 的半透明会把图标一起
    淡掉，等待感反而更弱；文案恒定是最省事也最不容易出错的形态。 */
async function handleStart(accountId: string) {
  if (isPending(accountId)) return;
  const token = `${accountId}:start`;
  pendingActions.value.add(token);
  clearActionError();
  try {
    await accountsStore.startMiner(accountId);
    // 启动后自动选中该账号：用户点「启动」的意图就是「我要看这个账号」，
    // 不自动选中会让他再点一次账号行，而进度卡还停在别的账号上。
    emit("select", accountId);
  } catch (e) {
    showActionError(`启动失败: ${e}`, true);
  } finally {
    pendingActions.value.delete(token);
  }
}

async function handleStop(accountId: string) {
  if (isPending(accountId)) return;
  const token = `${accountId}:stop`;
  pendingActions.value.add(token);
  clearActionError();
  try {
    await accountsStore.stopMiner(accountId);
  } catch (e) {
    showActionError(`停止失败: ${e}`, true);
  } finally {
    pendingActions.value.delete(token);
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
  <!-- 卡片内边距 14/12/14/14、间距 10px，对齐 Qt 时代的账号面板；
       h-full 拉满左栏：列表区弹性伸缩，操作按钮固定在卡底。
       rounded-none：账号栏紧贴窗口左右边缘，圆角会在窗口边界与卡片
       之间露出一小块背景色，看起来像「卡片没贴满」。
       card-hover 的 hover 边框变化保留，它不影响圆角。
       图标条模式已删除，这里不再有 collapsed 分支。 -->
    <Card class="card-hover flex h-full flex-col rounded-none">
      <CardHeader class="px-3.5 pb-2.5 pt-3">
      <div class="flex items-center justify-between">
        <CardTitle class="text-[11pt] font-semibold">账号</CardTitle>
        <span class="text-xs text-muted-foreground">
          {{ accountsStore.accounts.length }} 个
        </span>
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
              <p
                v-if="addError"
                class="break-all text-xs text-signal-danger"
                role="alert"
              >
                {{ addError }}
              </p>
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
              <p
                v-if="renameError"
                class="break-all text-xs text-signal-danger"
                role="alert"
              >
                {{ renameError }}
              </p>
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
      <!-- 列表容器沿用 Qt 时代 QListWidget 的观感：
           输入框底色 + 1px 边框 + radius 8px + 内 padding 4px。
           用原生 overflow-y-auto 而非引入 reka 的滚动条组件：后者会渲染
           一条独立的隐藏式滚动条元素，CSS 的 ::-webkit-scrollbar 盖不住它，
           而全局隐藏滚动条是本项目的统一要求。 -->
      <div class="scroll-hidden h-full overflow-y-auto rounded-lg border border-input bg-input/40 p-1">
        <div
          v-if="accountsStore.loading"
          class="py-8 text-center text-sm text-muted-foreground"
        >
          加载中...
        </div>
        <!-- 错误态：缺了它，sidecar 起不来时 accounts 保持 []，
             下面会渲染「暂无账号」，把故障伪装成空列表 -->
        <div
          v-else-if="accountsStore.error"
          class="space-y-2 py-8 text-center"
          role="alert"
        >
          <p class="break-all text-sm text-signal-danger">
            {{ accountsStore.error }}
          </p>
          <Button size="sm" variant="outline" @click="accountsStore.fetchAccounts()">
            重试
          </Button>
        </div>
        <div
          v-else-if="accountsStore.accounts.length === 0"
          class="py-8 text-center text-sm text-muted-foreground"
        >
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
            class="mx-px flex cursor-pointer items-center justify-between rounded-md border border-border px-2.5 py-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            :class="[
              // 运行态只由行内的状态圆点与文字颜色表达，不再叠一层边框动画：
              // 原实现在四边各铺一条独立 background-image 并各自流动，
              // 四个方向互不相同，视觉上就是「扫描线」而不是流动虚线框。
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
                class="h-2 w-2 shrink-0 rounded-full"
                :class="account.running ? 'bg-signal-success' : 'bg-muted'"
              />
              <p
                class="truncate text-sm leading-tight font-medium"
                :class="account.running ? 'text-signal-success' : 'text-foreground'"
              >
                {{ account.remark }}
              </p>
            </div>
            <div class="flex shrink-0 items-center gap-1">
              <!-- 启停合为一个按钮，variant 动态绑定。
                   早前用 v-if / v-else 写两个 Button：点「停止」时
                   account.running 翻 false，旧按钮被销毁、新按钮被创建，
                   而 transition-colors 只在同一 DOM 节点上生效 —— 节点替换
                   不产生过渡，加上 variant 从 destructive（红底白字）跳到
                   outline（白底描边）整套配色突变，视觉上就是「闪一下」。
                   单按钮后 variant 只是 class 变化，过渡正常生效。 -->
              <Button
                size="sm"
                :variant="account.running ? 'destructive' : 'outline'"
                class="h-7 w-16 rounded-md px-0 text-xs"
                :disabled="isPending(account.id)"
                @click.stop="account.running ? handleStop(account.id) : handleStart(account.id)"
              >
                {{ account.running ? "停止" : "启动" }}
              </Button>
            </div>
          </div>
        </TransitionGroup>
      </div>
    </CardContent>

    <!-- 底部操作区：添加账号全宽 + 备注/删除对半 -->
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
        <!-- 必须 side="top"：菜单挂在按钮正下方会被窗口底部截断，
             而这个按钮就在左栏最下缘。 -->
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
        <!-- 「删除」保留全局禁用（pendingActions 非空即禁用），
             与行内启停的按行禁用不同：删除会连带 stop_miner + 清缓存 + 删库，
             在任何一个账号启停在途时做这件事，失败原因极难归到正确的操作上。 -->
        <Button
          variant="outline"
          class="rounded-md text-destructive hover:bg-destructive/10"
          :disabled="!selectedId || pendingActions.size > 0"
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
    :error="removeError"
    confirm-text="删除"
    variant="destructive"
    :loading="removing"
    @update:open="showRemoveConfirm = $event"
    @confirm="confirmRemoveAccount"
    @cancel="cancelRemoveAccount"
  />
</template>

