<script setup lang="ts">
import { ref, watch, nextTick } from "vue";
import { useLogsStore } from "@/stores/logs";
import { useAccountsStore } from "@/stores/accounts";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const logsStore = useLogsStore();
const accountsStore = useAccountsStore();
const scrollRef = ref<HTMLElement | null>(null);
const collapsed = ref(true);

watch(
  () => logsStore.filteredLogs.length,
  async () => {
    const el = scrollRef.value;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= 30;
    if (!atBottom) return;
    await nextTick();
    el.scrollTop = el.scrollHeight;
  }
);

function getLevelColor(level: string) {
  // 用语义令牌而非 Tailwind 默认调色板：默认色在浅色主题下白底对比度
  // 只有 1.9~3.8:1，全部不达 WCAG AA（4.5:1），且不随 .dark 变化。
  switch (level) {
    case "error":
      return "text-signal-danger";
    case "warning":
      return "text-signal-warning";
    case "debug":
      return "text-muted-foreground";
    default:
      return "text-foreground";
  }
}

function formatTime(timestamp: string) {
  return new Date(timestamp).toLocaleTimeString("zh-CN");
}

function handleClear() {
  const filterId = logsStore.filterAccountId;
  if (filterId) {
    logsStore.clearByAccount(filterId);
  } else {
    logsStore.clear();
  }
}
</script>

<template>
  <!-- 卡片内边距对齐旧版 main_layout.py:268 的 setContentsMargins(18, 8, 18, 14)；
       不要加 h-full：本卡在右列滚动容器内，height:100% 会向下冲出 main 造成底部空白 -->
  <Card class="card-hover">
    <CardHeader class="px-[18px] pb-2 pt-2">
      <div class="flex items-center justify-between gap-2">
        <!-- 标题即折叠开关（对齐旧版左上角折叠按钮） -->
        <button
          :aria-expanded="!collapsed"
          aria-controls="log-panel"
          class="text-left text-[11pt] font-bold text-foreground transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          @click="collapsed = !collapsed"
        >
          {{ collapsed ? "展开运行日志" : "收起运行日志" }}
        </button>
        <div class="flex items-center gap-2">
          <select
            id="log-account-filter"
            aria-label="按账号过滤日志"
            class="h-7 rounded-md border border-input bg-background px-2 text-xs"
            :value="logsStore.filterAccountId ?? ''"
            @change="logsStore.setFilter(($event.target as HTMLSelectElement).value || null)"
          >
            <option value="">全部账号</option>
            <option
              v-for="acc in accountsStore.accounts"
              :key="acc.id"
              :value="acc.id"
            >
              {{ acc.remark }}
            </option>
          </select>
          <Button
            size="sm"
            variant="ghost"
            class="h-7 rounded-md px-3 text-xs text-muted-foreground"
            @click="handleClear"
          >
            清空
          </Button>
        </div>
      </div>
    </CardHeader>
    <CardContent class="px-[18px] pb-3.5 pt-0">
      <!-- 展开高度对齐旧版 log_text（main_layout.py:286-287）：min-height 140 + 固定可视高度。
           边框/底色/内边距只放在展开态：border-box 下 height:0 仍会被 padding 撑到
           padding 之和（实测 12px），折叠时必须连 padding 一起清零。
           折叠用 hidden（display:none）而非 opacity-0：后者只影响视觉，DOM 里
           最多 5000 条日志仍在无障碍树中，折叠后读屏会继续逐条朗读。

           高度用 min(220px, 30vh) 而非固定 220px：日志卡在右列 flex 流里与
           TaskProgress 争抢空间，固定高度在小窗口下会把挂宝进度压到 min-h 之下，
           连带把「自动领取 / 领取奖励 / 手动刷新」那一行挤出去。vh 下限保证
           窗口再小也留得住上方卡片。 -->
      <div
        v-show="!collapsed"
        id="log-panel"
        ref="scrollRef"
        class="log-panel overflow-y-auto rounded-md border border-input bg-input/40 p-1.5"
        :class="collapsed ? 'h-0 min-h-0' : 'h-[min(220px,30vh)] min-h-[120px]'"
      >
        <div v-if="logsStore.filteredLogs.length === 0" class="py-8 text-center text-sm text-muted-foreground">
          暂无日志
        </div>
        <div v-else class="space-y-1 font-mono text-xs">
          <div
            v-for="log in logsStore.filteredLogs"
            :key="log.seq"
            class="flex gap-2"
          >
            <span class="shrink-0 text-muted-foreground">{{ formatTime(log.timestamp) }}</span>
            <span
              v-if="log.account_id"
              class="shrink-0 text-signal-info"
            >
              [{{ log.account_id.slice(0, 6) }}]
            </span>
            <span :class="getLevelColor(log.level)">
              {{ log.message }}
            </span>
          </div>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
