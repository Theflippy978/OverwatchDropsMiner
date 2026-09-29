<script setup lang="ts">
import { ref, onMounted } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { save, open } from "@tauri-apps/plugin-dialog";
import { useConfigStore } from "@/stores/config";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const configStore = useConfigStore();

interface TaskGroup {
  label: string;
  task_ids: string[];
  active: boolean;
}

const fetchingRoom = ref(false);
const fetchingTasks = ref(false);
const fetchError = ref("");

const showGroupDialog = ref(false);
const pendingGroups = ref<TaskGroup[]>([]);
const selectedGroupIndex = ref(0);

onMounted(async () => {
  await configStore.ensureLoaded();
});

async function handleSave() {
  await configStore.save();
}

async function handleExport() {
  const filePath = await save({
    defaultPath: "config.json",
    filters: [{ name: "JSON", extensions: ["json"] }],
  });
  if (!filePath) return;
  await invoke("export_config", { path: filePath });
}

async function handleImport() {
  const filePath = await open({
    multiple: false,
    filters: [{ name: "JSON", extensions: ["json"] }],
  });
  if (!filePath || typeof filePath !== "string") return;
  await invoke("import_config", { path: filePath });
  await configStore.load();
}

function firstRoomId(): number {
  const match = configStore.config.rooms_text.match(/\d+/);
  return match ? parseInt(match[0], 10) : 0;
}

function applyGroup(group: TaskGroup) {
  configStore.config.task_ids_text = group.task_ids.join(",");
}

function applyGroups(groups: TaskGroup[], roomId: number | null | undefined) {
  if (roomId && roomId > 0) {
    configStore.config.rooms_text = String(roomId);
  }
  if (groups.length === 0) {
    fetchError.value = "未解析到掉宝任务分组";
    return;
  }
  if (groups.length === 1) {
    applyGroup(groups[0]);
    return;
  }
  pendingGroups.value = groups;
  selectedGroupIndex.value = Math.max(
    0,
    groups.findIndex((g) => g.active)
  );
  showGroupDialog.value = true;
}

function confirmGroupSelection() {
  const group = pendingGroups.value[selectedGroupIndex.value];
  if (group) applyGroup(group);
  showGroupDialog.value = false;
}

async function handleFetchRoom() {
  if (fetchingRoom.value) return;
  fetchingRoom.value = true;
  fetchError.value = "";
  try {
    const result = await invoke<{ room_id: number }>("auto_fetch_room_id");
    configStore.config.rooms_text = String(result.room_id);
  } catch (e) {
    fetchError.value = `自动获取房间号失败: ${e}`;
  } finally {
    fetchingRoom.value = false;
  }
}

async function handleFetchTaskIdsMode1() {
  if (fetchingTasks.value) return;
  const roomId = firstRoomId();
  if (!roomId) {
    fetchError.value = "请先填写房间号，或改用模式2自动获取";
    return;
  }
  fetchingTasks.value = true;
  fetchError.value = "";
  try {
    const result = await invoke<{ room_id: number; groups: TaskGroup[] }>(
      "auto_fetch_task_ids",
      { roomId }
    );
    applyGroups(result.groups, result.room_id);
  } catch (e) {
    fetchError.value = `自动获取模式1失败: ${e}`;
  } finally {
    fetchingTasks.value = false;
  }
}

async function handleFetchTaskIdsMode2() {
  if (fetchingTasks.value) return;
  fetchingTasks.value = true;
  fetchError.value = "";
  try {
    const result = await invoke<{
      room_id: number | null;
      groups: TaskGroup[];
    }>("auto_fetch_task_ids_mode2", { roomId: firstRoomId() || null });
    applyGroups(result.groups, result.room_id);
  } catch (e) {
    fetchError.value = `自动获取模式2失败: ${e}`;
  } finally {
    fetchingTasks.value = false;
  }
}
</script>

<template>
  <Card>
    <CardHeader class="pb-3">
      <div class="flex items-center justify-between">
        <CardTitle class="text-sm">挂机配置</CardTitle>
        <div class="flex gap-1">
          <Button size="sm" variant="outline" class="h-7 text-xs" @click="handleImport">
            导入
          </Button>
          <Button size="sm" variant="outline" class="h-7 text-xs" @click="handleExport">
            导出
          </Button>
          <Button size="sm" variant="outline" class="h-7 text-xs" @click="handleSave">
            保存配置
          </Button>
        </div>
      </div>
    </CardHeader>
    <CardContent class="pt-0">
      <div class="grid grid-cols-2 gap-4">
        <div class="space-y-2">
          <Label for="rooms" class="text-xs">直播间号</Label>
          <div class="flex gap-2">
            <Input
              id="rooms"
              v-model="configStore.config.rooms_text"
              placeholder="多个用逗号分隔"
              class="h-8 min-w-0 flex-1 text-xs"
            />
            <Button
              size="sm"
              variant="outline"
              class="h-8 shrink-0 text-xs"
              :disabled="fetchingRoom"
              @click="handleFetchRoom"
            >
              {{ fetchingRoom ? "捕获中..." : "自动获取" }}
            </Button>
          </div>
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
          <div class="flex gap-2">
            <Input
              id="taskIds"
              v-model="configStore.config.task_ids_text"
              placeholder="多个用逗号分隔"
              class="h-8 min-w-0 flex-1 text-xs"
            />
            <Button
              size="sm"
              variant="outline"
              class="h-8 shrink-0 text-xs"
              :disabled="fetchingTasks"
              @click="handleFetchTaskIdsMode1"
            >
              模式1
            </Button>
            <Button
              size="sm"
              variant="outline"
              class="h-8 shrink-0 text-xs"
              :disabled="fetchingTasks"
              @click="handleFetchTaskIdsMode2"
            >
              {{ fetchingTasks ? "捕获中..." : "模式2" }}
            </Button>
          </div>
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

      <p
        v-if="fetchError"
        class="mt-3 break-all text-xs text-red-500"
      >
        {{ fetchError }}
      </p>
      <p class="mt-2 text-xs text-muted-foreground">
        模式1：纯 HTTP 抓取直播间页面（需先填房间号）；模式2：浏览器嗅探（自动同时获取房间号）
      </p>
    </CardContent>

    <!-- 任务组选择（多个分组时弹出，对齐原 QInputDialog.getItem） -->
    <Dialog v-model:open="showGroupDialog">
      <DialogContent class="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>选择掉宝任务组</DialogTitle>
          <DialogDescription>
            检测到多个按日期分组的掉宝任务，请选择要填入的一组
          </DialogDescription>
        </DialogHeader>
        <div class="space-y-2 py-2">
          <label
            v-for="(group, index) in pendingGroups"
            :key="index"
            class="flex cursor-pointer items-center gap-2 rounded-md border p-2 text-sm"
            :class="
              index === selectedGroupIndex
                ? 'border-primary bg-accent/60'
                : 'border-border hover:bg-accent/50'
            "
          >
            <input
              v-model="selectedGroupIndex"
              type="radio"
              :value="index"
              class="accent-primary"
            />
            <span>{{ group.label }}（{{ group.task_ids.length }} 个任务）</span>
          </label>
        </div>
        <div class="flex justify-end gap-2">
          <Button variant="outline" size="sm" @click="showGroupDialog = false">
            取消
          </Button>
          <Button size="sm" @click="confirmGroupSelection">
            填入选中分组
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  </Card>
</template>
