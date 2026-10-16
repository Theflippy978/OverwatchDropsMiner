"""跨模块共享的常量与状态语义。

B站任务接口用同一个 ``status`` 整数表达多种含义，此前 3 与 6 这两个
取值以字面量散落在七个模块（client_parts 下的 models / rewards / tasks /
task_parsing、browser 下的 task_presenter、main.py，以及前端 types.ts 与
TaskProgress.vue）。任何一处漏改都会让「已完成」与「已领取」的判定漂移，
且漂移后没有任何报错——只表现为界面把已领取的任务显示成已完成。

新增语义时只改这里，并同步 ``src/lib/types.ts`` 里的镜像常量。
"""

# 检查点（单个奖励任务）的状态
TASK_STATUS_COMPLETED = 3
TASK_STATUS_CLAIMED = 6

#: 已完成或已领取。``is_completed`` 必须包含 6：已领取的检查点同样已达成
#: 目标时长，若这里排除它，界面会把已领取显示成「进行中」。
TASK_STATUS_DONE = frozenset({TASK_STATUS_COMPLETED, TASK_STATUS_CLAIMED})

#: 奖励任务刚下发、未开始
TASK_STATUS_PENDING = 0


# ---------------------------------------------------------------------------
# 「线程数」的**默认值** —— 只有这一处该写字面量
# ---------------------------------------------------------------------------
# 边界不在这：下限 1、上限 256 的**唯一入口**是 backend/config.py 的
# MAX_TOTAL_CONNECTIONS（它同时是「总连接数」与「线程数上限」两个概念，
# 本项目里两者是同一个数），main.py 与前端 config-limits.ts 都从那里取。
#
# 为什么单独抽这个 60：它此前散落在 main.py 的 12 处 `data.get(..., 60)` /
# `_clamp_int(..., 60, ...)` 里，与前端 stores/config.ts 初始值的 "60" 各写一份。
# 改默认值要动 12 个地方，漏掉任何一处的后果不是报错而是**行为分裂** ——
# 有的路径按新默认、有的按旧默认，用户看到「同一个数字有时生效有时不生效」。
# 历史教训：同源的 128/256 漂移导致「前端允许填 256、保存也成功，启动时才被
# validate() 拒」。
THREAD_COUNT_DEFAULT = 60

# 线程数下限。config.py 的 validate() 只判「>0」这个硬边界，合法工作区间的下界
# 由钳制点负责，所以这个 1 会同时出现在 main.py 的三处 _clamp_int 与前端
# config-limits.ts —— 写三遍就会漂移，故在此收拢。
THREAD_COUNT_MIN = 1


# ---------------------------------------------------------------------------
# 「任务查询间隔」（秒）的取值范围 —— 多处同源，改一处必须同步其余
# ---------------------------------------------------------------------------
# 其余落点：backend/config.py 的 validate()、main.py 各 _clamp_int 调用点、
# 前端 src/lib/config-limits.ts（stores/config.ts 的 save() 与 App.vue 的
# 定时器都从它取，前端不再各写各的字面量）。
# 历史上前后端各写各的，后果是「前端能填进去、保存也成功，启动时才被
# validate() 拒」，错误文案来自深层调用，用户无法把报错与刚才那个输入框关联。
TASK_QUERY_INTERVAL_DEFAULT_SECONDS = 30
TASK_QUERY_INTERVAL_MIN_SECONDS = 10
TASK_QUERY_INTERVAL_MAX_SECONDS = 3600


# ---------------------------------------------------------------------------
# 「重连延迟」（秒）的取值范围 —— 与任务查询间隔同理，多处同源
# ---------------------------------------------------------------------------
# 其余落点：backend/config.py 的 validate()、main.py 的 _clamp_int 调用点、
# 前端 src/lib/config-limits.ts。
RECONNECT_DELAY_DEFAULT_SECONDS = 8
RECONNECT_DELAY_MIN_SECONDS = 1
RECONNECT_DELAY_MAX_SECONDS = 3600


# ---------------------------------------------------------------------------
# 标题栏状态胶囊的 message 字数上限 —— 跨进程契约
# ---------------------------------------------------------------------------
# 更新检查的 message 经 sidecar → Rust → 前端，最终显示在标题栏那个**定宽**
# 胶囊里。像素真相在 src/components/TitleBar.vue（定宽 132px、文字上限 110px、
# 11px 字号）；汉字是方块字，一个字约等于字号宽，故 110 ÷ 11 = 10 个字。
#
# 为什么写成常量：这条预算的像素数字此前散在多个文件的注释里各写一遍，
# 同一事实散落多处就会互相漂移 —— 改窄胶囊时没人记得回去改后端文案的说明。
# 后端写文案只需要「能写几个字」，像素怎么来的归前端那份注释说。
#
# 写超了会怎样：message 超过这个字数时，超出部分被 CSS 从中间省略号切掉，
# 用户只看到半句话 —— 2026-10-13 用户报告「检查更新失败还是显示超过 6 个字」，
# 根因就是这条预算当时没有可机器判的入口，改文案的人不知道有上限。
# 现在判据是机器判的：遍历 FAILURE_MESSAGES 这张表逐条量字数，超出即红，
# 新增文案必须先加进 FAILURE_MESSAGES（不加进表 = 不被量，review 时看得见）。
# 完整原因一律放 detail，前端把它接进胶囊的 title。
CAPSULE_MESSAGE_MAX_CHARS = 10
