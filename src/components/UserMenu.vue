<script setup lang="ts">
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const emit = defineEmits<{
  profile: [];
  settings: [];
  logout: [];
}>();
</script>

<template>
  <DropdownMenu>
    <DropdownMenuTrigger as-child>
      <Button variant="ghost" size="sm" class="relative h-8 w-8 rounded-full">
        <span class="text-sm">👤</span>
      </Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent class="w-56" align="end">
      <DropdownMenuLabel>我的账号</DropdownMenuLabel>
      <DropdownMenuSeparator />
      <DropdownMenuItem @click="emit('profile')">
        个人资料
      </DropdownMenuItem>
      <DropdownMenuItem @click="emit('settings')">
        设置
      </DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem @click="emit('logout')">
        退出登录
      </DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>
</template>
