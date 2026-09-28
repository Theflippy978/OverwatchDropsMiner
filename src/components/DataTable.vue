<script setup lang="ts">
import { computed } from "vue";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const props = defineProps<{
  title: string;
  columns: Array<{ key: string; label: string; width?: string }>;
  data: Array<Record<string, any>>;
  loading?: boolean;
}>();

const emit = defineEmits<{
  rowClick: [row: Record<string, any>];
}>();
</script>

<template>
  <Card>
    <CardHeader>
      <CardTitle class="text-sm">{{ title }}</CardTitle>
    </CardHeader>
    <CardContent>
      <div v-if="loading" class="py-8 text-center text-sm text-muted-foreground">
        加载中...
      </div>
      <div v-else-if="data.length === 0" class="py-8 text-center text-sm text-muted-foreground">
        暂无数据
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-border">
              <th
                v-for="col in columns"
                :key="col.key"
                class="pb-2 text-left font-medium text-muted-foreground"
                :style="{ width: col.width }"
              >
                {{ col.label }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, index) in data"
              :key="index"
              class="border-b border-border/50 hover:bg-accent/50 cursor-pointer"
              @click="emit('rowClick', row)"
            >
              <td
                v-for="col in columns"
                :key="col.key"
                class="py-2"
              >
                {{ row[col.key] }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </CardContent>
  </Card>
</template>
