<script setup lang="ts">
import { onMounted } from "vue";
import { useConfigStore } from "@/stores/config";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";

const configStore = useConfigStore();

onMounted(async () => {
  await configStore.load();
});

async function handleSave() {
  await configStore.save();
}
</script>

<template>
  <Card>
    <CardHeader class="pb-3">
      <div class="flex items-center justify-between">
        <CardTitle class="text-sm">挂机配置</CardTitle>
        <Button size="sm" variant="outline" class="h-7 text-xs" @click="handleSave">
          保存配置
        </Button>
      </div>
    </CardHeader>
    <CardContent class="pt-0">
      <div class="grid grid-cols-2 gap-4">
        <div class="space-y-2">
          <Label for="rooms" class="text-xs">直播间号</Label>
          <Input
            id="rooms"
            v-model="configStore.config.rooms_text"
            placeholder="多个用逗号分隔"
            class="h-8 text-xs"
          />
        </div>
        <div class="space-y-2">
          <Label for="threads" class="text-xs">线程数 (60-128)</Label>
          <Input
            id="threads"
            v-model="configStore.config.thread_count_text"
            type="number"
            min="1"
            max="128"
            class="h-8 text-xs"
          />
        </div>
        <div class="space-y-2">
          <Label for="reconnect" class="text-xs">重连延迟 (秒)</Label>
          <Input
            id="reconnect"
            v-model="configStore.config.reconnect_delay_text"
            type="number"
            min="1"
            class="h-8 text-xs"
          />
        </div>
        <div class="space-y-2">
          <Label for="interval" class="text-xs">任务查询间隔 (秒)</Label>
          <Input
            id="interval"
            v-model="configStore.config.task_query_interval_text"
            type="number"
            min="10"
            class="h-8 text-xs"
          />
        </div>
        <div class="space-y-2">
          <Label for="taskIds" class="text-xs">任务 ID</Label>
          <Input
            id="taskIds"
            v-model="configStore.config.task_ids_text"
            placeholder="多个用逗号分隔"
            class="h-8 text-xs"
          />
        </div>
        <div class="space-y-2">
          <Label for="notifyUrls" class="text-xs">通知 URL</Label>
          <Input
            id="notifyUrls"
            v-model="configStore.config.notify_urls_text"
            placeholder="Gotify / 企业微信 / Server酱"
            class="h-8 text-xs"
          />
        </div>
      </div>
    </CardContent>
  </Card>
</template>
