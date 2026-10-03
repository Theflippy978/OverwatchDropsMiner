<script setup lang="ts">
import { ref } from "vue";
import { openUrl } from "@tauri-apps/plugin-opener";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

const open = defineModel<boolean>("open", { required: false, default: false });

const props = defineProps<{
  latestVersion: string;
  releaseUrl: string;
}>();

const downloading = ref(false);
const error = ref("");

/** release_url 来自 sidecar 的 check_update 响应，Rust 侧已做
    host 前缀白名单（GitHub 系）。这里再校验一次协议：
    opener 插件虽已限制 scheme 为 http/https/mailto/tel（file:// 被挡），
    但组件作为通用组件不该对 URL 放任不管。 */
function safeReleaseUrl(raw: string): string | null {
  try {
    const u = new URL(raw);
    return u.protocol === "https:" ? u.toString() : null;
  } catch {
    return null;
  }
}

async function handleDownload() {
  downloading.value = true;
  error.value = "";
  try {
    const url = safeReleaseUrl(props.releaseUrl);
    if (!url) {
      error.value = "下载链接无效或非 HTTPS，已阻止打开";
      return;
    }
    await openUrl(url);
  } catch (e) {
    error.value = `打开下载页面失败: ${e}`;
  } finally {
    downloading.value = false;
  }
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>发现新版本</DialogTitle>
        <DialogDescription>
          有新版本 {{ latestVersion }} 可用，建议更新以获得最新功能和修复。
        </DialogDescription>
      </DialogHeader>
      <p v-if="error" class="break-all text-xs text-signal-danger" role="alert">
        {{ error }}
      </p>
      <DialogFooter class="gap-2">
        <Button variant="outline" @click="open = false">
          稍后提醒
        </Button>
        <Button :disabled="downloading" @click="handleDownload">
          {{ downloading ? "正在打开..." : "前往下载" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
