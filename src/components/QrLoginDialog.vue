<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
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

const props = defineProps<{
  open: boolean;
}>();

const emit = defineEmits<{
  "update:open": [value: boolean];
  success: [cookie: string];
}>();

const qrCode = ref("");
const loading = ref(false);
const error = ref("");
const countdown = ref(0);
let timer: number | null = null;

onMounted(() => {
  if (props.open) {
    startQrLogin();
  }
});

onUnmounted(() => {
  if (timer) clearInterval(timer);
});

async function startQrLogin() {
  loading.value = true;
  error.value = "";
  try {
    // TODO: 调用后端获取二维码
    // qrCode.value = await invoke("qr_login");
    qrCode.value = "https://example.com/qr-placeholder";
    startCountdown();
  } catch (e) {
    error.value = "获取二维码失败";
  } finally {
    loading.value = false;
  }
}

function startCountdown() {
  countdown.value = 180; // 3分钟
  if (timer) clearInterval(timer);
  timer = window.setInterval(() => {
    countdown.value--;
    if (countdown.value <= 0) {
      if (timer) clearInterval(timer);
    }
  }, 1000);
}

function handleSuccess() {
  emit("success", "cookie_string");
  emit("update:open", false);
}
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>扫码登录</DialogTitle>
        <DialogDescription>
          使用哔哩哔哩手机 APP 扫描二维码登录
        </DialogDescription>
      </DialogHeader>
      
      <div class="flex flex-col items-center gap-4 py-4">
        <div v-if="loading" class="h-48 w-48 flex items-center justify-center rounded-lg border border-border bg-muted">
          <span class="text-sm text-muted-foreground">加载中...</span>
        </div>
        <div v-else-if="error" class="h-48 w-48 flex items-center justify-center rounded-lg border border-border bg-red-500/10">
          <span class="text-sm text-red-500">{{ error }}</span>
        </div>
        <div v-else class="h-48 w-48 rounded-lg border border-border bg-white p-2">
          <img
            v-if="qrCode"
            :src="qrCode"
            alt="扫码登录"
            class="h-full w-full"
          />
        </div>
        
        <p v-if="countdown > 0" class="text-sm text-muted-foreground">
          {{ Math.floor(countdown / 60) }}:{{ (countdown % 60).toString().padStart(2, "0") }} 后过期
        </p>
        <p v-else class="text-sm text-red-500">
          二维码已过期，请重新获取
        </p>
      </div>
      
      <DialogFooter>
        <Button variant="outline" @click="emit('update:open', false)">
          取消
        </Button>
        <Button :disabled="loading" @click="startQrLogin">
          刷新二维码
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
