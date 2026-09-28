<script setup lang="ts">
import { computed } from "vue";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

const props = defineProps<{
  title: string;
  description?: string;
}>();

const emit = defineEmits<{
  action: [];
}>();
</script>

<template>
  <Card>
    <CardHeader>
      <div class="flex items-center justify-between">
        <div>
          <CardTitle class="text-sm">{{ title }}</CardTitle>
          <p v-if="description" class="text-xs text-muted-foreground">
            {{ description }}
          </p>
        </div>
        <slot name="action" />
      </div>
    </CardHeader>
    <CardContent>
      <slot />
    </CardContent>
  </Card>
</template>
