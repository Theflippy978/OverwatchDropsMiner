<script setup lang="ts">
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const emit = defineEmits<{
  startAll: [];
  stopAll: [];
  refresh: [];
  settings: [];
}>();
</script>

<template>
  <Card>
    <CardHeader>
      <CardTitle class="text-sm">快速操作</CardTitle>
    </CardHeader>
    <CardContent>
      <div class="grid grid-cols-2 gap-2">
        <Button
          variant="default"
          size="sm"
          @click="emit('startAll')"
        >
          全部启动
        </Button>
        <Button
          variant="destructive"
          size="sm"
          @click="emit('stopAll')"
        >
          全部停止
        </Button>
        <Button
          variant="outline"
          size="sm"
          @click="emit('refresh')"
        >
          刷新任务
        </Button>
        <Button
          variant="outline"
          size="sm"
          @click="emit('settings')"
        >
          设置
        </Button>
      </div>
    </CardContent>
  </Card>
</template>
