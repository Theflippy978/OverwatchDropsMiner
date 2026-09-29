<script setup lang="ts">
import { ref } from "vue";
import { useAccountsStore } from "@/stores/accounts";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";

const accountsStore = useAccountsStore();

const emit = defineEmits<{
  select: [accountId: string];
}>();

const showAddDialog = ref(false);
const newCookie = ref("");
const adding = ref(false);

async function handleAddAccount() {
  if (!newCookie.value.trim()) return;
  adding.value = true;
  try {
    await accountsStore.addAccount(newCookie.value.trim());
    newCookie.value = "";
    showAddDialog.value = false;
  } finally {
    adding.value = false;
  }
}

async function handleRemoveAccount(accountId: string) {
  if (confirm("确定要删除该账号吗？")) {
    await accountsStore.removeAccount(accountId);
  }
}

async function handleStart(accountId: string) {
  const config = {
    room_ids: [],
    thread_count: 60,
    reconnect_delay_seconds: 8,
    task_ids: [],
    task_query_interval_seconds: 30,
    notify_urls: [],
  };
  await accountsStore.startMiner(accountId, config);
}

async function handleStop(accountId: string) {
  await accountsStore.stopMiner(accountId);
}
</script>

<template>
  <Card class="h-full">
    <CardHeader class="pb-3">
      <div class="flex items-center justify-between">
        <CardTitle class="text-sm">账号列表</CardTitle>
        <Dialog v-model:open="showAddDialog">
          <DialogTrigger as-child>
            <Button size="sm" class="h-7 text-xs">
              + 添加账号
            </Button>
          </DialogTrigger>
          <DialogContent class="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>添加账号</DialogTitle>
            </DialogHeader>
            <div class="space-y-4 py-4">
              <div class="space-y-2">
                <label class="text-sm font-medium">Cookie</label>
                <Input
                  v-model="newCookie"
                  placeholder="粘贴 B 站 Cookie..."
                  class="font-mono text-xs"
                />
              </div>
              <div class="flex justify-end gap-2">
                <Button variant="outline" size="sm" @click="showAddDialog = false">
                  取消
                </Button>
                <Button size="sm" :disabled="adding" @click="handleAddAccount">
                  {{ adding ? "添加中..." : "添加" }}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </CardHeader>
    <CardContent class="pt-0">
      <ScrollArea class="h-[calc(100vh-280px)]">
        <div v-if="accountsStore.loading" class="py-8 text-center text-sm text-muted-foreground">
          加载中...
        </div>
        <div v-else-if="accountsStore.accounts.length === 0" class="py-8 text-center text-sm text-muted-foreground">
          暂无账号，点击上方按钮添加
        </div>
        <div v-else class="space-y-2">
          <div
            v-for="account in accountsStore.accounts"
            :key="account.id"
            class="flex items-center justify-between rounded-lg border border-border p-3 hover:bg-accent/50"
          >
            <div class="flex items-center gap-3">
              <span
                class="h-2.5 w-2.5 rounded-full"
                :class="account.running ? 'bg-green-500' : 'bg-muted'"
              />
              <div>
                <p class="text-sm font-medium">{{ account.remark }}</p>
                <p class="text-xs text-muted-foreground">{{ account.id.slice(0, 12) }}...</p>
              </div>
            </div>
            <div class="flex items-center gap-1">
              <Button
                v-if="!account.running"
                size="sm"
                variant="outline"
                class="h-7 text-xs"
                @click="handleStart(account.id)"
              >
                启动
              </Button>
              <Button
                v-else
                size="sm"
                variant="destructive"
                class="h-7 text-xs"
                @click="handleStop(account.id)"
              >
                停止
              </Button>
              <Button
                size="sm"
                variant="ghost"
                class="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                @click="handleRemoveAccount(account.id)"
              >
                ✕
              </Button>
            </div>
          </div>
        </div>
      </ScrollArea>
    </CardContent>
  </Card>
</template>

