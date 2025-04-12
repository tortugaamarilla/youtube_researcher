import os
import random
import streamlit as st
from typing import List, Dict, Optional, Tuple
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_api_keys() -> Tuple[Optional[str], Optional[str]]:
    """
    Получает API ключи из секретов Streamlit.
    
    Returns:
        Tuple[Optional[str], Optional[str]]: Кортеж (openai_api_key, anthropic_api_key)
    """
    openai_api_key = None
    anthropic_api_key = None
    
    try:
        # Проверяем локальный запуск (файл secrets.toml)
        if "OPENAI_API_KEY" in st.secrets:
            openai_api_key = st.secrets["OPENAI_API_KEY"]
        
        if "ANTHROPIC_API_KEY" in st.secrets:
            anthropic_api_key = st.secrets["ANTHROPIC_API_KEY"]
            
    except Exception as e:
        logger.warning(f"Не удалось загрузить API ключи из секретов: {e}")
        
    return openai_api_key, anthropic_api_key

def get_proxy_list() -> List[Dict[str, str]]:
    """
    Получает список прокси из секретов Streamlit и форматирует их для использования.
    
    Returns:
        List[Dict[str, str]]: Список словарей с настройками прокси
    """
    proxies = []
    
    try:
        if "proxies" in st.secrets and "servers" in st.secrets["proxies"]:
            proxy_servers = st.secrets["proxies"]["servers"]
            
            for proxy_str in proxy_servers:
                parts = proxy_str.split(":")
                if len(parts) == 4:
                    ip, port, username, password = parts
                    proxy = {
                        "server": f"{ip}:{port}",
                        "username": username,
                        "password": password,
                        "http": f"http://{username}:{password}@{ip}:{port}",
                        "https": f"https://{username}:{password}@{ip}:{port}"
                    }
                    proxies.append(proxy)
                    
    except Exception as e:
        logger.warning(f"Не удалось загрузить список прокси из секретов: {e}")
        
    return proxies

def get_random_proxy(verified_proxies: List[Dict[str, str]] = None) -> Optional[Dict[str, str]]:
    """
    Выбирает случайный прокси из списка доступных.
    
    Args:
        verified_proxies (List[Dict[str, str]], optional): Список проверенных прокси.
        
    Returns:
        Optional[Dict[str, str]]: Случайный прокси или None, если список пуст
    """
    if verified_proxies:
        proxies = verified_proxies
    else:
        proxies = get_proxy_list()
        
    if not proxies:
        logger.warning("Список прокси пуст")
        return None
        
    return random.choice(proxies)

def parse_youtube_url(url: str) -> Tuple[str, bool]:
    """
    Определяет тип YouTube URL (канал или видео).
    
    Args:
        url (str): URL для анализа
        
    Returns:
        Tuple[str, bool]: (url, is_channel)
    """
    if not url:
        return "", False
        
    url = url.strip()
    
    # Проверка наличия YouTube в URL
    if not ('youtube.com' in url or 'youtu.be' in url):
        logger.warning(f"URL не является ссылкой на YouTube: {url}")
        return url, False
    
    # Проверка на URL канала
    channel_indicators = [
        "youtube.com/channel/", 
        "youtube.com/c/", 
        "youtube.com/user/",
        "youtube.com/@",
        "youtube.com/profile",
        "/featured",
        "/videos"
    ]
    
    # Прямая проверка на URL видео
    video_indicators = [
        "youtube.com/watch",
        "youtu.be/"
    ]
    
    is_video = any(indicator in url for indicator in video_indicators)
    
    # Если это явно видео, возвращаем False для is_channel
    if is_video:
        logger.info(f"Определено как URL видео: {url}")
        return url, False
    
    # Если это явно канал или плейлист с видео
    is_channel = any(indicator in url for indicator in channel_indicators)
    
    if is_channel:
        logger.info(f"Определено как URL канала: {url}")
        
        # Исправляем URL канала, если он не содержит /videos в конце
        if not url.endswith("/videos") and "/videos" not in url:
            if url.endswith("/"):
                url = f"{url}videos"
            else:
                url = f"{url}/videos"
                
        return url, True
    
    # По умолчанию считаем, что это видео
    logger.info(f"Не удалось определить тип URL, считаем видео по умолчанию: {url}")
    return url, False 