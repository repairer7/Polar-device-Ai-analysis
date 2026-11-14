# Polar Device AI Analysis (Polar Loop 深度版)

基于 Polar AccessLink API v3 和 OpenAI 兼容大模型接口的 Polar Loop 全维度健康数据分析工具。

项目从 Polar Loop 同步睡眠分期、连续心率、活动与久坐、Nightly Recharge、夜间皮肤温度（Elixir™）、SleepWise™ 清醒度与生物钟节律、心肺负荷（Cardio Load）、运动记录以及个人生理基准，结合跨模态规则引擎对**心率变化曲线与异常时段**进行精准定位，最终生成适合手机 Bark 阅读的紧凑中文健康报告。

## 功能特性

- **Polar Loop 全维度数据同步**：
  - 睡眠结构分析（深睡/浅睡/REM 时长与占比、夜醒中断、睡眠周期、连续性及三大子评分）
  - 连续心率深度分析（睡前/睡眠/上午/下午/傍晚 5 段对比、24 小时逐时曲线、夜间最低心率恢复动力学、静息/睡眠/突变异常阶段自动筛查）
  - 活动与久坐监测（步数、活动强度区间分布、久坐提醒时间戳、活跃时长、消耗千卡与目标完成率）
  - Nightly Recharge 夜间恢复（ANS Charge、HRV 整夜波动趋势、呼吸率稳定性）
  - Elixir™ 生物传感（夜间睡眠皮肤温度及 28 天个人基线偏离值、体温周期与佩戴接触状态）
  - SleepWise™ 生物钟预测（今日清醒度评分、精力峰值/犯困低谷时段、今晚最佳入睡时间窗）
  - 训练与心肺负荷（Cardio Load、Strain 近期疲劳度、Tolerance 长期耐受度及运动记录自动对齐）
  - 个人生理基准（自动读取 `physical-info` 静息心率与最大心率，动态设定异常阈值）
- **跨模态心率异常检测**：自动对齐睡眠区间、步数采样和运动记录，区分“静息非活动期心率偏高 / 睡眠心率偏高 / 非活动骤升骤降”与“正常步行或运动引起的生理性升高”。
- **严格北京时间（UTC+8）**：显式锁定东八区时间，避免 GitHub Actions（UTC 环境）出现跨日与 `21:00` 边界偏移。
- **Bark POST 推送**：优先采用 `POST /push` JSON 协议发送报告（避免长文本 URL 截断或 414 错误），并在需要时自动回退兼容 `GET` 模式。
- **高可用重试与降级**：OpenAI 与 Bark 均支持指数退避重试；部分可选 Polar 接口无数据时安全降级，不中断整体报告。

## 数据分析范围

程序默认以**北京时间（UTC+8）**当天日期为报告日期，分析时间区间为：

```text
前一天 21:00 至当天 20:59 (Asia/Shanghai)
```

各类数据的处理方式如下：

| 数据类型 | 接口端点 | 获取与处理方式 |
| --- | --- | --- |
| 睡眠 | `/v3/users/sleep` | 提取睡眠起止、深睡/REM/浅睡时长及占比、中断时长、连续性、三大子评分及睡眠期心率 |
| 连续心率 | `/v3/users/continuous-heart-rate/{date}` | 合并前一天 21:00 后与当天 21:00 前样本，结合个人静息基准、睡眠窗、步数与运动记录，检测异常高心率/低心率/突变阶段与夜间最低点恢复位置 |
| 活动与久坐 | `/v3/users/activities/samples` & `/v3/users/activities` | 统计区间步数、活跃时段、活动强度区间(`SEDENTARY`/`LIGHT`/`MODERATE`/`VIGOROUS`)、久坐提醒时刻及日卡路里/距离/达成率 |
| Nightly Recharge | `/v3/users/nightly-recharge/{date}` | 获取 HRV、呼吸率、ANS Charge 及状态，提炼前后半夜 HRV 与呼吸率波动趋势 |
| 生物传感 (Elixir™) | `/v3/users/biosensing/skintemperature` 等 | 获取夜间睡眠皮肤温度及相对 28 天基线偏离℃、体温汇总与腕部贴合状态 |
| SleepWise™ | `/v3/users/sleepwise/alertness` & `circadian-bedtime` | 预测今日精力高精力时段与困倦低谷时段、今晚最佳入睡时间窗 |
| 心肺负荷与运动 | `/v3/users/cardio-load` & `/v3/exercises` | 获取 Cardio Load / Strain / Tolerance 状态及当日训练记录（并用于排除运动心率误报） |
| 生理基准 | `/v3/users/physical-info` | 读取个人静息心率、最大心率、VO2max 等用于动态计算心率异常阈值 |

