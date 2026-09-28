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
        <DialogTitle>服务条款</DialogTitle>
        <DialogDescription>
          使用本软件即表示您同意以下条款
        </DialogDescription>
      </DialogHeader>
      
      <ScrollArea class="h-96">
        <div class="space-y-4 py-4 text-xs text-muted-foreground">
          <h3 class="text-sm font-medium text-foreground">1. 使用许可</h3>
          <p>
            本软件仅供个人学习和使用，不得用于商业用途。
          </p>
          
          <h3 class="text-sm font-medium text-foreground">2. 责任限制</h3>
          <p>
            本软件按"原样"提供，不提供任何明示或暗示的担保。
          </p>
          
          <h3 class="text-sm font-medium text-foreground">3. 使用限制</h3>
          <p>
            您不得使用本软件进行任何违法活动。
          </p>
          
          <h3 class="text-sm font-medium text-foreground">4. 终止</h3>
          <p>
            如果您违反这些条款，我们有权终止您的使用许可。
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
