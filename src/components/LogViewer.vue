<script setup lang="ts">
import { ref, watch, nextTick, computed } from "vue";
import { useLogsStore } from "@/stores/logs";
import type { StoredLog } from "@/stores/logs";
import { useAccountsStore } from "@/stores/accounts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectItem } from "@/components/ui/select";

const logsStore = useLogsStore();
const accountsStore = useAccountsStore();
const scrollRef = ref<HTMLElement | null>(null);

/** 账号 id → 备注名。
 *
 * 日志里原本显示 id 前 6 位（如 b34547），用户无法对应到具体账号；
 * 改显示备注。回退到 id 前 8 位是因为 remark 允许为空。
 */
const remarkById = computed(() => {
  const map = new Map<string, string>();
  for (const account of accountsStore.accounts) {
    map.set(account.id, account.remark.trim() || account.id.slice(0, 8));
  }
  return map;
});

function remarkOf(accountId: string): string {
  return remarkById.value.get(accountId) ?? accountId.slice(0, 8);
}

/**
 * 结构化字段的着色规则。
 *
 * 后端把关键字段写成「中文标签：值」（见 miner.py / miner_manager.py /
 * x25kn_worker.py / client_parts/* 的各处日志），这里只按**标签**匹配，
 * 不依赖句子的词序或标点 —— 后端调整文案时着色不会错位。
 *
 * 标签必须逐个列出而不是用 `.+?：` 这类宽松匹配：Cookie、URL、base64 都含
 * 「=」，宽松匹配会把整段凭据涂成高亮色。
 *
 * 值默认在空白与**全角中文标点**处断开（见 VALUE_STOP_CHARS 的说明）：
 * 旧的 `(\S+)` 只认空白，后端一句 `直播状态：0，计时可能不会增长`
 * 会把后半句整段染蓝。半角逗号必须留在值里 —— 房间号是
 * `[23612045,21452505]` 这种紧凑形态。
 *
 * 标签表是**跨文件契约**，两侧都有门禁（2026-10-05 起，此前只有后端侧有，
 * 所以「后端加了标签、前端忘了加」会静默不着色，同一个房间号因标签不同而颜色不同）：
 * 后端要求进日志流的文案不得出现 `key=value`（Cookie、URL、base64 都含「=」），
 * 且「`标签：占位符`」里的标签必须出现在下面这张表里；
 * 前端侧要求本表不含已废弃的同义标签、且身份色只给 `账号`。
 */
const FIELD_LABELS = [
  "账号",
  "UID",
  "房间号",
  "连接",
  "线程数",
  "间隔",
  "序号",
  "ETS",
  "会话",
  "直播状态",
  "任务ID",
  "分区",
  "父分区",
  "已用时长",
  "期望间隔",
  "实际间隔",
  "错误码",
  "任务组数",
  "领奖任务数",
  "返回消息",
] as const;

/**
 * 值里可以合法出现的字符集：**排除全角中文标点**。
 *
 * 为什么不能只按空白断值：后端有一句告警是
 * `房间号：%s 当前状态非开播 直播状态：%s，计时可能不会增长`，
 * `0` 后面紧跟全角「，」而没有空格，旧的 `(\S+)` 会把后半整句
 * 当成「直播状态」的值涂成蓝色 —— 用户看到的是「，计时可能不会增长」
 * 被错误高亮。
 *
 * **半角 `,` 必须保留**：房间号是 `utils.format_room_ids` 输出的
 * `[23612045,21452505]`，紧凑形态里的分隔符就是半角逗号。
 */
const VALUE_STOP_CHARS = "，。；、！？";

/** 值本身是自由文本、允许含标点的标签。
 *  `账号` 的值是 B 站昵称（用户起的名字，可能带逗号），
 *  `返回消息` 的值是 B 站返回的整句话 —— 这两个用 `\S+` 到空白为止，
 *  其余标签一律在中文标点处断开。 */
const FREE_TEXT_LABELS = new Set(["账号", "返回消息"]);

/**
 * 逐标签生成 alternation。
 *
 * **每个分支各带一个捕获组**（值），标签本身用 `match[0]` 切出来。
 * 不能写成 `(?:标签)：(值)` 之外还指望 `match[1]`：
 * 正则的组号是按**模式里的位置**编号的，命中第 3 个分支时它的值在
 * `match[3]`，`match[1]` 是 `undefined` —— 界面上会渲染成
 * 「undefined：」+ 丢掉整个值。
 * 所以取值必须用 `match.slice(1).find(...)` 拿「实际参与了匹配的那个组」。
 */
