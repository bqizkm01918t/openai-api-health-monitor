# OpenAI API 可用性巡检（GitHub Actions + 流式请求）

这个项目用于**定时巡检 OpenAI 兼容接口可用性**，核心目标是：

1. 每天北京时间凌晨 2 点自动运行。
2. 按你配置的参数，发起多次请求。
3. 请求必须是**串行**（前一次完成后再下一次）。
4. 请求必须是**流式**（`stream: true`，日志实时输出 token）。
5. 运行结束后统计：
   - 模型可用性（成功率）
   - 平均耗时
   - 最快耗时
   - 最慢耗时
6. 自动把“最新结果”写到 README 末尾，并且每次运行**替换上一次结果**，不会无限追加。

---

## 目录结构

```text
.
├── .github/workflows/openai-api-availability.yml
├── scripts/openai_stream_benchmark.py
└── README.md
```

---

## 工作流说明

工作流文件：`.github/workflows/openai-api-availability.yml`

- 定时触发：`cron: "0 18 * * *"`
  - GitHub Actions 的 cron 使用 UTC。
  - `18:00 UTC` 等于北京时间（Asia/Shanghai）次日 `02:00`。
- 手动触发：`workflow_dispatch`
- 权限：`contents: write`
  - 用于自动提交 README 的运行结果。
- 执行顺序：
  1. checkout 仓库
  2. 运行 Python 脚本发起串行流式请求
  3. 提交并 push 更新后的 `README.md`
  4. 如果脚本退出码非 0，最终将 workflow 标记为失败（但 README 结果仍会先提交）

---

## 参数配置（每个参数独立设置）

你可以在仓库 `Settings -> Secrets and variables -> Actions` 中配置。

### Secrets（敏感信息）

| 名称 | 必填 | 说明 |
|---|---|---|
| `OPENAI_API_KEY` | 是 | API Key，建议只放在 Secrets，不要放变量。 |

### Variables（普通配置）

| 名称 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `OPENAI_API_URL` | 否 | `https://api.openai.com/v1/chat/completions` | 请求地址（支持 OpenAI 兼容网关）。 |
| `OPENAI_MODEL` | 否 | `gpt-4o-mini` | 模型名。 |
| `OPENAI_PROMPT` | 否 | `请简单回复：服务可用。` | 每次请求发送的用户问题内容。 |
| `OPENAI_REQUEST_COUNT` | 否 | `5` | 总请求次数（串行执行）。 |
| `OPENAI_REQUEST_TIMEOUT_SECONDS` | 否 | `120` | 单次请求超时（秒）。 |
| `OPENAI_MAX_RUNTIME_SECONDS` | 否 | `0` | 总运行时长上限，`0` 表示不限。 |
| `OPENAI_MAX_TOKENS` | 否 | `128` | 请求的 `max_tokens`。 |
| `OPENAI_TEMPERATURE` | 否 | `0.1` | 请求的 `temperature`。 |
| `OPENAI_REQUEST_PAUSE_SECONDS` | 否 | `0` | 两次请求间额外停顿秒数。 |
| `OPENAI_README_PATH` | 否 | `README.md` | 结果写入的 README 路径。 |

---

## 串行 + 流式请求机制

脚本文件：`scripts/openai_stream_benchmark.py`

- 请求体固定包含：
  - `model`
  - `messages`（system + user）
  - `stream: true`
  - `max_tokens`
  - `temperature`
- 每次请求通过 SSE 读取：
  - 逐行读取 `data: ...`
  - 遇到 `[DONE]` 结束
  - 每个 token 实时打印到日志
- 串行保证：
  - 使用普通 `for` 循环按顺序执行请求
  - 当前请求完成（成功或失败）后，才进入下一次

---

## 统计指标定义

- 可用性（Model availability）
  - `成功请求数 / 实际请求数 * 100%`
- 平均耗时（Average duration）
  - 成功请求耗时的平均值
