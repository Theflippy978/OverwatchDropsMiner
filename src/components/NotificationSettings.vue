<script setup lang="ts">
import { ref, onMounted } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";

const notifyUrls = ref("");
const notifyOnTaskComplete = ref(true);
const autoClaimRewards = ref(false);
const verbose = ref(false);
const loading = ref(false);
const testing = ref(false);
const testResult = ref("");

onMounted(async () => {
  loading.value = true;
  try {
    const config = await invoke<any>("load_config");
    notifyUrls.value = config.notify_urls_text || "";
    notifyOnTaskComplete.value = config.notify_on_task_complete ?? true;
    autoClaimRewards.value = config.auto_claim_rewards ?? false;
    verbose.value = config.verbose ?? false;
  } finally {
    loading.value = false;
  }
});

async function handleSave() {
  loading.value = true;
  try {
    await invoke("save_config", {
      config: {
        cookie: "",
        rooms_text: "",
        thread_count_text: "60",
        reconnect_delay_text: "8",
        task_ids_text: "",
        task_query_interval_text: "30",
        notify_urls_text: notifyUrls.value,
        notify_on_task_complete: notifyOnTaskComplete.value,
        verbose: verbose.value,
        auto_claim_rewards: autoClaimRewards.value,
      },
    });
  } finally {
    loading.value = false;
  }
}

async function handleTest() {
  testing.value = true;
  testResult.value = "";
  try {
    const ok = await invoke<boolean>("send_notification", {
      title: "Overwatch Drops Miner",
      body: "这是一条测试通知，收到即表示配置成功",
    });
    testResult.value = ok ? "已发送" : "发送失败，请检查通知 URL";
  } catch (e) {
    testResult.value = `发送失败: ${e}`;
  } finally {
    testing.value = false;
  }
}
</script>

<template>
  <Card>
    <CardHeader class="pb-3">
      <div class="flex items-center justify-between">
        <CardTitle class="text-sm">通知设置</CardTitle>
        <Button size="sm" variant="outline" class="h-7 text-xs" :disabled="loading" @click="handleSave">
          保存
        </Button>
      </div>
    </CardHeader>
    <CardContent class="pt-0">
      <div class="space-y-4">
        <!-- 通知 URL -->
        <div class="space-y-2">
          <Label for="notifyUrls" class="text-xs">通知 Webhook URL</Label>
          <Input
            id="notifyUrls"
            v-model="notifyUrls"
            placeholder="Gotify / 企业微信 / Server酱"
            class="h-8 text-xs"
          />
          <p class="text-xs text-muted-foreground">
            支持 Gotify、企业微信、Server酱 等通知渠道，多个用逗号分隔
          </p>
          <div class="flex items-center gap-2">
            <Button size="sm" variant="secondary" class="h-7 text-xs" :disabled="testing" @click="handleTest">
              {{ testing ? "发送中..." : "测试通知" }}
            </Button>
            <span v-if="testResult" class="text-xs text-muted-foreground">{{ testResult }}</span>
          </div>
        </div>

        <Separator />

        <!-- 开关选项 -->
        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <div class="space-y-0.5">
              <Label class="text-xs">任务完成通知</Label>
              <p class="text-xs text-muted-foreground">任务完成时发送通知</p>
            </div>
            <Switch v-model:checked="notifyOnTaskComplete" />
          </div>

          <div class="flex items-center justify-between">
            <div class="space-y-0.5">
              <Label class="text-xs">自动领取奖励</Label>
              <p class="text-xs text-muted-foreground">任务完成后自动领取奖励</p>
            </div>
            <Switch v-model:checked="autoClaimRewards" />
          </div>

          <div class="flex items-center justify-between">
            <div class="space-y-0.5">
              <Label class="text-xs">详细日志</Label>
              <p class="text-xs text-muted-foreground">输出更详细的运行日志</p>
            </div>
            <Switch v-model:checked="verbose" />
          </div>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
