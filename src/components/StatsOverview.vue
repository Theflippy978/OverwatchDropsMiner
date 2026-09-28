<script setup lang="ts">
import { computed } from "vue";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

const props = defineProps<{
  totalAccounts: number;
  runningAccounts: number;
  totalWatchTime: number;
  totalRewards: number;
}>();

const watchTimeFormatted = computed(() => {
  const hours = Math.floor(props.totalWatchTime / 3600);
  const minutes = Math.floor((props.totalWatchTime % 3600) / 60);
  return `${hours}h ${minutes}m`;
});
</script>

<template>
  <div class="grid grid-cols-2 gap-4 md:grid-cols-4">
    <Card>
      <CardHeader class="pb-2">
        <CardTitle class="text-xs text-muted-foreground">总账号</CardTitle>
      </CardHeader>
      <CardContent>
        <div class="text-2xl font-bold">{{ totalAccounts }}</div>
      </CardContent>
    </Card>
    
    <Card>
      <CardHeader class="pb-2">
        <CardTitle class="text-xs text-muted-foreground">运行中</CardTitle>
      </CardHeader>
      <CardContent>
        <div class="text-2xl font-bold text-green-500">{{ runningAccounts }}</div>
      </CardContent>
    </Card>
    
    <Card>
      <CardHeader class="pb-2">
        <CardTitle class="text-xs text-muted-foreground">总观看时间</CardTitle>
      </CardHeader>
      <CardContent>
        <div class="text-2xl font-bold">{{ watchTimeFormatted }}</div>
      </CardContent>
    </Card>
    
    <Card>
      <CardHeader class="pb-2">
        <CardTitle class="text-xs text-muted-foreground">总奖励</CardTitle>
      </CardHeader>
      <CardContent>
        <div class="text-2xl font-bold text-yellow-500">{{ totalRewards }}</div>
      </CardContent>
    </Card>
  </div>
</template>
