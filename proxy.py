import asyncio
import json
import os
import random
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
import httpx

KEYS_FILE = "keys.json"
KEYS = []
CURRENT_KEY_INDEX = 0

# 默认保底模型名
CURRENT_FREE_MODEL = "google/gemini-2.5-pro-exp:free"
http_client = None

def load_keys():
    global KEYS
    if os.path.exists(KEYS_FILE):
        with open(KEYS_FILE, "r") as f:
            try:
                parsed = json.load(f)
                # 过滤掉作为注释说明的伪行（以//开头的字符串元素）
                KEYS = [k for k in parsed if not k.strip().startswith("//")]
                random.shuffle(KEYS) # 打乱使得轮询时初始起跑点不同
            except Exception:
                KEYS = []

def get_next_key() -> str:
    global CURRENT_KEY_INDEX, KEYS
    if not KEYS:
        return ""
    key = KEYS[CURRENT_KEY_INDEX]
    CURRENT_KEY_INDEX = (CURRENT_KEY_INDEX + 1) % len(KEYS)
    return key

async def fetch_best_free_model():
    global CURRENT_FREE_MODEL, http_client
    try:
        # 获取 OpenRouter 上目前免费的模型列表
        response = await http_client.get("https://openrouter.ai/api/v1/models", timeout=10.0)
        if response.status_code == 200:
            data = response.json()
            free_models = []
            for model in data.get("data", []):
                pricing = model.get("pricing", {})
                if pricing.get("prompt") == "0" and pricing.get("completion") == "0":
                    free_models.append(model)
            if free_models:
                # 简单起见，从海量免费模型中随机抽取一个作为本次全局免费主力，你也可以根据其自带的 context_length 排序挑最大的
                CURRENT_FREE_MODEL = random.choice(free_models)["id"]
                print(f"[*] Fetched and updated current free model: {CURRENT_FREE_MODEL}")
    except Exception as e:
        print(f"[!] Error fetching free models: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient()
    load_keys()
    if not KEYS:
        print("[!] Warning: keys.json is empty or not found. Please add your OpenRouter keys.")
    
    # 启动拉取最优免费模型
    await fetch_best_free_model()
    
    # 后台每2小时更新一次有效模型名单
    async def periodic_update():
        while True:
            await asyncio.sleep(7200)
            await fetch_best_free_model()
    task = asyncio.create_task(periodic_update())
    
    yield
    
    task.cancel()
    await http_client.aclose()

app = FastAPI(lifespan=lifespan)

@app.post("/v1/chat/completions")
async def proxy_completions(request: Request):
    if not KEYS:
        return JSONResponse({"error": "No API keys configured in keys.json"}, status_code=500)

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    # 1. 强行接管客户端意图的模型，修改为最新的热点免费模型
    payload["model"] = CURRENT_FREE_MODEL

    max_retries = len(KEYS) * 2  # 每个 key 允许一次机会，重试两转
    attempt = 0

    # 2. 开启核心重试轮询
    while attempt < max_retries:
        current_key = get_next_key()
        attempt += 1
        
        headers = {
            "Authorization": f"Bearer {current_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/openclaw/openclawfreetoken",
            "X-Title": "OpenClaw Proxy"
        }

        req = http_client.build_request(
            "POST",
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=8.0 # 【关键约束】8秒硬阻断
        )

        try:
            response = await http_client.send(req, stream=True)
            
            # 如果触发限流（429）或网关崩溃（5xx），关闭当前流进入新循环
            if response.status_code in (429, 502, 503, 504):
                print(f"[!] Attempt {attempt}/{max_retries} failed with status {response.status_code}. Retrying...")
                await response.aclose()
                continue
            
            if response.status_code != 200:
                print(f"[!] Attempt {attempt}/{max_retries} returned {response.status_code}. Retrying...")
                await response.aclose()
                continue
            
            # 情况接通：完好无缺拿到了流信息，透明桥接到 OpenClaw 客户端
            async def stream_generator():
                async for chunk in response.aiter_bytes():
                    yield chunk
                await response.aclose()
            
            return StreamingResponse(
                stream_generator(),
                status_code=response.status_code,
                headers={k: v for k, v in response.headers.items() if k.lower() not in ('content-encoding', 'content-length', 'transfer-encoding')} # 必须滤除特定的 Http 传输头，不然在代理层面会截断
            )
            
        except httpx.ReadTimeout:
            print(f"[!] Attempt {attempt}/{max_retries} ReadTimeout (>8.0s). Swapping key/model...")
        except httpx.ConnectTimeout:
            print(f"[!] Attempt {attempt}/{max_retries} ConnectTimeout. Swapping key/model...")
        except Exception as e:
            print(f"[!] Attempt {attempt}/{max_retries} Exception: {e}. Swapping key...")

    # 如果用尽所有的可重试弹药依然完全沉默，报告崩溃
    return JSONResponse({"error": "All available proxy keys or connections failed within the timeout threshold."}, status_code=503)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("proxy:app", host="127.0.0.1", port=8000, reload=False)