- 最快耗时（Fastest duration）
  - 成功请求中的最小耗时
- 最慢耗时（Slowest duration）
  - 成功请求中的最大耗时

说明：
- 若没有任何成功请求，平均/最快/最慢显示为 `N/A`。
- 若触发总时长上限（`OPENAI_MAX_RUNTIME_SECONDS`），脚本会提前停止后续请求。

---

## README 自动写入/替换机制

脚本会在 README 中维护固定区块标记：

- `<!-- OPENAI_BENCHMARK_RESULTS_START -->`
- `<!-- OPENAI_BENCHMARK_RESULTS_END -->`

处理逻辑：

1. 先删除 README 中旧的标记区块（如果存在）。
2. 把“最新运行结果”区块重新写到 README 的**最后**。
3. 因此每次运行只保留一份最新结果，不会累积历史垃圾内容。

---

## 结果内容包含什么

每次运行后，README 末尾会显示：

- 运行状态（`SUCCESS` / `PARTIAL_SUCCESS` / `FAILED` / `CONFIG_ERROR` / `RUNTIME_ERROR`）
- 运行时间（UTC 和 Asia/Shanghai）
- 本次使用的 API URL、模型、Prompt
- 计划请求数和实际请求数
- 成功/失败次数
- 可用性、总耗时、平均/最快/最慢耗时
- 每个请求的明细表（序号、状态、耗时、输出字符数、错误信息）

---

## 首次使用步骤

1. 把这三个文件推送到你的仓库：
   - `.github/workflows/openai-api-availability.yml`
   - `scripts/openai_stream_benchmark.py`
   - `README.md`
2. 在仓库 Actions 设置中填好 `OPENAI_API_KEY`（Secret）和其他 Variables。
3. 去 Actions 页面手动执行一次 `OpenAI API Availability`。
4. 观察：
   - Actions 日志是否有流式 token 输出
   - Job Summary 是否有统计
   - README 末尾是否出现“最新脚本运行结果”

---

## 故障排查

### 1) 报缺少 `OPENAI_API_KEY`

- 原因：Secret 未配置。
- 处理：在 `Settings -> Secrets and variables -> Actions -> Secrets` 新增 `OPENAI_API_KEY`。

### 2) 全部请求失败

- 常见原因：
  - `OPENAI_API_URL` 错误
  - `OPENAI_MODEL` 不存在
  - Key 权限不足
  - 网关或网络问题
- 处理：
  - 先用 `OPENAI_REQUEST_COUNT=1` 做最小化测试
  - 提高 `OPENAI_REQUEST_TIMEOUT_SECONDS`
  - 查看 README 明细表中的错误信息

### 3) README 没有更新

- 检查 workflow 是否有 `contents: write`。
- 检查仓库是否允许 `GITHUB_TOKEN` 写入。
- 检查 `Commit README result` 步骤日志是否提示无变更或 push 失败。

### 4) 定时没触发

- 先确认仓库启用了 Actions。
- 先手动触发一次，确认 workflow 可正常运行。
- cron 按 UTC 执行，`0 18 * * *` 才是北京时间 2 点。

---

## 安全建议

- `OPENAI_API_KEY` 只放在 Secrets。
- 不要在 Prompt 中放敏感数据。
- README 会公开运行结果（如果仓库是公开仓库），注意避免把敏感错误原文暴露出来。

---

## 可扩展方向

- 增加多模型轮询（模型列表逐个测）。
- 统计首 token 延迟（TTFT）。
- 输出 JSON 工件（artifact）供外部系统消费。
- 增加失败阈值告警（邮件 / webhook / 飞书 / 钉钉）。

---

<!-- OPENAI_BENCHMARK_RESULTS_START -->
## 最新脚本运行结果

- 运行状态: **NOT_RUN_YET**
- 说明: 首次运行后将由脚本自动替换本区块内容。
<!-- OPENAI_BENCHMARK_RESULTS_END -->
