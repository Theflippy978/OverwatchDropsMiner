<script setup lang="ts">
import { ref, onMounted } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { useConfigStore } from "@/stores/config";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";

const configStore = useConfigStore();
const loading = ref(false);
const testing = ref(false);
const testResult = ref("");
const saveNotice = ref("");
const saveNoticeError = ref(false);

onMounted(async () => {
  loading.value = true;
  try {
    await configStore.ensureLoaded();
  } finally {
    loading.value = false;
  }
});

// 统一走 configStore.save()：原实现自构造 config 会用空值覆盖
// 房间号/线程数等配置（与 ConfigForm 数据源分裂）
async function handleSave() {
  loading.value = true;
  saveNotice.value = "";
  try {
    await configStore.save();
    saveNotice.value = "配置已保存";
    saveNoticeError.value = false;
  } catch (e) {
    saveNotice.value = `保存配置失败: ${e}`;
    saveNoticeError.value = true;
  } finally {
    loading.value = false;
  }
}

async function handleVerboseToggle() {
  saveNotice.value = "";
  try {
    await configStore.save();
    saveNotice.value = "配置已保存";
    saveNoticeError.value = false;
  } catch (e) {
    saveNotice.value = `保存配置失败: ${e}`;
    saveNoticeError.value = true;
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
        <div class="flex items-center gap-2">
          <Button size="sm" variant="outline" class="h-7 text-xs" :disabled="loading" @click="handleSave">
            保存
          </Button>
          <span
            v-if="saveNotice"
            class="text-xs"
            :class="saveNoticeError ? 'text-destructive' : 'text-muted-foreground'"
          >
            {{ saveNotice }}
          </span>
        </div>
      </div>
    </CardHeader>
    <CardContent class="pt-0">
      <div class="space-y-4">
        <!-- 通知 URL -->
        <div class="space-y-2">
          <Label for="notifyUrls" class="text-xs">通知 Webhook URL</Label>
          <Input
            id="notifyUrls"
            v-model="configStore.config.notify_urls_text"
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
            <Switch v-model="configStore.config.notify_on_task_complete" />
          </div>

          <div class="flex items-center justify-between">
            <div class="space-y-0.5">
              <Label class="text-xs">自动领取奖励</Label>
              <p class="text-xs text-muted-foreground">任务完成后自动领取奖励</p>
            </div>
            <Switch v-model="configStore.config.auto_claim_rewards" />
          </div>

          <div class="flex items-center justify-between">
            <div class="space-y-0.5">
              <Label class="text-xs">详细日志</Label>
              <p class="text-xs text-muted-foreground">输出更详细的运行日志</p>
            </div>
            <Switch
              v-model="configStore.config.verbose"
              @update:model-value="handleVerboseToggle"
            />
          </div>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
