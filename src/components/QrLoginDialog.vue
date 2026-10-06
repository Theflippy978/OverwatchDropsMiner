<script setup lang="ts">
import { ref, watch, onUnmounted } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface QrChallenge {
  qr_url: string;
  qr_key: string;
  qr_image: string;
}

interface QrPollResult {
  status: string;
  cookie: string;
}

const props = defineProps<{
  open: boolean;
  /** 添加账号失败的原因，由父组件传入。渲染在框内而非父组件页面上：
      弹窗打开时 Dialog 的全屏遮罩会盖住页面上的任何错误提示，
      用户只会看到「点了没反应」。 */
  addError?: string;
}>();

const emit = defineEmits<{
  "update:open": [value: boolean];
  success: [cookie: string];
}>();

const qrImage = ref("");
const qrKey = ref("");
const loading = ref(false);
const error = ref("");
const statusText = ref("");
const countdown = ref(0);

const POLL_INTERVAL_MS = 2000;
const SESSION_SECONDS = 180;

let pollTimer: number | null = null;
let countdownTimer: number | null = null;
let polling = false;
/** 会话代次号：每次 startSession / stopSession 自增，
    in-flight 响应回来后比对不符即丢弃（防旧会话污染新会话） */
let sessionSeq = 0;

watch(
  () => props.open,
  (open) => {
    if (open) {
      void startSession();
    } else {
      stopSession();
    }
  }
);

onUnmounted(() => {
  stopSession();
});

async function startSession() {
  stopTimers();
  // 代次号：新会话开始即自增，旧的 in-flight 响应回来后比对不符就丢弃。
  // 原实现没有这层保护 —— 用户在 qr_login 请求在途时点「刷新二维码」或
  // 关闭再打开，旧 pollOnce 回来会覆盖新会话的 statusText。
  sessionSeq += 1;
  // 同时复位 polling：否则旧请求卡住时它会锁死新会话最长 300s
  polling = false;
  loading.value = true;
  error.value = "";
  statusText.value = "";
  qrImage.value = "";
  qrKey.value = "";
  const seq = sessionSeq;
  try {
    const challenge = await invoke<QrChallenge>("qr_login");
    if (seq !== sessionSeq) return; // 会话已被取代
    qrImage.value = challenge.qr_image;
    qrKey.value = challenge.qr_key;
    statusText.value = "请使用哔哩哔哩手机客户端扫码";
    startCountdown();
    startPolling();
  } catch (e) {
    if (seq !== sessionSeq) return;
    error.value = `获取二维码失败: ${e}`;
  } finally {
    if (seq === sessionSeq) loading.value = false;
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  void pollOnce();
  pollTimer = window.setInterval(() => {
    void pollOnce();
  }, POLL_INTERVAL_MS);
}

async function pollOnce() {
  const key = qrKey.value;
  const seq = sessionSeq;
  if (polling || !key || !props.open) return;
  polling = true;
  try {
    const result = await invoke<QrPollResult>("qr_poll", { qrKey: key });
    if (seq !== sessionSeq || qrKey.value !== key) return; // 旧会话，丢弃
    switch (result.status) {
      case "unscanned":
        statusText.value = "请使用哔哩哔哩手机客户端扫码";
        break;
      case "scanned":
        statusText.value = "已扫码，请在手机上确认登录";
        break;
      case "expired":
        stopTimers();
        statusText.value = "二维码已过期，请重新生成";
        break;
      case "success":
        stopTimers();
        emit("success", result.cookie);
        emit("update:open", false);
        break;
    }
  } catch (e) {
    if (seq !== sessionSeq) return;
    // 错误分级：会话失效是终态，必须停轮询并给出重新生成引导。
    // 原实现一律「保持轮询下次重试」，于是 main.py 返回的
    // 「二维码会话不存在，请重新生成」被降级成一句临时文案，
    // 用户永远拿不到引导，只能自己发现要去点刷新按钮。
    const text = String(e);
    if (text.includes("会话不存在") || text.includes("已过期") || text.includes("invalid")) {
      stopTimers();
      sessionSeq += 1;
      statusText.value = "二维码已过期，请重新生成";
    } else {
      // 网络抖动时保持轮询，下次重试
      statusText.value = `查询状态失败: ${e}`;
    }
  } finally {
    polling = false;
  }
}

function startCountdown() {
  countdown.value = SESSION_SECONDS;
  if (countdownTimer) clearInterval(countdownTimer);
  countdownTimer = window.setInterval(() => {
    countdown.value--;
    if (countdown.value <= 0) {
      stopTimers();
      statusText.value = "二维码已过期，请重新生成";
    }
  }, 1000);
}

function stopTimers() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  if (countdownTimer) {
    clearInterval(countdownTimer);
    countdownTimer = null;
  }
}

