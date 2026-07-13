# Polar Device AI Analysis

基于 Polar AccessLink API 和 Gemini 的健康数据分析工具。

项目从 Polar 健康监测设备同步睡眠、连续心率、活动量和 Nightly Recharge 数据，将指定时间范围内的健康数据交给 Gemini 进行分析，并通过 Bark 推送一份适合手机阅读的中文健康报告。

## 功能特性

- 同步 Polar 睡眠数据
- 同步日常连续心率数据
- 同步活动和步数数据
- 同步 Nightly Recharge 数据
- 使用 Gemini 生成结构化健康分析和生活建议
- 通过 Bark 推送分析报告
- 对 Bark 推送和 Gemini 请求进行失败重试
- 使用 GitHub Actions 执行，无需额外服务器

## 数据分析范围

程序默认以当天日期为报告日期，分析时间区间为：

```text
前一天 21:00 至当天 20:59
```

各类数据的处理方式如下：

| 数据类型 | 获取内容 | 处理方式 |
| --- | --- | --- |
| 睡眠 | 睡眠开始时间、结束时间、睡眠得分 | 匹配当天的睡眠记录 |
| 连续心率 | 平均、最高、最低心率和样本数量 | 合并前一天和当天数据，过滤 21:00 分界线外的数据和心率为 0 的样本 |
| 活动 | 步数和活动样本 | 严格过滤到指定时间范围后统计 |
| Nightly Recharge | HRV、呼吸率、ANS Charge 和状态 | 获取当天的 Nightly Recharge 数据 |

注意：代码中的连续心率数据是日常监测数据，不包含运动心率。Gemini 提示词会要求按照静息或日常活动心率进行解读。

## 项目结构

```text
.
├── .github/
│   └── workflows/
│       └── main.yml              # GitHub Actions 工作流
├── main.py                       # 主程序，负责同步、分析和推送
├── sleep_sync.py                 # Polar 睡眠数据同步
├── hr_sync.py                    # Polar 连续心率数据同步
├── activity_sync.py              # Polar 活动数据同步
├── nightly_recharge.py           # Polar Nightly Recharge 数据同步
├── bark_push.py                  # Bark 推送封装
├── requirements.txt              # Python 依赖
└── README1.md                   # 项目说明
```

## 工作原理

程序运行时会按以下流程执行：

1. 获取当前日期和前一天日期
2. 调用 Polar AccessLink API 获取健康数据
3. 过滤并统计 21:00 到次日 20:59 的有效数据
4. 组装睡眠、Nightly Recharge、心率和活动摘要
5. 将摘要和原始数据交给 Gemini
6. 生成中文纯文本健康分析报告
7. 通过 Bark 推送报告

Gemini 生成的报告包含以下内容：

- 睡眠质量分析
- Nightly Recharge 分析
- 心脏负荷分析
- 活动水平分析
- 潜在健康隐患
- 综合建议

报告被限制为短文本格式，适合直接在 Bark 通知中阅读。

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
| `POLAR_TOKEN` | Polar AccessLink API 访问令牌 | `your-polar-token` |
| `GEMINI_API_KEY` | Google Gemini API Key | `your-gemini-api-key` |
| `BARK_HOST` | Bark 服务地址或域名 | `https://api.day.app` |
| `BARK_KEY` | Bark 设备 Key | `your-bark-key` |

代码会从环境变量读取以上配置。请不要将 Polar Token、Gemini API Key 或 Bark Key 直接写入代码。

### 3. 手动执行工作流

进入仓库的 **Actions** 页面，选择：

```text
Polar Health Sync & Gemini Analysis
```

点击：

```text
Run workflow
```

当前工作流使用 `workflow_dispatch`，默认不会自动定时运行。

### 4. 查看结果

- 在 GitHub Actions 日志中查看数据同步、Gemini 分析和 Bark 推送过程
- 在 Bark 应用中查看最终健康报告
- 如果执行失败，可根据 Actions 日志定位 API、权限或推送问题

## 本地运行

### 环境要求

- Python 3.10 或更高版本
- 有效的 Polar AccessLink API Token
- 可用的 Gemini API Key
- Bark 设备 Key
- 能够访问 Polar、Google Gemini 和 Bark 服务的网络环境

### 安装依赖

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 配置环境变量

Linux/macOS：

```bash
export POLAR_TOKEN="your-polar-token"
export GEMINI_API_KEY="your-gemini-api-key"
export BARK_HOST="https://api.day.app"
export BARK_KEY="your-bark-key"
```

Windows PowerShell：

```powershell
$env:POLAR_TOKEN="your-polar-token"
$env:GEMINI_API_KEY="your-gemini-api-key"
$env:BARK_HOST="https://api.day.app"
$env:BARK_KEY="your-bark-key"
```

运行主程序：

```bash
python main.py
```

## API 和权限说明

### Polar AccessLink

程序使用 Polar AccessLink API v3，访问地址为：

```text
https://www.polaraccesslink.com/v3
```

需要确保 Token 有权访问以下数据：

- 睡眠数据
- 连续心率数据
- 活动样本数据
- Nightly Recharge 数据

如果某类数据暂时没有记录，程序会返回空摘要，Gemini 仍可能基于其他可用数据生成报告。

### Gemini

当前程序使用 Google Gen AI SDK，并配置了以下模型：

```python
models/gemini-3-flash-preview
```

如果该模型在你的 API 账号或地区不可用，需要根据 Gemini API 当前可用模型修改 `main.py` 中的 `MODEL_ID`。

### Bark

Bark 通知使用以下参数：

```text
group=Polar
isArchive=1
level=active
```

通知标题格式为：

```text
YYYY年M月D日健康监测分析
```

## 重试机制

### Gemini 请求

当 Gemini 返回 `503` 或 `UNAVAILABLE` 时，程序最多重试 5 次，并使用指数退避等待。

### Bark 推送

Bark 推送失败时最多重试 5 次，等待时间依次增加：

```text
1 秒、2 秒、4 秒、8 秒、16 秒
```

如果多次尝试仍失败，程序会在日志中报告推送失败。

## 注意事项

- 当前 GitHub Actions 仅支持手动触发，没有配置 `schedule`
- Polar API、Gemini API 和 Bark 都可能存在调用限制或服务异常
- Polar Token 和 Gemini API Key 属于敏感凭证，应使用 GitHub Secrets 或本地环境变量保存
- 睡眠、心率和活动数据缺失时，报告内容可能不完整
- 时区由运行环境决定，GitHub Actions 默认使用 UTC；如果需要严格按照本地时间分析，建议在代码中显式处理时区
- Gemini 生成的内容仅供健康管理参考，不能替代医生诊断或专业医疗建议
- 若出现持续异常心率、严重睡眠问题或其他身体不适，应及时咨询专业医疗人员

## 技术栈

- Python
- Polar AccessLink API v3
- Google Gemini API
- `google-genai`
- `requests`
- GitHub Actions
- Bark

## 许可证

本项目当前未指定开源许可证。若希望明确允许其他人使用、修改和分发代码，建议根据实际需求添加 MIT 或 Apache-2.0 等许可证。