const FIELD_RE = new RegExp(
  FIELD_LABELS.map((label) =>
    FREE_TEXT_LABELS.has(label)
      ? `${label}：(\\S+)`
      : `${label}：([^\\s${VALUE_STOP_CHARS}]+)`,
  ).join("|"),
  "g",
);

/**
 * 账号标识类标签：值用 success 绿。
 *
 * 这里**只有 `账号`**。曾经还放过 `直播间`，那是错的：
 * `直播间：` 后面跟的是房间号（miner.py / x25kn_worker.py 的旧用词，
 * 已统一改成 `房间号`），把它当身份染成绿色会让同一个房间号
 * 在两条日志里出现两种颜色。
 */
const ACCOUNT_KEYS = new Set(["账号"]);

interface LogSegment {
  text: string;
  kind: "plain" | "account" | "value";
}

function segmentMessage(message: string): LogSegment[] {
  const segments: LogSegment[] = [];
  let last = 0;
  // 正则带 g 标志，必须用 matchAll 或每次重置 lastIndex；
  // 直接 exec 循环在复用时会跳过匹配
  for (const match of message.matchAll(FIELD_RE)) {
    const start = match.index ?? 0;
    if (start > last) {
      segments.push({ text: message.slice(last, start), kind: "plain" });
    }
    // 标签从 match[0] 切出来，值取「实际参与了匹配的那个组」——
    // 见 FIELD_RE 上方的注释：组号按模式位置编号，不是按命中的分支。
    const value = match.slice(1).find((group) => group !== undefined) ?? "";
    const key = match[0].slice(0, match[0].indexOf("："));
    // 标签本身用普通色：它是结构提示不是数据，涂成高亮色会让整行都在闪。
    segments.push({ text: `${key}：`, kind: "plain" });
    segments.push({ text: value, kind: ACCOUNT_KEYS.has(key) ? "account" : "value" });
    last = start + match[0].length;
  }
  if (last < message.length) {
    segments.push({ text: message.slice(last), kind: "plain" });
  }
  return segments.length > 0 ? segments : [{ text: message, kind: "plain" }];
}

function segmentClass(kind: LogSegment["kind"]): string {
  if (kind === "account") return "text-signal-success font-medium";
  if (kind === "value") return "text-signal-info";
  return "";
}

/**
 * 新日志到达时滚到底；**切换筛选时无条件滚到底**。
 *
 * 面板常驻可滚动，所以「新日志」这一路只剩一种情况：用户手动往上翻阅
 * 历史时，不应该被新日志拽回底部 —— 靠 atBottom 判定（距底 30px 内才跟随）。
 *
 * **必须监听 lastSeq 而不是 filteredLogs.length**：到达 maxLogs(5000) 之后
 * 每批是「push N 条 + splice 掉 N 条」，length 恒为 5000，监听 length 的
 * watcher 再也不会触发 —— 表现为长时间运行后日志面板不再跟随最新日志
 * （实测：灌满 5000 条后再追加 5000 条，监听 length 触发 0 次）。
 * lastSeq 由 store 的 nextSeq++ 生成，单调递增，永不受容量裁剪影响。
 *
 * **但只监听 lastSeq 会引入一个更糟的回归（实测确证）**：切换账号筛选时
 * 结果集整体替换，浏览器把 scrollTop 钳在新内容高度以内，此时
 * atBottom 判定为 false —— 而它**不会自愈**：此后新日志到达时同样因为
 * atBottom=false 被提前 return，自动跟随**永久失效**，用户必须手动
 * 滚到底才能恢复。实测轨迹：
 *     5000 行滚到底 → 切「只看A」(120 行) → 切回「全部账号」
 *     → scrollTop 停在 2201/99801、atBottom=false，
 *       随后追加新日志触发 0 次（卡住）
 *
 * 因此把两种语义分开：
 *   * **筛选变化**（filterAccountId 变）→ 属「视图重置」，**无条件滚到底**，
 *     不看 atBottom。用户切筛选的意图就是「看这个账号的最新日志」，
 *     此时停在半空没有任何理由。
 *   * **新日志到达**（lastSeq 变）→ 仍尊重用户的上翻（atBottom 判定）。
 *
 * 用数组 watch 源让两者共用一次回调，靠比对旧值区分是哪种变化 ——
 * 若拆成两个 watch，「筛选变化」那一路的 nextTick 会与另一路竞争写
 * scrollTop，最终位置取决于回调注册顺序。
 */
