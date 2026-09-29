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
  loading.value = true;
  error.value = "";
  statusText.value = "";
  qrImage.value = "";
  qrKey.value = "";
  try {
    const challenge = await invoke<QrChallenge>("qr_login");
    qrImage.value = challenge.qr_image;
    qrKey.value = challenge.qr_key;
    statusText.value = "请使用哔哩哔哩手机客户端扫码";
    startCountdown();
    startPolling();
  } catch (e) {
    error.value = `获取二维码失败: ${e}`;
  } finally {
    loading.value = false;
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
  if (polling || !qrKey.value || !props.open) return;
  polling = true;
  try {
    const result = await invoke<QrPollResult>("qr_poll", { qrKey: qrKey.value });
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
    // 网络抖动时保持轮询，下次重试
    statusText.value = `查询状态失败: ${e}`;
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
  if (qrKey.value) {
    invoke("qr_cancel").catch(() => undefined);
  }
  qrKey.value = "";
}

function handleCancel() {
  stopSession();
  emit("update:open", false);
}
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="sm:max-w-md" @escape-key-down="handleCancel">
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
          class="h-48 w-48 flex items-center justify-center rounded-lg border border-red-500/40 bg-red-500/10 p-2"
        >
          <span class="text-center text-sm text-red-500">{{ error }}</span>
        </div>
        <div v-else class="h-48 w-48 rounded-lg border border-border bg-white p-2">
          <img
            v-if="qrImage"
            :src="qrImage"
            alt="扫码登录"
            class="h-full w-full"
          />
        </div>

        <p v-if="statusText" class="text-center text-sm text-muted-foreground">
          {{ statusText }}
        </p>
        <p v-if="countdown > 0 && !error" class="text-sm text-muted-foreground">
          {{ Math.floor(countdown / 60) }}:{{ (countdown % 60).toString().padStart(2, "0") }} 后过期
        </p>
      </div>

      <DialogFooter>
        <Button variant="outline" @click="handleCancel">取消</Button>
        <Button :disabled="loading" @click="startSession">刷新二维码</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
