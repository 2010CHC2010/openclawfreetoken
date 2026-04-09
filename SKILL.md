---
name: openclawfreetoken
description: A local proxy skill for OpenClaw that natively manages and fetches multi-OpenRouter keys. It catches API timeouts (>8s) silently and swaps models/keys on the fly to bypass free-layer connection limitations.
---

# `openclawfreetoken` 核心辅助环境指引

## 1. 目标描述 (Purpose)
你现在是 `openclawfreetoken` 设施的管理主脑。在这个工程体系里，玩家提供一系列 OpenRouter 的 Free Key 用于日常闲聊和推理。
代理文件 `proxy.py` 扮演网关。你的职责是：必须时刻确保该本地代理服务器存活，并在客户端网络设置上完成向该本地网关的“偷梁换柱”。

## 2. 操作机制 - 执行心跳与自检 (CRITICAL)

当你在上下文中注意到或者被明确提示执行该技能时（或者运行任务前发现调用受阻）：

### 第 1 步：依赖与密钥补全检测
1. 检测 `keys.json` 内容：如果没有这个文件或者里面是空列表 `[]`，友善地向人类用户说明需要将他搜集的 `sk-or-v1-xxx` 字符串写入列表形式。
2. 确认拥有 `pip install -r requirements.txt`。

### 第 2 步：后台存活拦截探测
你要借助系统执行命令行去拉起守护进程：
如果你通过 `netstat` 或由于直连 `http://127.0.0.1:8000` 发现服务没有开启，你需要执行后台静默拉起：
```bash
uvicorn proxy:app --host 127.0.0.1 --port 8000 &
```
*(注意末尾的 `&` 是防止阻塞进程，如果在非 bash 环境，可用类似 python 的 subprocess，确保完全挂到守护台).*

### 第 3 步：内部网络配置篡改
在确保 `127.0.0.1:8000` 端口已经健康后。
引导用户（或如果你有权限可以自行）修改你的大语言模型配置卡：
- **API Base URL**改为：`http://127.0.0.1:8000/v1`
- **API Key** 改为：输入任何假数据（例如 `sk-openclaw-mock`），它的校验会在底层被代理覆盖下发真实的 Key。
- **Model** 改为：直接填写任何意图模型名，底层统统会被强截替换为 `free` 限定最优模型。

完成这三步后，所有网络超时的大山就被搬开了。遇到偶尔超时的提示，系统底层会打印日记并立刻连新线，你不需要因此停止执行任务。
