<script setup lang="ts">
import { computed } from "vue";
import { Button } from "@/components/ui/button";

const props = defineProps<{
  collapsed?: boolean;
}>();

const emit = defineEmits<{
  toggle: [];
  navigate: [view: string];
}>();

const navItems = [
  { id: "dashboard", label: "仪表盘", icon: "📊" },
  { id: "accounts", label: "账号管理", icon: "👥" },
  { id: "tasks", label: "任务管理", icon: "📋" },
  { id: "logs", label: "日志", icon: "📝" },
  { id: "settings", label: "设置", icon: "⚙️" },
];
</script>

<template>
  <div
    class="flex h-full flex-col border-r border-border bg-card"
    :class="collapsed ? 'w-16' : 'w-56'"
  >
    <!-- 折叠按钮 -->
    <div class="flex h-14 items-center justify-between border-b border-border px-4">
      <span v-if="!collapsed" class="font-bold">OW Miner</span>
      <Button variant="ghost" size="sm" @click="emit('toggle')">
        {{ collapsed ? "→" : "←" }}
      </Button>
    </div>

    <!-- 导航项 -->
    <nav class="flex-1 space-y-1 p-2">
      <button
        v-for="item in navItems"
        :key="item.id"
        class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm hover:bg-accent transition-colors"
        :class="{ 'justify-center': collapsed }"
        @click="emit('navigate', item.id)"
      >
        <span class="text-lg">{{ item.icon }}</span>
        <span v-if="!collapsed">{{ item.label }}</span>
      </button>
    </nav>
  </div>
</template>
