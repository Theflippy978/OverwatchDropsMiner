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