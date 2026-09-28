<script setup lang="ts">
import { ref } from "vue";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

const settings = ref({
  autoStart: false,
  minimizeToTray: true,
  startMinimized: false,
  checkUpdate: true,
  language: "zh-CN",
});

const emit = defineEmits<{
  save: [settings: typeof settings.value];
}>();
</script>

<template>
  <div class="space-y-6">
    <Card>
      <CardHeader>
        <CardTitle>常规设置</CardTitle>
        <CardDescription>基本应用设置</CardDescription>
      </CardHeader>
      <CardContent class="space-y-4">
        <div class="flex items-center justify-between">
          <div class="space-y-0.5">
            <Label>开机自启动</Label>
            <p class="text-xs text-muted-foreground">系统启动时自动运行</p>
          </div>
          <Switch v-model:checked="settings.autoStart" />
        </div>
        <Separator />
        <div class="flex items-center justify-between">
          <div class="space-y-0.5">
            <Label>最小化到托盘</Label>
            <p class="text-xs text-muted-foreground">关闭窗口时最小化到系统托盘</p>
          </div>
          <Switch v-model:checked="settings.minimizeToTray" />
        </div>
        <Separator />
        <div class="flex items-center justify-between">
          <div class="space-y-0.5">
            <Label>启动时最小化</Label>
            <p class="text-xs text-muted-foreground">应用启动时自动最小化</p>
          </div>
          <Switch v-model:checked="settings.startMinimized" />
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>更新设置</CardTitle>
        <CardDescription>软件更新相关设置</CardDescription>
      </CardHeader>
      <CardContent class="space-y-4">
        <div class="flex items-center justify-between">
          <div class="space-y-0.5">
            <Label>自动检查更新</Label>
            <p class="text-xs text-muted-foreground">启动时自动检查新版本</p>
          </div>
          <Switch v-model:checked="settings.checkUpdate" />
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>语言设置</CardTitle>
        <CardDescription>界面语言</CardDescription>
      </CardHeader>
      <CardContent>
        <div class="space-y-2">
          <Label>语言</Label>
          <Input v-model="settings.language" disabled />
        </div>
      </CardContent>
    </Card>

    <div class="flex justify-end">
      <Button @click="emit('save', settings)">
        保存设置
      </Button>
    </div>
  </div>
</template>
