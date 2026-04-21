import requests
import urllib.parse
import os

def bark_push(title: str, body: str, bark_key: str, bark_host: str = None):
    """
    发送 Bark 推送
    :param title: 推送标题
    :param body: 推送内容（支持多行）
    :param bark_key: Bark 设备 Key
    :param bark_host: Bark 服务地址（从 GitHub Secrets 读取）
    """

    # ⭐ 只改这一段：从环境变量读取，不提供默认值
    if bark_host is None:
        bark_host = os.getenv("BARK_HOST")
        if not bark_host:
            raise ValueError("缺少 BARK_HOST 环境变量，无法发送 Bark 推送")

    # Bark URL Path 模式（兼容第三方 Bark）
    url = f"{bark_host}/{bark_key}/{urllib.parse.quote(title)}/{urllib.parse.quote(body)}"

    params = {
        "group": "Polar",
        "isArchive": "1",
        "level": "active"
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f"Bark 推送失败: {e}")
        return False