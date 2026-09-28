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

const shortcuts = [
  { key: "Ctrl + S", description: "保存配置" },
  { key: "Ctrl + R", description: "刷新任务" },
  { key: "Ctrl + Q", description: "退出应用" },
  { key: "F1", description: "打开帮助" },
  { key: "F5", description: "刷新页面" },
];
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>键盘快捷键</DialogTitle>
        <DialogDescription>
          使用快捷键提高操作效率
        </DialogDescription>
      </DialogHeader>
      
      <div class="space-y-2 py-4">
        <div
          v-for="shortcut in shortcuts"
          :key="shortcut.key"
          class="flex items-center justify-between rounded-lg border border-border p-2"
        >
          <span class="text-sm">{{ shortcut.description }}</span>
          <kbd class="rounded border border-border bg-muted px-2 py-1 text-xs font-mono">
            {{ shortcut.key }}
          </kbd>
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
