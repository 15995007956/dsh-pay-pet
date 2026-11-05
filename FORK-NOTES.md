# 本 Fork 的改动说明

上游仓库：[Merzlin/dsh-pet-indesktop](https://github.com/Merzlin/dsh-pet-indesktop)（MIT）

本 fork 在上游基础上做了「**DSH 联动**」与「**工资播报**」两块改造，其余保持上游行为。

---

## 一、改动清单

### 新增文件

| 路径 | 作用 |
|---|---|
| `pet/agent_link/session_api.py` | 本地回环 HTTP 接收器（`127.0.0.1:8765`），收 DSH client 插件推来的会话快照与工资播报；另提供 `GET /salary-config` |
| `pet/salary_widget.py` | 工资计算（21.75 月计薪天数 / 上班窗口内累计 / 净时薪口径）+ 独立参数文件读写 |
| `integrations/dsh-session-bridge/` | **DSH client 插件**（`dsh-session-bridge-pet`）：读 `sessions.list` 与 `uiSession.sessionStatus`，推会话状态并按时播出工资气泡文案 |

### 修改文件

| 路径 | 改动 |
|---|---|
| `pet/agent_link/__init__.py` | 会话快照处理（完成 / 审批 / 计划 / 提问 → 桌宠气泡）、工资事件处理、提示文案随机化接入 |
| `pet/config.py` | 新增 `salary_widget` 默认段；`agent_link` 新增 `session_api` / `session_api_port` |
| `pet/multi_window_shared.py` | `show_bubble` 透传 kwargs（overlay 拓扑下气泡转发所需） |
| `pet/persona_phrases.py` | 文案由「按顺序轮流」改为「随机抽取，且不与上一条相同」 |
| `pet/persona_presets/{legacy,whale_maid}.json` | 完成/等待类文案去掉 `DSH` 字样与 `{name}` 占位，改为中性的「任务完成」 |

---

## 二、能力说明

### 1. DSH 联动（替代上游的文件桥接）

上游通过 `integrations/dsh-pet-bridge`（host 插件写 JSONL、桌宠 tail）拿事件。本 fork 改为：

```
DSH 页面（client 插件）
  ├─ sessions.list / uiSession.sessionStatus
  │     → POST http://127.0.0.1:8765/event  {rows:[{id,running,unread,pending,main}]}
  └─ 到期时 GET /salary-config → 计算 → POST {source:"salary", text}
                ↓
桌宠  AgentLinkManager 收到后：完成 → 15 秒气泡；审批/计划/提问 → 常驻气泡
```

好处：能原生识别 `plan-review`（上游只能靠 `exit_plan_mode` 猜测）、不依赖文件轮询、DSH 页面后台也能收到。

**注意**：此方案要求 DSH 处于运行状态；DSH 关闭时不会推送任何提示（包括工资播报）。

### 2. 工资播报

每 20–45 分钟随机一次，在桌宠头顶冒 6 秒气泡：

```
今日已赚 ¥242.86 · 净赚 ¥121.43      （上班中）
今日收工：已赚 ¥459.77 · 净赚 ¥229.89 （下班后）
还没开工～今天预计 ¥459.77 · 净 ¥229.89 （上班前）
```

参数文件：`%APPDATA%\dsh-pet-standalone\salary-widget.json`

```json
{
  "enabled": true,
  "monthlySalary": 10000.0,
  "monthlyConsumption": 5000.0,
  "workStart": "08:00",
  "workEnd": "18:00",
  "min_interval_minutes": 20,
  "max_interval_minutes": 45
}
```

口径：`mwh = 每日工时 × 21.75`；毛时薪 `月薪 / mwh`；净时薪 `max(0, 毛 − 月耗 / mwh)`；
只在上班窗口内累计，下班后冻结。

---

## 三、安装

```powershell
# 1) 桌宠
git clone <本 fork>
cd dsh-pet-indesktop
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pythonw.exe -m pet

# 2) DSH client 插件（装进 desktop profile）
dsh plugin --profile desktop add <本 fork 目录>\integrations\dsh-session-bridge
```

装完**重启一次 DSH**（client 插件随页面加载）。

---

## 四、许可与素材

- **代码**：继承上游 [MIT](LICENSE)，可自由修改与分发，请保留 `LICENSE` 与版权声明。
- **角色素材**：`assets/characters/**` 为社区同人素材（角色 OC「溟月」，画师上善无形），
  按 **CC BY-NC-SA 类条款**发布，**仅限个人非商业使用**，须保留署名与来源。
  如需商业分发，请自行替换为有授权的素材。
- 其它第三方组件见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)，分发时请一并保留。

本 fork 与上游作者无隶属关系，不代表上游立场。

---

## 五、同步上游

```powershell
git remote add upstream https://github.com/Merzlin/dsh-pet-indesktop.git
git fetch upstream
git rebase upstream/main     # 冲突点通常集中在 agent_link 与 persona_presets
```

已知脆弱点：本 fork 修改了 `persona_presets` 与 `persona_phrases.py`，上游若调整文案结构，rebase 时需人工确认。
