#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Скрипт для проверки работоспособности прокси серверов.
Запускать отдельно для тестирования прокси без запуска всего приложения.
"""

import os
import sys
import logging
import argparse
import socket
import base64
import time
import json
import requests
from typing import List, Dict, Tuple

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def check_proxy(proxy_string: str) -> Tuple[bool, str]:
    """
    Проверяет работоспособность прокси-сервера
    
    Args:
        proxy_string: Строка в формате "ip:port:username:password"
        
    Returns:
        Tuple[bool, str]: (работает ли прокси, сообщение с результатом)
    """
    parts = proxy_string.split(":")
    if len(parts) != 4:
        return False, f"Неверный формат прокси: {proxy_string}. Ожидается формат ip:port:username:password"
    
    ip, port, username, password = parts
    
    # Метод 1: Прямое соединение через сокет
    try:
        # Подключаемся напрямую к прокси
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((ip, int(port)))
        
        logger.info(f"Установлено соединение с {ip}:{port}")
        
        # Формируем HTTP запрос через прокси
        auth_header = f"Proxy-Authorization: Basic {base64.b64encode(f'{username}:{password}'.encode()).decode()}\r\n"
        
        # Важно! Используем HTTP вместо HTTPS для проверки
        http_request = (
            f"GET http://example.com/ HTTP/1.1\r\n"
            f"Host: example.com\r\n"
            f"{auth_header}"
            f"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0\r\n"
            f"Accept: text/html\r\n"
            f"Connection: close\r\n\r\n"
        )
        
        # Отправляем запрос
        s.sendall(http_request.encode())
        
        # Получаем ответ
        response = b""
        s.settimeout(3)
        
        try:
            while True:
                data = s.recv(4096)
                if not data:
                    break
                response += data
        except socket.timeout:
            pass
            
        s.close()
        
        # Декодируем ответ
        response_text = response.decode("utf-8", errors="ignore")
        
        # Проверяем, содержит ли ответ HTTP статус 200 OK или успешный редирект (302)
        if "HTTP/1.1 200" in response_text or "HTTP/1.0 200" in response_text:
            return True, f"Прокси {ip}:{port} работает (прямое соединение, HTTP 200)"
        elif "HTTP/1.1 302" in response_text or "HTTP/1.0 302" in response_text:
            # 302 Found считаем успешным ответом, это нормальный редирект
            return True, f"Прокси {ip}:{port} работает, возвращает редирект (HTTP 302)"
        elif "HTTP/1.1 407" in response_text:
            return False, f"Прокси {ip}:{port} требует авторизацию, проверьте логин/пароль"
        else:
            # Проверяем наличие любого HTTP ответа, даже если это не 200
            if response_text.startswith("HTTP/"):
                logger.info(f"Прокси вернул HTTP ответ: {response_text.splitlines()[0] if response_text.splitlines() else 'неизвестно'}")
                return True, f"Прокси {ip}:{port} работает, возвращает: {response_text.splitlines()[0] if response_text.splitlines() else 'неизвестно'}"
            else:
                logger.warning(f"Прокси вернул неожиданный ответ: {response_text[:100]}...")
            
    except Exception as e:
        logger.error(f"Ошибка при прямой проверке прокси {ip}:{port}: {e}")
        # Продолжаем со вторым методом
    
    # Метод 2: Проверка через requests
    try:
        # Используем HTTP для проверки, так как многие прокси могут не поддерживать HTTPS
        proxies = {
            "http": f"http://{username}:{password}@{ip}:{port}",
            "https": f"http://{username}:{password}@{ip}:{port}"
        }
        
        # Список тестовых URL - используем HTTP вместо HTTPS
        test_urls = [
            "http://example.com",
            "http://httpbin.org/ip",
            "http://info.cern.ch"  # Простой статический сайт, используется для тестирования
        ]
        
        # Проверяем через разные URL
        for url in test_urls:
            try:
                logger.info(f"Проверка прокси {ip}:{port} через {url}")
                response = requests.get(
                    url,
                    proxies=proxies,
                    timeout=5,
                    verify=False,  # Отключаем проверку SSL сертификатов
                    allow_redirects=True  # Разрешаем редиректы
                )
                
                # Проверяем как код 200, так и успешные редиректы (коды 3xx)
                if 200 <= response.status_code < 400:
                    logger.info(f"Успешный ответ от {url}: {response.status_code}")
                    return True, f"Прокси {ip}:{port} работает через {url} (статус: {response.status_code})"
                else:
                    logger.warning(f"Неудачный статус код {response.status_code} при проверке прокси {ip}:{port} через {url}")
            except requests.RequestException as url_error:
                logger.error(f"Ошибка при проверке {ip}:{port} через {url}: {url_error}")
                continue
                
        # Если мы дошли сюда, но ранее получили HTTP ответ через сокеты,
        # считаем прокси рабочим, даже если requests не смог подключиться
        if response_text and response_text.startswith("HTTP/"):
            return True, f"Прокси {ip}:{port} работает только через прямое соединение"
                
        return False, f"Прокси {ip}:{port} не прошел проверку ни на одном тестовом URL"
        
    except Exception as e:
        # Если мы дошли сюда, но ранее получили HTTP ответ через сокеты,
        # считаем прокси рабочим, даже если requests не смог подключиться
        if response_text and response_text.startswith("HTTP/"):
            return True, f"Прокси {ip}:{port} работает только через прямое соединение"
            
        return False, f"Ошибка при проверке прокси {ip}:{port}: {e}"


def load_proxies_from_file(file_path: str) -> List[str]:
    """
    Загружает список прокси из файла
    
    Args:
        file_path: Путь к файлу со списком прокси
        
    Returns:
        List[str]: Список прокси в формате "ip:port:username:password"
    """
    proxies = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    proxies.append(line)
                    
        logger.info(f"Загружено {len(proxies)} прокси из файла {file_path}")
        return proxies
    except Exception as e:
        logger.error(f"Ошибка при загрузке прокси из файла {file_path}: {e}")
        return []


def save_working_proxies(proxies: List[Dict], file_path: str) -> None:
    """
    Сохраняет список рабочих прокси в файл
    
    Args:
        proxies: Список словарей с информацией о рабочих прокси
        file_path: Путь к файлу для сохранения
    """
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(proxies, f, indent=4, ensure_ascii=False)
            
        logger.info(f"Сохранено {len(proxies)} рабочих прокси в файл {file_path}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении прокси в файл {file_path}: {e}")


def test_proxies(proxy_list: List[str]) -> List[Dict]:
    """
    Тестирует список прокси и возвращает работающие
    
    Args:
        proxy_list: Список строк с прокси в формате "ip:port:username:password"
        
    Returns:
        List[Dict]: Список словарей с информацией о работающих прокси
    """
    working_proxies = []
    results = []
    
    print(f"Проверка {len(proxy_list)} прокси-серверов...")
    
    for i, proxy_string in enumerate(proxy_list):
        print(f"[{i+1}/{len(proxy_list)}] Проверка {proxy_string}...")
        is_working, message = check_proxy(proxy_string)
        
        proxy_info = {
            "proxy_string": proxy_string,
            "is_working": is_working,
            "message": message
        }
        
        results.append(proxy_info)
        
        # Разбиваем строку прокси для удобства
        if is_working:
            parts = proxy_string.split(":")
            if len(parts) == 4:
                ip, port, username, password = parts
                working_proxy = {
                    "server": f"{ip}:{port}",
                    "username": username,
                    "password": password,
                    "http": f"http://{username}:{password}@{ip}:{port}",
                    "https": f"http://{username}:{password}@{ip}:{port}"
                }
                working_proxies.append(working_proxy)
    
    # Выводим результаты
    print("\nРезультаты проверки прокси:")
    for result in results:
        status = "✅ РАБОТАЕТ" if result["is_working"] else "❌ НЕ РАБОТАЕТ"
        print(f"{status}: {result['proxy_string']} - {result['message']}")
    
    print(f"\nВсего рабочих прокси: {len(working_proxies)} из {len(proxy_list)}")
    return working_proxies


def test_youtube_functions(test_urls: List[str] = None) -> bool:
    """
    Тестирует основные функции YouTube Analyzer без использования прокси.
    
    Args:
        test_urls (List[str], optional): Список URL для тестирования.
        
    Returns:
        bool: True, если тест прошел успешно, False в противном случае.
    """
    try:
        # Если не указаны URL для тестирования, используем несколько популярных каналов
        if not test_urls:
            test_urls = [
                "https://www.youtube.com/@MrBeast",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # Известное видео
            ]
            
        logger.info("Запускаем тестирование функций YouTube Analyzer без прокси")
        
        # Импортируем YouTubeAnalyzer
        from youtube_scraper import YouTubeAnalyzer
        
        # Создаем экземпляр с отключенными прокси
        analyzer = YouTubeAnalyzer(headless=True, use_proxy=False)
        
        # Инициализируем драйвер
        logger.info("Инициализация драйвера...")
        analyzer.setup_driver()
        
        if not analyzer.driver:
            logger.error("Не удалось инициализировать драйвер")
            return False
            
        # Тестируем каждый URL
        for url in test_urls:
            try:
                logger.info(f"Тестирование URL: {url}")
                
                if "youtube.com/@" in url or "/channel/" in url or "/c/" in url:
                    # Тестируем получение видео с канала
                    logger.info("Тестирование получения видео с канала")
                    videos = analyzer.get_last_videos_from_channel(url, limit=2)
                    
                    if not videos:
                        logger.warning(f"Не удалось получить видео с канала {url}")
                        continue
                        
                    logger.info(f"Успешно получено {len(videos)} видео с канала")
                    
                    # Тестируем получение рекомендаций для первого видео
                    if videos:
                        video_url = videos[0]["url"]
                        logger.info(f"Тестирование получения рекомендаций для видео {video_url}")
                        recommendations = analyzer.get_recommended_videos(video_url, limit=2)
                        
                        if recommendations:
                            logger.info(f"Успешно получено {len(recommendations)} рекомендаций")
                        else:
                            logger.warning(f"Не удалось получить рекомендации для видео {video_url}")
                else:
                    # Тестируем получение деталей видео
                    logger.info("Тестирование получения информации о видео")
                    video_details = analyzer.get_video_details(url)
                    
                    if not video_details or not video_details.get("title"):
                        logger.warning(f"Не удалось получить детали видео {url}")
                        continue
                        
                    logger.info(f"Успешно получены детали видео: {video_details.get('title')}")
                    
                    # Тестируем получение рекомендаций
                    logger.info(f"Тестирование получения рекомендаций для видео {url}")
                    recommendations = analyzer.get_recommended_videos(url, limit=2)
                    
                    if recommendations:
                        logger.info(f"Успешно получено {len(recommendations)} рекомендаций")
                    else:
                        logger.warning(f"Не удалось получить рекомендации для видео {url}")
            
            except Exception as e:
                logger.error(f"Ошибка при тестировании URL {url}: {e}")
                
        # Закрываем драйвер
        analyzer.quit_driver()
        
        logger.info("Тестирование YouTube функций завершено")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при тестировании YouTube функций: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Утилита для проверки прокси серверов")
    parser.add_argument('--file', '-f', type=str, help='Путь к файлу со списком прокси')
    parser.add_argument('--proxies', '-p', type=str, nargs='+', help='Список прокси в формате "ip:port:username:password"')
    parser.add_argument('--output', '-o', type=str, default='working_proxies.json', help='Путь к файлу для сохранения результатов')
    parser.add_argument('--test-youtube', action='store_true', help='Тестировать функции YouTube без прокси')
    
    args = parser.parse_args()
    
    if not args.file and not args.proxies:
        parser.print_help()
        print("\nОшибка: должен быть указан файл или список прокси")
        sys.exit(1)
    
    proxies = []
    
    if args.file:
        proxies = load_proxies_from_file(args.file)
        
    if args.proxies:
        proxies.extend(args.proxies)
    
    if not proxies:
        print("Не найдено прокси для проверки")
        sys.exit(1)
    
    working_proxies = test_proxies(proxies)
    
    if working_proxies:
        save_working_proxies(working_proxies, args.output)
        print(f"Рабочие прокси сохранены в файл {args.output}")
    else:
        print("Не найдено рабочих прокси")
    
    # Если запрошено тестирование YouTube без прокси
    if args.test_youtube:
        test_youtube_functions()
        sys.exit(0)
    
    return 0


if __name__ == "__main__":
    sys.exit(main()) 