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

function handleDownload() {
  downloading.value = true;
  openUrl(props.releaseUrl);
  downloading.value = false;
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
