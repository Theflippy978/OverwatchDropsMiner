<script setup lang="ts">
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

defineProps<{
  open: boolean;
}>();

const emit = defineEmits<{
  "update:open": [value: boolean];
}>();
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>关于守望先锋直播掉宝助手</DialogTitle>
        <DialogDescription>
          版本 1.0.0
        </DialogDescription>
      </DialogHeader>
      
      <div class="space-y-4 py-4">
        <p class="text-sm text-muted-foreground">
          守望先锋直播掉宝助手是一款专为守望先锋直播掉宝设计的自动化挂机工具。
        </p>
        <div class="space-y-2 text-sm">
          <p><strong>开发者：</strong> Theflippy</p>
          <p><strong>许可证：</strong> GPL v3</p>
          <p><strong>技术栈：</strong> Tauri 2 + Vue 3 + Python</p>
        </div>
      </div>
      
      <DialogFooter>
        <Button variant="outline" @click="emit('update:open', false)">
          关闭
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
