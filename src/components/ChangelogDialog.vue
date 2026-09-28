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
import { ScrollArea } from "@/components/ui/scroll-area";

defineProps<{
  open: boolean;
}>();

const emit = defineEmits<{
  "update:open": [value: boolean];
}>();

const changelog = [
  {
    version: "1.0.0",
    date: "2026-09-28",
    changes: [
      "全新 Tauri 2 + Vue 3 架构",
      "现代化 UI 设计",
      "支持多账号管理",
      "实时日志监控",
      "自动领取奖励",
    ],
  },
  {
    version: "0.9.0",
    date: "2026-09-01",
    changes: [
      "新增扫码登录功能",
      "优化任务进度显示",
      "修复若干已知问题",
    ],
  },
];
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>更新日志</DialogTitle>
        <DialogDescription>
          查看版本更新历史
        </DialogDescription>
      </DialogHeader>
      
      <ScrollArea class="h-96">
        <div class="space-y-4 py-4">
          <div
            v-for="release in changelog"
            :key="release.version"
            class="space-y-2"
          >
            <div class="flex items-center justify-between">
              <h3 class="text-sm font-medium">v{{ release.version }}</h3>
              <span class="text-xs text-muted-foreground">{{ release.date }}</span>
            </div>
            <ul class="list-inside list-disc space-y-1 text-xs text-muted-foreground">
              <li v-for="change in release.changes" :key="change">
                {{ change }}
              </li>
            </ul>
          </div>
        </div>
      </ScrollArea>
      
      <DialogFooter>
        <Button variant="outline" @click="emit('update:open', false)">
          关闭
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
