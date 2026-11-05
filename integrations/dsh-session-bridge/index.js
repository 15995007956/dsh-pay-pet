// dsh-session-bridge（host 半）：无逻辑。
// 真正的工作在 client 半（client.js）：它运行在 DSH 页面里，能读到 uiSession 的
// sessionStatus 与 sessions.list，把会话状态 POST 到桌宠的本地回环端口。
export function apply() {
  // no-op：本插件不使用宿主侧服务，也不写任何文件。
}

// cordis 同时接受「函数」与「带 apply 的对象」；默认导出兜底，避免加载器
// 只取 default 时拿到没有 apply 的命名空间对象。
export default { name: "dsh-session-bridge-pet", apply };
