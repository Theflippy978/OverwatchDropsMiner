<script setup lang="ts">
import { ref } from "vue";
import { openUrl } from "@tauri-apps/plugin-opener";
import { LoaderCircle } from "lucide-vue-next";
import { formatIpcError } from "@/lib/ipc-error";
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
    error.value = formatIpcError(e, "打开下载页面失败");
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
      <!-- text-sm 而不是 text-xs：ConfirmDialog 与 QrLoginDialog 的框内错误
           都用 text-sm，同一语义在三处应保持同一字号。 -->
      <p v-if="error" class="break-all text-sm text-signal-danger" role="alert">
        {{ error }}
      </p>
      <DialogFooter class="gap-2">
        <Button variant="outline" @click="open = false">
          稍后提醒
        </Button>
        <!-- 宽度必须恒定，否则加载时按钮变宽会把左侧「稍后提醒」挤得位移
             （「按钮文案别变宽」是同一类问题）。

             做法（两点缺一不可）：
             ① 文案恒为「前往下载」，等待期只靠 disabled + 转圈表达。
                不用「正在打开...」—— 那是 6 个汉字 + 3 个点（≈105px），
                比 4 个汉字宽 49px，光靠 min-w 挡不住（内容会撑开按钮）。
                这与 AccountList 启停按钮「文案恒为启动/停止」的既有决策同构。
             ② 转圈**始终占位**（非 loading 时 invisible 而非 v-if）：
                否则它出现/消失本身又会带来 24px（16 图标 + 8 gap）的位移。
                用预留空间换零抖动，与 TaskProgress「奖励名固定预留 8 汉字」
                是同一个取舍。

             ⚠ 此前我加的是 `min-w-[104px]`，那是**无效防抖**：
             min-width 只是下限，内容更宽时按钮照样被撑开。 -->
        <Button :disabled="downloading" class="min-w-[112px]" @click="handleDownload">
          <LoaderCircle
            class="h-4 w-4"
            :class="downloading ? 'animate-spin' : 'invisible'"
            aria-hidden="true"
          />
          前往下载
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