## 项目结构

```text
.
├── .github/
│   └── workflows/
│       └── main.yml              # GitHub Actions 工作流
├── main.py                       # 主程序，负责北京时间调度、数据聚合、AI 分析与 Bark 推送
├── sleep_sync.py                 # Polar 睡眠数据及分期结构同步
├── hr_sync.py                    # Polar 连续心率同步与跨模态心率异常阶段检测引擎
├── activity_sync.py              # Polar 活动样本、强度区间与每日活动汇总同步
├── nightly_recharge.py           # Polar Nightly Recharge 与夜间 HRV/呼吸趋势提炼
├── loop_extras_sync.py           # Polar Loop 扩展接口（皮肤温度、SleepWise、心肺负荷、运动与生理基准）
├── bark_push.py                  # Bark 推送封装（POST JSON 优先 + GET 兼容回退）
├── requirements.txt              # Python 依赖
└── README.md                     # 项目说明
```

## 工作原理

程序运行时按以下流程执行：

1. 按北京时间（`UTC+8`）确定当天与前一天日期（统计区间 `前一天 21:00 - 当天 20:59`）
2. 并行/依次拉取睡眠、Nightly Recharge、活动样本与汇总、个人生理基准、Elixir 皮肤温度、SleepWise 清醒度/生物钟、心肺负荷和运动记录
3. 由 `hr_sync.py` 将连续心率序列与睡眠窗、同时段步数、运动记录进行跨模态对齐，识别静息异常高心率段、睡眠高心率段、非活动心率突变及夜间最低心率恢复特征
4. 组装高密度 JSON 载荷并发送给 OpenAI 兼容模型生成 **450～650 字**的纯文本紧凑报告
5. 通过 Bark `POST /push` 推送至手机端

报告固定包含以下 4 个紧凑板块：

- **睡眠与夜间恢复分析**（含睡眠分期、HRV/呼吸率、夜间皮肤温度偏离）
- **心率动态与异常阶段深度分析**（含 5 阶段心率对比、夜间最低点恢复评价、精确到 `HH:MM-HH:MM` 的异常时段与原因判定）
- **日常活动与心肺负荷分析**（含步数、消耗、久坐提醒及 Cardio Load）
- **生物钟清醒度与今日综合建议**（含今日精力峰值/低谷、今晚最佳入睡窗与健康预警）

## 使用 GitHub Actions

### 1. Fork 仓库

点击 GitHub 仓库右上角的 **Fork**，将项目复制到自己的 GitHub 账号下。

### 2. 配置 GitHub Secrets

进入仓库：

```text
Settings → Secrets and variables → Actions → New repository secret
```

添加以下 Secrets：

| 名称 | 说明 | 示例 |
| --- | --- | --- |
| `POLAR_TOKEN` | Polar AccessLink API 访问令牌（需 `accesslink.read_all` 权限） | `your-polar-token` |
| `OPENAI_API_KEY` | OpenAI / 中转站 API Key | `your-openai-api-key` |
| `OPENAI_BASE_URL` | (可选) 自建中转站等自定义 API 地址 | `https://api.your-proxy.com/v1` |
| `BARK_HOST` | Bark 服务地址或域名 | `https://api.day.app` |
| `BARK_KEY` | Bark 设备 Key | `your-bark-key` |

### 3. 手动执行工作流

进入仓库的 **Actions** 页面，选择 `Polar Health Sync & OpenAI Analysis`，点击 `Run workflow`。

## 本地运行

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Windows PowerShell 配置环境变量并运行：

```powershell
$env:POLAR_TOKEN="your-polar-token"
$env:OPENAI_API_KEY="your-openai-api-key"
$env:OPENAI_BASE_URL="https://api.your-proxy.com/v1"
$env:BARK_HOST="https://api.day.app"
$env:BARK_KEY="your-bark-key"
python main.py
```

## 注意事项

- 本分析报告由大模型结合传感器统计特征生成，仅供日常健康与作息管理参考，不能替代专业医疗诊断；若持续出现静息心率明显偏高、胸闷或心律异常，请及时就医。
- 部分增强维度（如夜间皮肤温度基线偏离、SleepWise 预测）需要连续佩戴数天建立个人基线后才会有数值返回，基线建立前程序会自动标注“暂无数据”并正常运行。
