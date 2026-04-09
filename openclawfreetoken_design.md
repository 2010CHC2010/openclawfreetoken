# OpenClaw Skill Design: `openclawfreetoken`

## 1. 需求理解摘要 (Understanding Summary)
* **What（做什么）**：构建一个名为 `openclawfreetoken` 的附属生态 Skill（不仅是 Prompt，还包含本地服务代理软件）。
* **Why（为什么做）**：在利用 OpenRouter 免费羊毛资源时，这些免费模型极其容易出现无响应、限流或崩溃问题。传统的客户端遇错即崩溃导致使用体验极差。该 Skill 用于把出错、轮询、超时等不稳定因素全盘屏蔽在本地网络代理层。
* **Who（为谁做）**：在个人开发电脑上使用 OpenClaw 助手，希望降本降开销的研发/使用人员。
* **Key Constraints（关键基准线）**：超时切换（>8s）必须做到客户端无感知，流式（Streaming SSE）输出时延不可有损毁；生命周期必须交由主脑 OpenClaw 的生命周期管理。
* **Explicit Non-goals（排除目标）**：不做用于部署在公网被外部滥用的服务端中间件；不设计极其复杂花哨的可视化操控页面配置。

## 2. 假设前提 (Assumptions)
* **性能与规模**：这是单机自用挂载辅助件，完全不考虑分布式环境和高并发压力测试，主要解决单条流水线稳定性。
* **安全隐私**：绝不在代码版本库管理追踪任何 API Keys（如设定 `.gitignore`）；微型 Proxy 服务器绑定在 `127.0.0.1`，直接隔绝局域网访问刺探安全隐患。
* **错误熔断**：虽然会死命在后台寻找新 Key 和新可用资源重组轮询，一旦彻底用完所有可用池里的弹药库并且全部失败，系统会优雅向 OpenClaw 呈现 `503 Service Unavailable` 要求客户端终止。

## 3. 决策日志 (Decision Log)

| 决策点 | 候选方案 | 最终决定与采取缘由 |
| :--- | :--- | :--- |
| **集成机制方案** | 1. FastAPI 代理模块<br>2. 纯挂脚本/指令让系统修改自己配置 <br>3. 完全依赖其他现成中间库(LiteLLM) | 采取了 **1. 代理拦截器（FastAPI+httpx代理）**。只有这种方案能够在微秒级控制 HTTP 底层超时时间，且可以完美中继分块传输并劫持拦截其连接错漏，做到真正的上游 OpenClaw 无感。 |
| **守护进程管理** | 1. 玩家自管启动 <br>2. SKILL.md 监督式命令智能代管 | 选择 **2. SKILL.md 托管**。这样玩家可以做到真正的即刻导入。只要技能装进去，大语言模型可以自己使用 bash `netstat` 检测服务自己执行 `uvicorn`，体验感满分。 |
| **8s 故障响应策略** | 1. 原封报错并让调用者反思重发请求 <br>2. 拦截并静默无限重接下一位 | 选择 **2. 设置底线静默重接**。这种策略直接终结了 LLM “一直报错中断对话”带来的恶劣体验。如果没接到任何文字则直接断流重选模型并更换 OpenRouter 账号鉴权。 |

## 4. 最终核心架构设计 (Final Blueprint)

### 一、运行架构

```text
openclawfreetoken/
├── SKILL.md            # 内置智能托管和引导启动的Prompt指导，系统接驳规范
├── proxy.py            # 主代理网关（Python ASGI APP）
├── requirements.txt    # 三把小刀：fastapi, uvicorn, httpx
├── keys.json           # Array: [ "sk-or-v1-xxx", ... ]
└── .gitignore          # 忽略关键配置文件
```

### 二、底层动作流程

1. **环境准备与守护**
   通过 `SKILL.md` 的强制要求，让主系统在使用期间探测前置条件，补齐三方依赖并执行：
   `uvicorn proxy:app --host 127.0.0.1 --port 8000 &`

2. **全局智能预读**
   在 `proxy.py` 初始化完毕准备接起 HTTP 监听之前，执行异步任务：访问 `https://openrouter.ai/api/v1/models`，使用内存缓存存取性价比/限额最优的完全免费模型名字符串至 `CURRENT_FREE_MODEL`。

3. **OpenRouter 拦截流式转发处理 (Retry Loop Block)**
   - OpenClaw 发来伪造的 `/v1/chat/completions` 请求，并带有假 Token 以及原本意图的模型。
   - `proxy.py` 利用 `httpx.AsyncClient`(Timeout=8.0秒) 注入自己轮询的 Key，篡改原本的模型名。
   - 若发出并在八秒内发生错误、超时或者任何 4xx\5xx 拒网，利用 `while` 重置，推进 Index 继续尝试。
   - 一旦接通（`Status=200`），挂接底层的 `Response.aiter_lines()` 输出流原封不动向后方客户端直接吐出流式字节，完成无感接管。
