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
        <DialogTitle>帮助中心</DialogTitle>
        <DialogDescription>
          常见问题和使用指南
        </DialogDescription>
      </DialogHeader>
      
      <div class="space-y-4 py-4">
        <div class="space-y-2">
          <h3 class="text-sm font-medium">如何添加账号？</h3>
          <p class="text-xs text-muted-foreground">
            点击"添加账号"按钮，选择扫码登录或手动粘贴 Cookie。
          </p>
        </div>
        
        <div class="space-y-2">
          <h3 class="text-sm font-medium">如何启动挂机？</h3>
          <p class="text-xs text-muted-foreground">
            在账号列表中选择账号，点击"启动"按钮即可开始挂机。
          </p>
        </div>
        
        <div class="space-y-2">
          <h3 class="text-sm font-medium">如何查看日志？</h3>
          <p class="text-xs text-muted-foreground">
            在主界面下方的日志区域可以查看实时运行日志。
          </p>
        </div>
        
        <div class="space-y-2">
          <h3 class="text-sm font-medium">如何设置通知？</h3>
          <p class="text-xs text-muted-foreground">
            在设置页面配置 Gotify、企业微信或 Server酱 等通知渠道。
          </p>
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