function stopSession() {
  stopTimers();
  // 递增代次：让在途的 qr_login / qr_poll 响应回来时判定为旧会话并丢弃
  sessionSeq += 1;
  polling = false;
  if (qrKey.value) {
    invoke("qr_cancel").catch(() => undefined);
  }
  qrKey.value = "";
}

function handleOpenChange(next: boolean) {
  if (next) {
    emit("update:open", true);
  } else {
    handleCancel();
  }
}

function handleCancel() {
  stopSession();
  emit("update:open", false);
}
</script>

<template>
  <!-- ESC 不再单独绑 @escape-key-down：Dialog 根的 @update:open 已经会
       emit(false)，两者并存会连发两次 update:open。stopSession 有 qrKey
       守卫不会重复 qr_cancel，但语义重复且后续维护极易变成真 bug。 -->
  <Dialog :open="open" @update:open="handleOpenChange">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>扫码登录</DialogTitle>
        <DialogDescription>
          使用哔哩哔哩手机 APP 扫描二维码登录
        </DialogDescription>
      </DialogHeader>

      <div class="flex flex-col items-center gap-3 py-4">
        <div
          v-if="loading"
          class="h-48 w-48 flex items-center justify-center rounded-lg border border-border bg-muted"
        >
          <span class="text-sm text-muted-foreground">正在生成二维码...</span>
        </div>
        <div
          v-else-if="error"
          class="h-48 w-48 flex items-center justify-center rounded-lg border border-signal-danger/40 bg-signal-danger/10 p-2"
        >
          <span class="text-center text-sm text-signal-danger">{{ error }}</span>
        </div>
        <!-- 二维码容器保持 bg-white：部分扫码 App 对低对比度识别率下降，
             后端生成的黑白 PNG（fill_color="black", back_color="white"）
             与容器色无关。这里刻意脱离主题令牌，不要被「统一主题」误改。 -->
        <div v-else class="h-48 w-48 rounded-lg border border-border bg-white p-2">
          <img
            v-if="qrImage"
            :src="qrImage"
            alt="扫码登录"
            class="h-full w-full"
          />
        </div>

        <!-- aria-live：扫码流程的关键反馈（请扫码→已扫码→已过期），
             读屏用户在把注意力转向手机 App 时回来必须能知道状态变了。
             倒计时刻意不加 aria-live（每秒播报会刷屏）。 -->
        <p
          v-if="addError"
          class="break-all text-center text-sm text-signal-danger"
          role="alert"
        >
          {{ addError }}
        </p>
        <p
          v-if="statusText"
          class="text-center text-sm text-muted-foreground"
          aria-live="polite"
        >
          {{ statusText }}
        </p>
        <p v-if="countdown > 0 && !error" class="text-sm text-muted-foreground" aria-hidden="true">
          {{ Math.floor(countdown / 60) }}:{{ (countdown % 60).toString().padStart(2, "0") }} 后过期
        </p>
      </div>

      <DialogFooter>
        <Button variant="outline" @click="handleCancel">取消</Button>
        <Button :disabled="loading" @click="startSession">
          {{ countdown === 0 || statusText.includes("过期") ? "重新生成二维码" : "刷新二维码" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
