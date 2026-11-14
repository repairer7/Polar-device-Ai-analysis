import os
import urllib.parse
import requests


def bark_push(title: str, body: str, bark_key: str, bark_host: str = None):
    """
    发送 Bark 推送（优先使用 POST JSON 避免长文本被 URL 截断，失败时兼容回退 GET）
    :param title: 推送标题
    :param body: 推送内容（支持多行）
    :param bark_key: Bark 设备 Key
    :param bark_host: Bark 服务地址（从 GitHub Secrets 读取）
    """
    if bark_host is None:
        bark_host = os.getenv("BARK_HOST")
        if not bark_host:
            raise ValueError("缺少 BARK_HOST 环境变量，无法发送 Bark 推送")

    if not bark_key:
        raise ValueError("缺少 BARK_KEY，无法发送 Bark 推送")

    host = bark_host.strip().rstrip("/")
    params = {
        "group": "Polar",
        "isArchive": "1",
        "level": "active",
    }

    # 1. 优先 POST /push JSON 模式（支持长文本报告，防止 HTTP 414）
    post_url = f"{host}/push"
    payload = {
        "device_key": bark_key,
        "title": title,
        "body": body,
        **params,
    }
    try:
        resp = requests.post(
            post_url,
            json=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=15,
        )
        if resp.status_code == 200:
            try:
                data = resp.json()
                if isinstance(data, dict) and data.get("code") not in (None, 200):
                    print(f"Bark POST 返回业务错误: {data}")
                else:
                    return True
            except ValueError:
                return True
        else:
            print(f"Bark POST 失败 (HTTP {resp.status_code})，尝试回退 GET 模式...")
    except Exception as e:
        print(f"Bark POST 请求异常: {e}，尝试回退 GET 模式...")

    # 2. 回退原 URL Path GET 模式（兼容精简版第三方反代）
    get_url = f"{host}/{bark_key}/{urllib.parse.quote(title, safe='')}/{urllib.parse.quote(body, safe='')}"
    try:
        resp = requests.get(get_url, params=params, timeout=15)
        if resp.status_code == 200:
            return True
        print(f"Bark GET 推送失败 (HTTP {resp.status_code})")
        return False
    except Exception as e:
        print(f"Bark 推送失败: {e}")
        return False
