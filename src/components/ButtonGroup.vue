<script setup lang="ts">
import { computed } from "vue";
import { Button } from "@/components/ui/button";

const props = defineProps<{
  loading?: boolean;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  submit: [];
  cancel: [];
}>();
</script>

<template>
  <div class="flex items-center justify-end gap-2">
    <Button
      type="button"
      variant="outline"
      :disabled="loading || disabled"
      @click="emit('cancel')"
    >
      取消
    </Button>
    <Button
      type="submit"
      :disabled="loading || disabled"
      @click="emit('submit')"
    >
      <span v-if="loading" class="mr-2 h-4 w-4 animate-spin">⟳</span>
      <slot>确定</slot>
    </Button>
  </div>
</template>
