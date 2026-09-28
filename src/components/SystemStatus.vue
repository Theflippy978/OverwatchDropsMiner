<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const systemStatus = ref({
  cpu: 0,
  memory: 0,
  uptime: 0,
});

let interval: number | null = null;

onMounted(() => {
  // 模拟系统状态更新
  interval = window.setInterval(() => {
    systemStatus.value = {
      cpu: Math.random() * 30 + 10,
      memory: Math.random() * 20 + 40,
      uptime: systemStatus.value.uptime + 1,
    };
  }, 1000);
});

onUnmounted(() => {
  if (interval) clearInterval(interval);
});

const uptimeFormatted = computed(() => {
  const hours = Math.floor(systemStatus.value.uptime / 3600);
  const minutes = Math.floor((systemStatus.value.uptime % 3600) / 60);
  const seconds = systemStatus.value.uptime % 60;
  return `${hours.toString().padStart(2, "0")}:${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
});

import { computed } from "vue";
</script>

<template>
  <Card>
    <CardHeader>
      <CardTitle class="text-sm">系统状态</CardTitle>
    </CardHeader>
    <CardContent>
      <div class="space-y-3">
        <div class="flex items-center justify-between">
          <span class="text-sm text-muted-foreground">CPU 使用率</span>
          <Badge variant="outline">{{ systemStatus.cpu.toFixed(1) }}%</Badge>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-sm text-muted-foreground">内存使用率</span>
          <Badge variant="outline">{{ systemStatus.memory.toFixed(1) }}%</Badge>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-sm text-muted-foreground">运行时间</span>
          <Badge variant="outline">{{ uptimeFormatted }}</Badge>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
