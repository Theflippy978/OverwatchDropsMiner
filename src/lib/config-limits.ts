/** 配置项的取值边界 —— **前端的唯一入口**。
 *
 *  为什么单独一个文件（而不是留在 stores/config.ts 里）：这些数字此前以
 *  字面量散落在多处（config.ts 的钳制、App.vue 的定时器、ConfigForm.vue
 *  输入框的 `min`/`max` 属性），改一处忘另一处的后果不是报错而是行为分裂 ——
 *  输入框允许填的值与保存时校验的值不一致。
 *  现在这些地方都从这里 import，改一次全生效。
 *
 *  ⚠ 与后端同源：本文件每一项都对应 `python_sidecar/backend/constants.py`
 *  里的同名常量（线程上限对应 config.py 的 MAX_TOTAL_CONNECTIONS）。
 *  跨语言无法共用一个文件，所以各留一份 —— 改这里的任何一个，必须同步后端那份。
 */

/** 线程数 / 总连接数上限（用户决策值 256）。
 *  历史上出现过 128/256 不一致，后果是「前端允许填 256、保存也成功，
 *  启动时才被后端 validate() 拒」，而错误文案来自深层调用，用户无法关联因果
 *  （默认 60 线程 × 3 房间 = 180，正好落在 128 与 256 之间，最易触发）。 */
export const MAX_THREAD_COUNT = 256;

/** 线程数的默认值与下限。后端同源：constants.py 的 THREAD_COUNT_DEFAULT / _MIN。 */
export const THREAD_COUNT_DEFAULT = 60;
export const THREAD_COUNT_MIN = 1;

/** 「任务查询间隔」的取值范围（秒）。
 *  后端同源：constants.py 的 TASK_QUERY_INTERVAL_*。 */
export const TASK_QUERY_INTERVAL_DEFAULT_SECONDS = 30;
export const TASK_QUERY_INTERVAL_MIN_SECONDS = 10;
export const TASK_QUERY_INTERVAL_MAX_SECONDS = 3600;

/** 「重连延迟」的取值范围（秒）。后端同源：constants.py 的 RECONNECT_DELAY_*。 */
export const RECONNECT_DELAY_DEFAULT_SECONDS = 8;
export const RECONNECT_DELAY_MIN_SECONDS = 1;
export const RECONNECT_DELAY_MAX_SECONDS = 3600;
