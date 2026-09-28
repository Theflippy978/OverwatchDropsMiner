<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

defineProps<{
  open: boolean;
}>();

const emit = defineEmits<{
  "update:open": [value: boolean];
}>();

const metrics = ref({
  cpu: 0,
  memory: 0,
  disk: 0,
  network: 0,
});

let interval: number | null = null;

onMounted(() => {
  interval = window.setInterval(() => {
    metrics.value = {
      cpu: Math.random() * 30 + 10,
      memory: Math.random() * 20 + 40,
      disk: Math.random() * 10 + 20,
      network: Math.random() * 50 + 10,
    };
  }, 1000);
});

onUnmounted(() => {
  if (interval) clearInterval(interval);
});
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>性能监控</DialogTitle>
        <DialogDescription>
          实时监控系统资源使用情况
        </DialogDescription>
      </DialogHeader>
      
      <div class="space-y-4 py-4">
        <div class="space-y-2">
          <div class="flex items-center justify-between text-sm">
            <span>CPU 使用率</span>
            <span>{{ metrics.cpu.toFixed(1) }}%</span>
          </div>
          <Progress :value="metrics.cpu" class="h-2" />
        </div>
        
        <div class="space-y-2">
          <div class="flex items-center justify-between text-sm">
            <span>内存使用率</span>
            <span>{{ metrics.memory.toFixed(1) }}%</span>
          </div>
          <Progress :value="metrics.memory" class="h-2" />
        </div>
        
        <div class="space-y-2">
          <div class="flex items-center justify-between text-sm">
            <span>磁盘使用率</span>
            <span>{{ metrics.disk.toFixed(1) }}%</span>
          </div>
          <Progress :value="metrics.disk" class="h-2" />
        </div>
        
        <div class="space-y-2">
          <div class="flex items-center justify-between text-sm">
            <span>网络使用率</span>
            <span>{{ metrics.network.toFixed(1) }}%</span>
          </div>
          <Progress :value="metrics.network" class="h-2" />
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