watch(
  [() => logsStore.lastSeq, () => logsStore.filterAccountId],
  async (_next, prev) => {
    const el = scrollRef.value;
    if (!el) return;
    // 清空后 lastSeq 变回 -1 会触发一次：此时无需滚动
    if (logsStore.filteredLogs.length === 0) return;
    const prevFilter = prev?.[1];
    const filterChanged = prevFilter !== undefined && prevFilter !== logsStore.filterAccountId;
    // 非筛选变化（即新日志）时才尊重用户的上翻位置
    if (!filterChanged && el.scrollHeight - el.scrollTop - el.clientHeight > 30) {
      return;
    }
    await nextTick();
    el.scrollTop = el.scrollHeight;
  },
);

function getLevelColor(level: string) {
  // 用语义令牌而非 Tailwind 默认调色板：默认色在浅色主题下白底对比度
  // 只有 1.9~3.8:1，全部不达 WCAG AA（4.5:1），且不随 .dark 变化。
  //
  // 这四个 signal-* 类此前根本没生效 —— --color-signal-* 被声明在 :root 而非
  // @theme，Tailwind v4 不为 :root 里的 --color-* 生成工具类，于是全部静默
  // 退化成继承色，上面这段对比度结论在当前构建下是假的。已移入 @theme 修好。
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

/** 等级圆点：给非颜色通道一个快速定位点，长日志里扫读更快 */
function levelDotClass(level: string) {
  switch (level) {
    case "error":
      return "bg-signal-danger";
    case "warning":
      return "bg-signal-warning";
    case "debug":
      return "bg-muted-foreground/40";
    default:
      return "bg-signal-info/70";
  }
}

/**
 * 等级的文本形式，供读屏使用（视觉上 sr-only 隐藏）。
 *
 * 为什么需要：等级此前**只由颜色与圆点表达**，而圆点标了 aria-hidden，
 * 颜色对读屏完全无效 —— 读屏用户无法区分一条日志是普通信息还是错误。
 * 颜色不是唯一指示（WCAG 1.4.1）在这里必须靠这段文本补上。
 */
const LEVEL_TEXT: Record<string, string> = {
  error: "错误",
  warning: "警告",
  debug: "调试",
  info: "信息",
};

function levelText(level: string): string {
  return LEVEL_TEXT[level] ?? "信息";
}

function formatTime(timestamp: string) {
  return new Date(timestamp).toLocaleTimeString("zh-CN");
}

/**
 * 每行渲染所需的全部派生数据，**按 seq 缓存**。
 *
 * 为什么必须缓存：`segmentMessage`（20 分支 alternation 正则的 matchAll）与
 * `formatTime`（走 ICU 的 toLocaleTimeString）此前都在模板里逐行调用，
 * 而 store 每 120ms 就 flush 一批新日志 —— 每次 flush 都会让整个列表
 * 重渲染，于是 5000 行 × (一次正则 + 一次 ICU) 每 120ms 重算一遍，
 * 主线程持续被占住。写入只发生一次，渲染要发生 N 次，把计算从后者
 * 挪到前者即可去掉绝大部分开销。
 *
 * 用 Map 而不是给 StoredLog 加字段：日志的格式化规则（FIELD_LABELS /
 * ACCOUNT_KEYS / VALUE_STOP_CHARS）定义在本文件，而 StoredLog 在 store 层。
 * 这几个常量的**定义位置本身是被外部校验的**（脚本按文件名读本文件的源码），
 * 搬去 store 会让那层校验静默失效 —— 不报错，只是不再检查。
 *
 * 缓存必须随列表裁剪而修剪，否则 seq 单调递增会让 Map 无限增长（内存泄漏）。
 * 修剪在下面 `logRows` 的尾部完成，不需要额外定时器。
 *
 * **修剪是「条件式」的，注释要按实现写（不要照愿望写）**：它被
 * `if (rowCache.size > alive.size)` 门控，即**只在 size 超了才遍历清理**，
 * 而不是「每次都精确清理」。这在当前实现下是正确且高效的，依据是一条
 * 不变式：**rowCache ⊇ alive** —— 每个 alive 里的 seq 要么命中缓存、
 * 要么在本轮被 set 进去，所以 size 恒 ≥ alive.size；门控成立时恰好
 * 等价于「存在 stale 项」，此时遍历能精确清掉它们。
 *
 * 为什么不去掉门控、改成无条件清理：那会让**每次 logRows 重算都全遍历
 * rowCache**（5000 项），而 logRows 每 120ms 就重算一次 —— 为了注释好读
 * 而引入每 120ms 的 5000 次 Map 遍历，不划算。代价是这条不变式成为
 * 前提：**将来若有人改动 set 时机（例如允许同一 seq 重复入 Map 导致
 * alive 去重后更小），门控会静默跳过清理、stale 项开始累积**。
 * 改那处时请一并把这里改成无条件清理。
 */
interface LogRow {
  log: StoredLog;
  time: string;
  segments: LogSegment[];
}

const rowCache = new Map<number, { time: string; segments: LogSegment[] }>();

const logRows = computed<LogRow[]>(() => {
  const source = logsStore.filteredLogs;
  const alive = new Set<number>();
  const rows: LogRow[] = [];
  for (const log of source) {
    alive.add(log.seq);
    let cached = rowCache.get(log.seq);
    if (!cached) {
      cached = {
        time: formatTime(log.timestamp),
        segments: segmentMessage(log.message),
      };
      rowCache.set(log.seq, cached);
    }
    rows.push({ log, time: cached.time, segments: cached.segments });
  }
  // 条件式修剪：门控依据是 rowCache ⊇ alive 这条不变式（见上方 rowCache
  // 的注释）。成立时它等价于「存在 stale 项」，此时遍历能精确清掉
  // 被 maxLogs 裁掉的旧 seq 与切筛选后不在结果集里的 seq。
  if (rowCache.size > alive.size) {
    for (const seq of rowCache.keys()) {
      if (!alive.has(seq)) rowCache.delete(seq);
    }
  }
  return rows;
});

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
  <!-- 卡片内边距 18/8/18/14，对齐 Qt 时代的日志面板。
       Card 是 `flex flex-col`、CardContent 是 `flex-1` 的列容器 ——
       右列网格第 3 行是 `1fr`，日志卡必须自己把高度撑满，
       日志面板才能吃到窗口的全部剩余高度（否则空白留在卡外）。
       这与「不要加 h-full」不矛盾：h-full 是相对 main 全文高度（会冲出
       main），这里要的是「占满本卡被分配到的高度」，由 flex 链给出。 -->
  <Card class="card-hover flex min-h-0 flex-col">
    <!-- 卡头是 shrink-0：高度固定，日志面板的伸缩全部由下方内容区承担。
         面板此前的 translateY(-8px) 已删，那个 transform 会与卡头下内边距
         抵消成「零间距」，让「全部账号」的下边框与面板上边框叠在一起。 -->
    <CardHeader class="shrink-0 px-4 pb-2 pt-2">
      <div class="flex items-center justify-between gap-2">
        <!-- 与另两张卡统一为 15px + font-semibold（原为 11pt + font-bold，
             既与正文几乎同大、字重又与 AccountList 不一致）。 -->
        <CardTitle class="text-[15px] font-semibold">运行日志</CardTitle>
        <div class="flex items-center gap-2">
          <!-- 换成自绘 Select 是为了与「添加账号」菜单共用同一套进出场动画：
               原生 select 的展开列表由系统绘制，CSS 管不到它，风格会割裂。
               换来的代价有两条，都不要忘记：
               * 焦点样式与键盘行为原先由系统提供，现在由 Select.vue 自己补；
               * 多了一层浮层动画。若它显得迟钝，该调的是 Select.vue 里的
                 duration token，而不是换回原生控件。 -->
          <Select
            id="log-account-filter"
            aria-label="按账号过滤日志"
            :model-value="logsStore.filterAccountId ?? ''"
            class="max-w-[168px]"
            @update:model-value="logsStore.setFilter(($event as string) || null)"
          >
            <!-- 空串 = 「全部账号」（store 侧是 null）。哨兵串的归一化与
                 出口反归一都在 ui/select 封装层里成对做完，调用方只见空串，
                 这里的 `|| null` 才成立。原理见 ui/select/constants.ts。 -->
            <SelectItem value="">全部账号</SelectItem>
            <SelectItem
              v-for="acc in accountsStore.accounts"
              :key="acc.id"
              :value="acc.id"
            >
              {{ acc.remark }}
            </SelectItem>
          </Select>
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
    <!-- min-h-0：flex 项目的 `min-height: auto` 会解析成内容高度，
         不写它日志面板就拿不到 flex 高度，超长时不内部滚动而是把卡片顶高
         （与 TaskProgress 的 CardContent 同一个道理）。 -->
    <!-- px-4 / pb-4（均 16px）：统一到 4px 网格，与另两张卡四边一致
         （原为 18px 横向 + 14px 纵向的任意值）。
         纵向 +2px 已计入最小窗口高度从 860 抬到 868（见 App.vue）。
         注释刻意不复写旧类名 —— Tailwind v4 会扫源码原文并生成，
         注释里的类名同样会污染产物。 -->
    <CardContent class="flex min-h-0 flex-1 flex-col px-4 pb-4 pt-0">
      <!-- 日志面板吃掉卡内全部剩余高度（`.log-panel` 的 flex: 1），
           始终可滚动。折叠态已在 2026-10-05 取消：右列把剩余高度给了日志，
           「只有两行高」的折叠语义会让空白重新出现在卡外，
           而满高可滚动的日志区在任何窗口高度下都没有空白。

           不要加 h-full：那是相对 main 全文高度、会向下冲出 main。
           高度来源唯一是 `.log-panel` 的 flex 链，Tailwind 不再参与。 -->
      <!-- role="log" + aria-label：读屏用户此前完全感知不到这是一个日志区，
            而日志等级（info/warning/error/debug）的唯一非颜色通道是那个
            6px 圆点，它标了 aria-hidden —— 于是等级信息对读屏彻底不可见。

            **刻意不加显式 aria-live**：verbose 模式下每 120ms 就有一批日志
            涌入，aria-live 会让读屏不停播报、把用户彻底淹没。role="log"
            本身已带隐式的 polite 语义，交给读屏按自身策略处理更稳妥。
            若后续实测确认需要显式声明，再按 V9 的结论调整。 -->
      <div
        id="log-panel"
        ref="scrollRef"
        role="log"
        aria-label="运行日志"
        class="log-panel min-h-0 flex-1 overflow-y-auto rounded-md border border-input bg-input/40"
      >
        <!-- 空态用 absolute inset-0 撑满面板再 flex 居中。
             面板的高度来自 flex 链（Card flex-col → CardContent flex-1 →
             .log-panel 的 flex-1 + min-h-0），没有 min-height 兜底，
             所以这里也不需要任何 py-* 去撑高度。
             .log-panel 的 position: relative 是这段 absolute 的定位祖先。 -->
        <div
          v-if="logsStore.filteredLogs.length === 0"
          class="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground"
        >
          暂无日志
        </div>
        <div v-else class="space-y-0.5 p-1.5 font-mono text-xs">
          <!-- 遍历 logRows（已缓存的派生数据）而不是 filteredLogs：
               时间格式化与结构化分段都在 computed 里按 seq 缓存，
               模板只负责渲染，不再逐行重跑正则与 ICU。 -->
          <!-- transition-colors：日志行 hover 变底色此前是瞬变，
               与账号行/菜单项那些有过渡的可点元素不一致（一行行扫过去时
               瞬变更像闪烁）。 -->
          <div
            v-for="row in logRows"
            :key="row.log.seq"
            class="flex min-h-[var(--log-row-h)] items-center gap-2 rounded px-1
                   leading-[var(--log-row-h)] transition-colors hover:bg-accent/40"
          >
            <span class="shrink-0 tabular-nums text-muted-foreground/80">
              {{ row.time }}
            </span>
            <span
              v-if="row.log.account_id"
              class="shrink-0 font-medium text-signal-success"
            >
              {{ remarkOf(row.log.account_id) }}
            </span>
            <!-- 等级用色块而不是纯文字色：等级信息不该只靠颜色传达，
                 但色块本身也提供了非颜色的视觉锚点 -->
            <span
              class="h-1.5 w-1.5 shrink-0 rounded-full"
              :class="levelDotClass(row.log.level)"
              aria-hidden="true"
            />
            <!-- 等级的文本通道：圆点与颜色对读屏都无效，这里补一个
                 视觉隐藏的等级词，让「错误/警告」能被念出来。 -->
            <span class="sr-only">{{ levelText(row.log.level) }}</span>
            <span :class="getLevelColor(row.log.level)" class="min-w-0 break-all">
              <template v-for="(seg, i) in row.segments" :key="i">
                <span :class="segmentClass(seg.kind)">{{ seg.text }}</span>
              </template>
            </span>
          </div>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
