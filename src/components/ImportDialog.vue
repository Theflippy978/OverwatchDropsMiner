<script setup lang="ts">
import { ref } from "vue";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

defineProps<{
  open: boolean;
}>();

const emit = defineEmits<{
  "update:open": [value: boolean];
  import: [file: File];
}>();

const selectedFile = ref<File | null>(null);
const dragOver = ref(false);

function handleFileSelect(event: Event) {
  const target = event.target as HTMLInputElement;
  if (target.files && target.files[0]) {
    selectedFile.value = target.files[0];
  }
}

function handleDrop(event: DragEvent) {
  dragOver.value = false;
  if (event.dataTransfer?.files[0]) {
    selectedFile.value = event.dataTransfer.files[0];
  }
}

function handleImport() {
  if (selectedFile.value) {
    emit("import", selectedFile.value);
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>导入数据</DialogTitle>
        <DialogDescription>
          从文件导入账号、配置或日志数据
        </DialogDescription>
      </DialogHeader>
      
      <div class="space-y-4 py-4">
        <div
          class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-border p-8 text-center"
          :class="{ 'border-primary bg-primary/5': dragOver }"
          @dragover.prevent="dragOver = true"
          @dragleave="dragOver = false"
          @drop.prevent="handleDrop"
        >
          <svg
            class="mb-4 h-12 w-12 text-muted-foreground"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
            />
          </svg>
          <p class="mb-2 text-sm font-medium">
            拖拽文件到此处，或
          </p>
          <Label
            for="file-upload"
            class="cursor-pointer text-sm text-primary hover:underline"
          >
            点击选择文件
          </Label>
          <Input
            id="file-upload"
            type="file"
            class="hidden"
            accept=".json,.csv"
            @change="handleFileSelect"
          />
        </div>
        
        <div v-if="selectedFile" class="rounded-lg border border-border p-3">
          <p class="text-sm font-medium">{{ selectedFile.name }}</p>
          <p class="text-xs text-muted-foreground">
            {{ (selectedFile.size / 1024).toFixed(2) }} KB
          </p>
        </div>
      </div>
      
      <DialogFooter>
        <Button variant="outline" @click="emit('update:open', false)">
          取消
        </Button>
        <Button :disabled="!selectedFile" @click="handleImport">
          导入
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
