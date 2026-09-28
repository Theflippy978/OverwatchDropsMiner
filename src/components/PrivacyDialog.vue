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
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>隐私政策</DialogTitle>
        <DialogDescription>
          我们如何保护您的隐私
        </DialogDescription>
      </DialogHeader>
      
      <ScrollArea class="h-96">
        <div class="space-y-4 py-4 text-xs text-muted-foreground">
          <h3 class="text-sm font-medium text-foreground">信息收集</h3>
          <p>
            我们不会收集您的任何个人信息。所有数据都存储在本地。
          </p>
          
          <h3 class="text-sm font-medium text-foreground">Cookie 使用</h3>
          <p>
            您的 B 站 Cookie 仅用于登录和挂机，不会上传到任何服务器。
          </p>
          
          <h3 class="text-sm font-medium text-foreground">数据安全</h3>
          <p>
            您的账号信息使用 DPAPI 加密存储在本地，确保数据安全。
          </p>
          
          <h3 class="text-sm font-medium text-foreground">第三方服务</h3>
 <p>
            我们不会与任何第三方分享您的数据。
          </p>
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
