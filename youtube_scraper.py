import os
import time
import base64
import random
import logging
import traceback
import json
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Tuple
import requests
from io import BytesIO
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.remote.webelement import WebElement
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, 
    StaleElementReferenceException, WebDriverException
)
# Изменяем импорт для совместимости с версией 3.4.6
import undetected_chromedriver as uc
from webdriver_manager.chrome import ChromeDriverManager
from PIL import Image
import pandas as pd
import tempfile
import zipfile
import socket

from utils import get_random_proxy, parse_youtube_url, get_proxy_list

# Настройка логирования
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class YouTubeAnalyzer:
    """
    Класс для анализа видео на YouTube с использованием Selenium.
    """
    
    def __init__(self, headless: bool = True, use_proxy: bool = True, google_account: Dict[str, str] = None):
        """
        Инициализация анализатора YouTube.
        
        Args:
            headless (bool): Запускать браузер в фоновом режиме.
            use_proxy (bool): Использовать прокси-сервера.
            google_account (Dict[str, str], optional): Аккаунт Google для авторизации. 
                                                       Должен содержать 'email' и 'password'.
        """
        self.headless = headless
        self.use_proxy = use_proxy
        self.google_account = google_account
        self.driver = None
        self.current_proxy = None
        self.proxy_list = None  # Список проверенных прокси
        self.is_logged_in = False  # Флаг авторизации
        
    def setup_driver(self) -> None:
        """
        Инициализирует веб-драйвер для автоматизации браузера.
        """
        try:
            logger.info("Настройка драйвера Chrome")

            # Очищаем прежний драйвер, если он остался
            if self.driver:
                try:
                    self.driver.quit()
                    self.driver = None
                    time.sleep(1)
                    logger.info("Предыдущий драйвер успешно закрыт")
                except:
                    logger.warning("Не удалось корректно закрыть предыдущий драйвер")

            # Опции Chrome
            chrome_options = webdriver.ChromeOptions()
            
            # Базовые настройки для стабильности и скорости
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-notifications")
            chrome_options.add_argument("--disable-popup-blocking")
            
            # Отключаем автовоспроизведение видео и звук
            chrome_options.add_argument("--autoplay-policy=user-gesture-required")
            chrome_options.add_argument("--mute-audio")
            
            # Отключаем сбор данных
            chrome_options.add_argument("--disable-features=RendererCodeIntegrity")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            
            # Если требуется режим без интерфейса
            if self.headless:
                chrome_options.add_argument("--headless=new")
            
            # Установка разрешения окна
            chrome_options.add_argument("--window-size=1920,1080")
            
            # Настройка User-Agent для имитации обычного пользователя
            chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            
            # Настройка языка
            chrome_options.add_argument("--lang=ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7")
            
            # Отключаем автоматизацию для более естественного поведения
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option("useAutomationExtension", False)
            
            # Дополнительные настройки для ускорения работы
            chrome_options.add_argument("--disable-web-security")
            chrome_options.add_argument("--allow-running-insecure-content")
            chrome_options.add_argument("--disable-setuid-sandbox")
            
            # Настраиваем прокси, если нужно
            if self.use_proxy:
                # Обновляем список прокси, если он пустой
                if not self.proxy_list:
                    self.proxy_list = get_proxy_list()
                    
                # Проверяем, есть ли прокси
                if self.proxy_list:
                    logger.info(f"Загружено {len(self.proxy_list)} прокси")
                    # Выбираем случайный прокси
                    self._set_random_proxy()
                    
                    if self.current_proxy:
                        proxy_server = self.current_proxy.get("server")
                        logger.info(f"Используем прокси: {proxy_server}")
                        
                        # Добавляем настройки прокси в опции Chrome
                        chrome_options.add_argument(f"--proxy-server={proxy_server}")
                else:
                    logger.warning("Список прокси пуст. Продолжение без прокси.")
                    self.use_proxy = False
            
            # Логирование инициализации драйвера
            logger.info("Создаём экземпляр драйвера Chrome")
            
            # Несколько попыток инициализации драйвера с разными настройками
            for attempt in range(3):
                success = False
                try:
                    logger.info(f"Попытка инициализации драйвера #{attempt+1}")
                    
                    if attempt == 0:
                        # Стандартный подход
                        self.driver = webdriver.Chrome(options=chrome_options)
                    elif attempt == 1:
                        # Упрощенный подход без лишних опций
                        simple_options = webdriver.ChromeOptions()
                        if self.headless:
                            simple_options.add_argument("--headless=new")
                        simple_options.add_argument("--disable-gpu")
                        simple_options.add_argument("--no-sandbox")
                        
                        self.driver = webdriver.Chrome(options=simple_options)
                    else:
                        # Крайне упрощенный подход
                        minimal_options = webdriver.ChromeOptions()
                        self.driver = webdriver.Chrome(options=minimal_options)
                    
                    logger.info(f"Драйвер Chrome успешно инициализирован (попытка #{attempt+1})")
                    
                    # Устанавливаем таймауты
                    self.driver.set_page_load_timeout(30)
                    self.driver.implicitly_wait(10)
                    
                    # Настройка поведения для обхода обнаружения автоматизации
                    self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                    
                    # Тестируем работоспособность драйвера на простой странице
                    logger.info("Тестирование драйвера на простой странице")
                    self.driver.get("https://www.google.com")
                    
                    # Проверяем, загрузилась ли страница
                    if "Google" in self.driver.title:
                        logger.info("Тест драйвера успешно пройден")
                        
                        # Если используется прокси, настраиваем аутентификацию
                        if self.use_proxy and self.current_proxy:
                            self._handle_proxy_auth()
                        
                        success = True
                        break  # Успешно инициализировали драйвер
                    else:
                        logger.warning(f"Тест драйвера не пройден: неверный заголовок страницы '{self.driver.title}'")
                        # Закрываем драйвер и пробуем еще раз
                        self.driver.quit()
                        self.driver = None
                        
                except Exception as e:
                    logger.error(f"Ошибка при инициализации или тестировании драйвера (попытка #{attempt+1}): {e}")
                    if self.driver:
                        try:
                            self.driver.quit()
                        except:
                            pass
                        self.driver = None
            
            # Если после всех попыток драйвер все еще None, логируем ошибку
            if self.driver is None:
                logger.error("Не удалось инициализировать драйвер после нескольких попыток")
            else:
                # Пытаемся авторизоваться, если указаны данные аккаунта
                if self.google_account and not self.is_logged_in:
                    self.login_to_google()
        
        except Exception as e:
            logger.error(f"Критическая ошибка при настройке драйвера: {e}")
            traceback.print_exc()
            self.driver = None
        
    def _handle_proxy_auth(self) -> None:
        """
        Обрабатывает аутентификацию прокси через Chrome DevTools Protocol.
        """
        if not self.current_proxy:
            logger.warning("Прокси не задан, пропускаем аутентификацию")
            return
        
        username = self.current_proxy.get("username")
        password = self.current_proxy.get("password")
        
        if not username or not password:
            logger.warning("Логин или пароль прокси не указаны, пропускаем аутентификацию")
            return
        
        try:
            logger.info(f"Настройка аутентификации прокси через CDP")
            
            # Использование Chrome DevTools Protocol для настройки аутентификации
            self.driver.execute_cdp_cmd("Network.enable", {})
            
            self.driver.execute_cdp_cmd("Network.setExtraHTTPHeaders", {
                "headers": {
                    "Proxy-Authorization": f"Basic {base64.b64encode(f'{username}:{password}'.encode()).decode()}"
                }
            })
            
            # Настройка аутентификации для всех типов запросов
            self.driver.execute_cdp_cmd("Network.setRequestInterception", {
                "patterns": [{"urlPattern": "*"}]
            })
            
            def interceptor(request):
                # Добавляем базовую аутентификацию к каждому запросу
                headers = request.get("headers", {})
                headers["Proxy-Authorization"] = f"Basic {base64.b64encode(f'{username}:{password}'.encode()).decode()}"
                request["headers"] = headers
                
                return request
            
            # Регистрируем интерсептор для запросов
            self.driver.request_interceptor = interceptor
            
            logger.info("Аутентификация прокси через CDP настроена успешно")
        except Exception as e:
            logger.error(f"Ошибка при настройке аутентификации прокси через CDP: {e}")
    
    def quit_driver(self) -> None:
        """
        Закрытие WebDriver.
        """
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.error(f"Ошибка при закрытии WebDriver: {e}")
            finally:
                self.driver = None
                
    def _random_sleep(self, min_seconds: float = 1.0, max_seconds: float = 3.0) -> None:
        """
        Случайная задержка для имитации поведения пользователя.
        
        Args:
            min_seconds (float): Минимальное время задержки в секундах.
            max_seconds (float): Максимальное время задержки в секундах.
        """
        # Сокращаем время задержек значительно
        delay = random.uniform(min_seconds, max_seconds)
        time.sleep(delay)
                
    def get_last_videos_from_channel(self, channel_url: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Получает последние видео с канала YouTube.
        
        Args:
            channel_url (str): URL канала YouTube.
            limit (int): Максимальное количество видео для получения.
            
        Returns:
            List[Dict[str, Any]]: Список видео с информацией.
        """
        videos = []
        
        # Проверяем, инициализирован ли драйвер
        if self.driver is None:
            try:
                logger.info("Драйвер не инициализирован, пытаемся инициализировать в get_last_videos_from_channel")
                self.setup_driver()
                # Проверяем еще раз после инициализации
                if self.driver is None:
                    logger.error("Не удалось инициализировать драйвер в get_last_videos_from_channel")
                    return []
            except Exception as e:
                logger.error(f"Ошибка при инициализации драйвера в get_last_videos_from_channel: {e}")
                traceback.print_exc()
                return []
        
        try:
            # Преобразуем URL канала на страницу видео канала
            if "/videos" not in channel_url:
                if channel_url.endswith("/"):
                    videos_url = f"{channel_url}videos"
                else:
                    videos_url = f"{channel_url}/videos"
            else:
                videos_url = channel_url
                
            logger.info(f"Загружаем страницу видео канала: {videos_url}")
            self.driver.get(videos_url)
            
            # Увеличиваем время ожидания загрузки страницы
            self._random_sleep(4.0, 6.0)
            
            # Принимаем cookies, если есть такое окно
            try:
                accept_button = self.driver.find_element(By.XPATH, "//button[contains(., 'Принять все') or contains(., 'Accept all')]")
                accept_button.click()
                self._random_sleep(0.5, 1.0)  # Сокращаем с 1.0-2.0 до 0.5-1.0
            except:
                pass
            
            # Прокрутка для загрузки видео (сокращаем количество прокруток с 5 до 3)
            for i in range(3):
                self._scroll_page(1)
                logger.info(f"Прокрутка #{i+1} страницы канала {videos_url}")
                self._random_sleep(0.5, 1.0)  # Сокращаем с 1.0-2.0 до 0.5-1.0
            
            # Проверяем разные варианты селекторов видео
            selectors = [
                "ytd-grid-video-renderer",
                "ytd-rich-item-renderer",
                "#content ytd-rich-grid-row"
            ]
            
            video_elements = []
            for selector in selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        logger.info(f"Найдено {len(elements)} элементов видео по селектору '{selector}'")
                        video_elements = elements
                        break
                except Exception as e:
                    logger.warning(f"Ошибка при поиске элементов по селектору '{selector}': {e}")
            
            if not video_elements:
                # Если все селекторы не сработали, пробуем получить ссылки напрямую
                logger.info("Пробуем получить ссылки на видео напрямую")
                video_links = self.driver.find_elements(By.XPATH, "//a[@id='video-title' or contains(@class, 'ytd-thumbnail')]")
                
                for idx, link in enumerate(video_links[:limit]):
                    try:
                        video_url = link.get_attribute("href")
                        title = link.get_attribute("title") or link.get_attribute("aria-label") or f"Видео {idx+1}"
                        
                        if video_url and "watch?v=" in video_url:
                            videos.append({
                                "title": title,
                                "url": video_url,
                                "source": "channel",
                                "origin": channel_url
                            })
                    except Exception as e:
                        logger.warning(f"Ошибка при получении данных ссылки #{idx+1}: {e}")
            else:
                # Обрабатываем найденные элементы видео
                for idx, video_element in enumerate(video_elements[:limit]):
                    try:
                        # Ищем ссылку на видео внутри элемента
                        video_link_element = None
                        try:
                            video_link_element = video_element.find_element(By.CSS_SELECTOR, "a#video-title")
                        except:
                            # Если не нашли по первому селектору, пробуем другие
                            try:
                                video_link_element = video_element.find_element(By.XPATH, ".//a[contains(@href, '/watch?v=')]")
                            except:
                                # Пробуем найти любую ссылку, содержащую watch?v=
                                links = video_element.find_elements(By.TAG_NAME, "a")
                                for link in links:
                                    href = link.get_attribute("href")
                                    if href and "watch?v=" in href:
                                        video_link_element = link
                                        break
                        
                        if not video_link_element:
                            logger.warning(f"Не удалось найти ссылку для видео #{idx+1}")
                            continue
                        
                        video_url = video_link_element.get_attribute("href")
                        title = video_link_element.get_attribute("title") or video_link_element.get_attribute("aria-label")
                        
                        if not title:
                            # Если не смогли получить заголовок из атрибутов, пытаемся получить текст
                            title = video_link_element.text or f"Видео {idx+1}"
                        
                        # Добавляем информацию о видео
                        video_info = {
                            "title": title,
                            "url": video_url,
                            "source": "channel",
                            "origin": channel_url
                        }
                        
                        videos.append(video_info)
                        
                    except (NoSuchElementException, StaleElementReferenceException) as e:
                        logger.warning(f"Не удалось получить данные для видео #{idx+1}: {e}")
                        continue
            
            # Если все равно не нашли видео, проверяем, не заблокирован ли доступ
            if not videos:
                page_source = self.driver.page_source.lower()
                if "robot" in page_source or "captcha" in page_source:
                    logger.error(f"Возможно, доступ к каналу {channel_url} заблокирован (обнаружена CAPTCHA)")
                    # Делаем скриншот для отладки
                    try:
                        self.driver.save_screenshot("captcha_detected.png")
                    except:
                        pass
                        
                logger.info(f"Сохраняем HTML страницы канала для отладки")
                try:
                    with open("channel_page.html", "w", encoding="utf-8") as f:
                        f.write(self.driver.page_source)
                except:
                    pass
            
            logger.info(f"Найдено {len(videos)} видео на канале {channel_url}")
            
        except Exception as e:
            logger.error(f"Ошибка при получении видео с канала {channel_url}: {e}")
            traceback.print_exc()
            
        return videos
        
    def get_video_details(self, video_url: str) -> Dict[str, Any]:
        """
        Получает подробную информацию о видео.
        
        Args:
            video_url (str): URL видео.
            
        Returns:
            Dict[str, Any]: Информация о видео.
        """
        # Проверяем, инициализирован ли драйвер
        if self.driver is None:
            try:
                logger.info("Драйвер не инициализирован, пытаемся инициализировать в get_video_details")
                self.setup_driver()
                # Проверяем еще раз после инициализации
                if self.driver is None:
                    logger.error("Не удалось инициализировать драйвер в get_video_details")
                    return {}
            except Exception as e:
                logger.error(f"Ошибка при инициализации драйвера в get_video_details: {e}")
                return {}
        
        video_info = {}
        
        try:
            logger.info(f"Загружаем страницу видео: {video_url}")
            
            # Устанавливаем оптимальный таймаут для загрузки страницы (15 секунд вместо 30)
            self.driver.set_page_load_timeout(15)
            
            # Загружаем страницу видео
            self.driver.get(video_url)
            
            # Останавливаем воспроизведение видео для экономии ресурсов
            try:
                self.driver.execute_script("""
                    // Останавливаем видео, если оно есть
                    var video = document.querySelector('video');
                    if (video) {
                        video.pause();
                        video.currentTime = 0;
                        video.volume = 0;
                    }
                """)
            except:
                pass
            
            # Даем время загрузиться основным элементам страницы (сокращаем с 2.0-3.0 до 1.0-1.5)
            self._random_sleep(1.0, 1.5)
            
            # Ждем загрузки информации о видео с уменьшенным таймаутом (10 секунд вместо 15)
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//h1[@class='title style-scope ytd-video-primary-info-renderer']"))
                )
            except TimeoutException:
                logger.warning(f"Таймаут при ожидании загрузки информации о видео: {video_url}")
                
            # Извлекаем данные
            video_info = self._extract_video_details(self.driver.find_element(By.TAG_NAME, "body"))
            video_info["url"] = video_url
            
            # Логируем успешное получение данных
            logger.info(f"Успешно получены данные о видео: {video_url}")
            
            return video_info
        
        except Exception as e:
            logger.error(f"Ошибка при получении информации о видео {video_url}: {e}")
            return {"url": video_url}
        
    def get_recommended_videos(self, video_url: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Получает список рекомендованных видео для заданного видео.
        
        Args:
            video_url (str): URL видео.
            limit (int): Максимальное количество рекомендованных видео для получения.
            
        Returns:
            List[Dict[str, Any]]: Список рекомендованных видео.
        """
        recommendations = []
        
        # Проверяем, инициализирован ли драйвер
        if self.driver is None:
            try:
                logger.info("Драйвер не инициализирован, пытаемся инициализировать в get_recommended_videos")
                self.setup_driver()
                # Проверяем еще раз после инициализации
                if self.driver is None:
                    logger.error("Не удалось инициализировать драйвер в get_recommended_videos")
                    return []
            except Exception as e:
                logger.error(f"Ошибка при инициализации драйвера в get_recommended_videos: {e}")
                return []
        
        try:
            logger.info(f"Загружаем страницу видео для получения рекомендаций: {video_url}")
            start_time = time.time()
            
            # Пробуем загрузить страницу несколько раз при необходимости
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    self.driver.get(video_url)
                    logger.info(f"Загрузка страницы заняла {time.time() - start_time:.2f} сек")
                    break
                except Exception as e:
                    logger.warning(f"Попытка {attempt+1}/{max_attempts} загрузки страницы не удалась: {e}")
                    if attempt == max_attempts - 1:
                        raise
                    time.sleep(2)
            
            # Останавливаем воспроизведение видео для экономии ресурсов
            try:
                video_pause_start = time.time()
                self.driver.execute_script("""
                    // Останавливаем видео, если оно есть
                    var video = document.querySelector('video');
                    if (video) {
                        video.pause();
                        video.currentTime = 0;
                        video.volume = 0;
                    }
                """)
                logger.info(f"Пауза видео заняла {time.time() - video_pause_start:.2f} сек")
            except:
                pass
            
            # Даем время для загрузки рекомендаций (сокращаем с 3.0-5.0 до 1.5-2.0)
            wait_start = time.time()
            self._random_sleep(1.5, 2.0)
            logger.info(f"Ожидание загрузки рекомендаций заняло {time.time() - wait_start:.2f} сек")
            
            # Ждем появления контейнера с рекомендациями
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "#related, #secondary, ytd-watch-next-secondary-results-renderer"))
                )
                logger.info("Контейнер с рекомендациями найден")
            except TimeoutException:
                logger.warning("Таймаут при ожидании контейнера с рекомендациями")
            
            # Прокручиваем страницу, чтобы загрузить все рекомендации
            scroll_start = time.time()
            self._scroll_to_recommendations()
            logger.info(f"Прокрутка к рекомендациям заняла {time.time() - scroll_start:.2f} сек")
            
            # Пробуем разные селекторы для рекомендаций
            recommendation_selectors = [
                "#related #contents ytd-compact-video-renderer",
                "#secondary #items ytd-compact-video-renderer",
                "#related ytd-compact-video-renderer",
                "ytd-watch-next-secondary-results-renderer ytd-compact-video-renderer",
                "#secondary ytd-compact-video-renderer",
                "ytd-compact-video-renderer",
                "#items > ytd-compact-video-renderer"
            ]
            
            recommendation_elements = []
            
            # Пробуем каждый селектор
            find_start = time.time()
            for selector in recommendation_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        logger.info(f"Найдены рекомендации с помощью селектора: {selector} ({len(elements)} шт.)")
                        recommendation_elements = elements
                        break
                except Exception as e:
                    logger.warning(f"Не удалось найти рекомендации с помощью селектора {selector}: {e}")
            
            # Если не нашли рекомендации по селекторам, пробуем через XPath
            if not recommendation_elements:
                try:
                    xpath_selectors = [
                        "//div[@id='related']//ytd-compact-video-renderer",
                        "//div[@id='secondary']//ytd-compact-video-renderer",
                        "//ytd-watch-next-secondary-results-renderer//ytd-compact-video-renderer",
                        "//ytd-compact-video-renderer"
                    ]
                    
                    for xpath in xpath_selectors:
                        elements = self.driver.find_elements(By.XPATH, xpath)
                        if elements:
                            logger.info(f"Найдены рекомендации с помощью XPath: {xpath} ({len(elements)} шт.)")
                            recommendation_elements = elements
                            break
                except Exception as e:
                    logger.warning(f"Не удалось найти рекомендации с помощью XPath: {e}")
            
            logger.info(f"Поиск рекомендаций занял {time.time() - find_start:.2f} сек")
            
            # Если всё ещё не нашли, пытаемся извлечь ссылки напрямую из HTML
            if not recommendation_elements:
                logger.warning("Не удалось найти рекомендации через селекторы, пробуем анализировать HTML")
                try:
                    html_start = time.time()
                    html = self.driver.page_source
                    
                    # Ищем все URL видео на странице (шаблон для рекомендаций)
                    video_urls = re.findall(r'href=\"(/watch\?v=[^\"&]+)', html)
                    video_urls = list(set(video_urls))  # Удаляем дубликаты
                    
                    if video_urls:
                        logger.info(f"Найдено {len(video_urls)} потенциальных рекомендаций через HTML-анализ")
                        
                        # Берем только уникальные URL и не больше лимита
                        seen_urls = set()
                        for url_path in video_urls[:limit*2]: # Берем в два раза больше, чтобы после фильтрации осталось достаточно
                            full_url = f"https://www.youtube.com{url_path}"
                            
                            # Пропускаем текущее видео и дубликаты
                            if full_url == video_url or full_url in seen_urls:
                                continue
                                
                            seen_urls.add(full_url)
                            recommendations.append({"url": full_url})
                            
                        logger.info(f"Добавлено {len(recommendations)} рекомендаций через HTML-анализ за {time.time() - html_start:.2f} сек")
                        return recommendations[:limit]
                except Exception as e:
                    logger.error(f"Ошибка при анализе HTML для рекомендаций: {e}")
            
            # Обрабатываем найденные элементы
            process_start = time.time()
            if recommendation_elements:
                for idx, element in enumerate(recommendation_elements[:limit]):
                    try:
                        # Ищем ссылку внутри элемента
                        link = None
                        
                        # Пробуем найти ссылку разными способами
                        try:
                            link = element.find_element(By.CSS_SELECTOR, "a#thumbnail")
                        except:
                            try:
                                link = element.find_element(By.TAG_NAME, "a")
                            except:
                                try:
                                    link = element.find_element(By.XPATH, ".//a[contains(@href, '/watch?v=')]")
                                except:
                                    logger.warning(f"Не удалось найти ссылку для рекомендации #{idx+1}")
                                    continue
                        
                        # Получаем URL рекомендации
                        rec_url = link.get_attribute("href")
                        
                        if not rec_url:
                            logger.warning(f"Пустой URL для рекомендации #{idx+1}")
                            continue
                        
                        # Пропускаем плейлисты и прямые эфиры
                        if "list=" in rec_url or "live" in rec_url:
                            continue
                        
                        # Получаем заголовок (необязательно)
                        title = None
                        try:
                            title_element = element.find_element(By.ID, "video-title")
                            title = title_element.get_attribute("title") or title_element.text
                        except:
                            pass
                        
                        recommendation = {"url": rec_url}
                        if title:
                            recommendation["title"] = title
                        
                        recommendations.append(recommendation)
                        
                    except Exception as e:
                        logger.warning(f"Ошибка при обработке рекомендации #{idx+1}: {e}")
                        continue
                
                logger.info(f"Обработка {len(recommendation_elements)} элементов заняла {time.time() - process_start:.2f} сек")
                logger.info(f"Получено {len(recommendations)} рекомендаций для видео {video_url}")
                
            else:
                logger.warning(f"Не найдены элементы с рекомендациями для видео {video_url}")
                
                # Делаем скриншот для отладки, если не нашли рекомендации
                try:
                    self.driver.save_screenshot("recommendations_page.png")
                    logger.info("Сохранен скриншот страницы рекомендаций")
                except Exception as e:
                    logger.warning(f"Не удалось сохранить скриншот: {e}")
            
            # Логируем общее время выполнения метода
            total_time = time.time() - start_time
            logger.info(f"Общее время получения рекомендаций для {video_url}: {total_time:.2f} сек")
            
            return recommendations
        
        except Exception as e:
            logger.error(f"Ошибка при получении рекомендаций для видео {video_url}: {e}")
            traceback.print_exc()
            return []

    def _scroll_to_recommendations(self) -> None:
        """
        Прокручивает страницу для полной загрузки рекомендаций.
        """
        try:
            # Прокрутка вниз, чтобы загрузить рекомендации
            self.driver.execute_script("window.scrollBy(0, 500);")
            time.sleep(1)
            
            # Найдем секцию с рекомендациями и прокрутим к ней
            try:
                recommendations_section = self.driver.find_element(By.ID, "related")
                self.driver.execute_script("arguments[0].scrollIntoView();", recommendations_section)
                time.sleep(1)
            except:
                # Если не нашли по ID, просто прокрутим еще немного
                self.driver.execute_script("window.scrollBy(0, 700);")
                time.sleep(1)
                
            # Дополнительная прокрутка для загрузки всех рекомендаций
            self.driver.execute_script("window.scrollBy(0, 500);")
            time.sleep(1)
        except Exception as e:
            logger.warning(f"Ошибка при прокрутке к рекомендациям: {e}")

    def download_thumbnail(self, thumbnail_url: str) -> Optional[Image.Image]:
        """
        Загружает миниатюру видео.
        
        Args:
            thumbnail_url (str): URL миниатюры.
            
        Returns:
            Optional[Image.Image]: Объект изображения или None в случае ошибки.
        """
        try:
            if not thumbnail_url:
                return None
                
            # Используем прокси, если настроен
            proxies = None
            if self.use_proxy and self.current_proxy:
                proxies = {
                    "http": self.current_proxy["http"],
                    "https": self.current_proxy["https"]
                }
                
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            
            response = requests.get(
                thumbnail_url, 
                headers=headers, 
                proxies=proxies, 
                timeout=10
            )
            
            if response.status_code == 200:
                img = Image.open(BytesIO(response.content))
                return img
            else:
                logger.warning(f"Не удалось загрузить миниатюру. Код статуса: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Ошибка при загрузке миниатюры {thumbnail_url}: {e}")
            return None
        
    def _scroll_page(self, num_scrolls: int = 3) -> None:
        """
        Прокручивает страницу для загрузки контента.
        
        Args:
            num_scrolls (int): Количество прокруток.
        """
        try:
            for _ in range(num_scrolls):
                self.driver.execute_script("window.scrollBy(0, 1000);")
                self._random_sleep(1.0, 2.0)
        except Exception as e:
            logger.error(f"Ошибка при прокрутке страницы: {e}")
            
    def _parse_publication_date(self, date_text: str) -> Optional[datetime]:
        """
        Парсит дату публикации из текста.
        
        Args:
            date_text (str): Текст с датой публикации.
            
        Returns:
            Optional[datetime]: Объект datetime с датой публикации или None, если не удалось распарсить.
        """
        if not date_text:
            return None
            
        try:
            # Обработка формата "Premiered ... ago"
            date_text = date_text.strip()
            logger.debug(f"Попытка разобрать дату из текста: '{date_text}'")
            
            # Предварительная обработка текста для удаления лишних символов и приведения к стандартному виду
            clean_text = date_text.lower()
            clean_text = re.sub(r'\s+', ' ', clean_text)  # Заменяем множественные пробелы на один
            
            # ОБРАБОТКА ОТНОСИТЕЛЬНЫХ ДАТ (ago/назад)
            relative_patterns = [
                # Часы (English & Russian)
                (r'(\d+)\s*(?:hour|час)[а-я]*\s*(?:ago|назад)', lambda x: datetime.now() - timedelta(hours=int(x))),
                # Дни (English & Russian)
                (r'(\d+)\s*(?:day|день|дня|дней)\s*(?:ago|назад)', lambda x: datetime.now() - timedelta(days=int(x))),
                # Недели (English & Russian)
                (r'(\d+)\s*(?:week|недел)[а-я]*\s*(?:ago|назад)', lambda x: datetime.now() - timedelta(weeks=int(x))),
                # Месяцы (English & Russian)
                (r'(\d+)\s*(?:month|месяц|месяца|месяцев)\s*(?:ago|назад)', lambda x: datetime.now() - timedelta(days=int(x)*30)),
                # Годы (English & Russian)
                (r'(\d+)\s*(?:year|год|года|лет)\s*(?:ago|назад)', lambda x: datetime.now() - timedelta(days=int(x)*365)),
                # Одна единица времени (hours ago, hour ago)
                (r'(?:an|a|один|одна)\s*(?:hour|day|week|month|year|час|день|недел|месяц|год)[а-я]*\s*(?:ago|назад)', 
                 lambda x: datetime.now() - timedelta(hours=1) if 'hour' in x.lower() or 'час' in x.lower() else
                           datetime.now() - timedelta(days=1) if 'day' in x.lower() or 'день' in x.lower() else
                           datetime.now() - timedelta(weeks=1) if 'week' in x.lower() or 'недел' in x.lower() else
                           datetime.now() - timedelta(days=30) if 'month' in x.lower() or 'месяц' in x.lower() else
                           datetime.now() - timedelta(days=365))
            ]
            
            for pattern, time_func in relative_patterns:
                match = re.search(pattern, clean_text, re.IGNORECASE)
                if match:
                    if len(match.groups()) > 0:
                        value = match.group(1)
                        return time_func(value)
                    else:
                        return time_func(clean_text)
            
            # ОБРАБОТКА АБСОЛЮТНЫХ ДАТ
            
            # Обработка "стандартных" форматов (месяц день, год)
            # Английские месяцы
            english_months = {
                'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
                'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6,
                'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12
            }
            
            # Русские месяцы
            russian_months = {
                'янв': 1, 'фев': 2, 'мар': 3, 'апр': 4, 'май': 5, 'июн': 6,
                'июл': 7, 'авг': 8, 'сен': 9, 'окт': 10, 'ноя': 11, 'дек': 12,
                'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5, 'июня': 6,
                'июля': 7, 'августа': 8, 'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
            }
            
            # Проверяем наличие месяцев в тексте напрямую
            month_found = None
            month_value = None
            
            for month_name, month_num in {**english_months, **russian_months}.items():
                if month_name in clean_text:
                    month_found = month_name
                    month_value = month_num
                    break
            
            if month_found:
                # Ищем день и год рядом с месяцем
                day_match = re.search(r'(\d{1,2})[^\d]' + month_found, clean_text) or re.search(month_found + r'[^\d](\d{1,2})', clean_text)
                year_match = re.search(r'(\d{4})', clean_text)
                
                if day_match and year_match:
                    try:
                        day = int(day_match.group(1))
                        year = int(year_match.group(1))
                        return datetime(year, month_value, day)
                    except ValueError:
                        pass
            
            # Форматы даты с разделителями
            date_patterns = [
                # ISO 8601: YYYY-MM-DD
                (r'(\d{4})-(\d{1,2})-(\d{1,2})', lambda y, m, d: datetime(int(y), int(m), int(d))),
                # DD.MM.YYYY
                (r'(\d{1,2})\.(\d{1,2})\.(\d{4})', lambda d, m, y: datetime(int(y), int(m), int(d))),
                # MM/DD/YYYY или DD/MM/YYYY (пробуем оба)
                (r'(\d{1,2})/(\d{1,2})/(\d{4})', lambda a, b, y: try_date_formats(a, b, y)),
                # DD-MM-YYYY
                (r'(\d{1,2})-(\d{1,2})-(\d{4})', lambda d, m, y: datetime(int(y), int(m), int(d))),
            ]
            
            def try_date_formats(a, b, y):
                """Пробует разные форматы даты MM/DD/YYYY и DD/MM/YYYY"""
                try:
                    # Сначала MM/DD/YYYY
                    return datetime(int(y), int(a), int(b))
                except ValueError:
                    try:
                        # Затем DD/MM/YYYY
                        return datetime(int(y), int(b), int(a))
                    except ValueError:
                        return None
            
            for pattern, date_func in date_patterns:
                match = re.search(pattern, clean_text)
                if match:
                    try:
                        result = date_func(*match.groups())
                        if result:
                            return result
                    except ValueError:
                        continue
            
            # Другие специальные форматы
            # Например, "Published on XXX" или "Premiered XXX"
            published_patterns = [
                r'(?:published|premiered|streamed|опубликовано|трансляция)(?:\s+on)?\s+(.*)',
                r'(?:вышло|стрим|эфир|вышла)\s+(.*)'
            ]
            
            for pattern in published_patterns:
                published_match = re.search(pattern, clean_text, re.IGNORECASE)
                if published_match:
                    # Рекурсивно обрабатываем часть после маркера публикации
                    return self._parse_publication_date(published_match.group(1))
            
            # Если ни один из форматов не подошел, ищем любые упоминания дат в тексте
            # Например, сначала цифры, потом "ago/назад"
            any_date_match = re.search(r'(\d+)\s*\w+\s*(?:ago|назад)', clean_text)
            if any_date_match:
                # Просто используем текущее число, как приблизительное
                num = int(any_date_match.group(1))
                # Если число похоже на день месяца (1-31), предполагаем дни
                if 1 <= num <= 31:
                    return datetime.now() - timedelta(days=num)
                # Если похоже на час (до 24), предполагаем часы
                elif 1 <= num <= 24:
                    return datetime.now() - timedelta(hours=num)
                # Иначе для больших чисел предполагаем какой-то тип единиц
                else:
                    # По умолчанию предполагаем дни
                    return datetime.now() - timedelta(days=min(num, 365*5))  # ограничиваем 5 годами
            
            # Если ни один из методов не сработал
            logger.debug(f"Не удалось разобрать дату из текста: '{date_text}'")
            return None
            
        except Exception as e:
            logger.error(f"Ошибка при разборе даты из текста '{date_text}': {e}")
            return None

    def _extract_channel_name(self, channel_url: str) -> Optional[str]:
        """
        Извлекает имя канала из URL или со страницы канала.
        
        Args:
            channel_url (str): URL канала YouTube.
            
        Returns:
            Optional[str]: Имя канала или None, если не удалось извлечь.
        """
        try:
            # Пытаемся извлечь имя канала из URL
            if "@" in channel_url:
                # Формат URL с именем канала: https://www.youtube.com/@channelname
                channel_parts = channel_url.split("@")
                if len(channel_parts) > 1:
                    channel_name = channel_parts[1].split("/")[0].strip()
                    if channel_name:
                        logger.info(f"Извлечено имя канала из URL: {channel_name}")
                        return channel_name
            
            # Если не удалось извлечь из URL, пытаемся загрузить страницу и получить имя канала
            if self.driver is None:
                logger.warning("Драйвер не инициализирован, не можем получить имя канала со страницы")
                return None
                
            logger.info(f"Загружаем страницу канала для извлечения имени: {channel_url}")
            
            # Загружаем страницу канала
            self.driver.get(channel_url)
            self._random_sleep(3.0, 5.0)
            
            # Пытаемся найти имя канала разными способами
            selectors = [
                "yt-formatted-string.ytd-channel-name",
                "#channel-name yt-formatted-string",
                "#channel-header-container h1",
                "#channel-title",
                "#channel-name"
            ]
            
            for selector in selectors:
                try:
                    name_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    channel_name = name_element.text.strip()
                    if channel_name:
                        logger.info(f"Извлечено имя канала со страницы: {channel_name}")
                        return channel_name
                except (NoSuchElementException, StaleElementReferenceException):
                    continue
            
            # Если не нашли через селекторы, попробуем через XPath
            xpath_selectors = [
                "//div[contains(@id, 'channel-name')]//yt-formatted-string",
                "//div[contains(@id, 'channel-header')]//h1",
                "//h1[contains(@class, 'title')]"
            ]
            
            for xpath in xpath_selectors:
                try:
                    name_element = self.driver.find_element(By.XPATH, xpath)
                    channel_name = name_element.text.strip()
                    if channel_name:
                        logger.info(f"Извлечено имя канала через XPath: {channel_name}")
                        return channel_name
                except (NoSuchElementException, StaleElementReferenceException):
                    continue
                    
            # Если все методы не сработали, возвращаем None
            logger.warning(f"Не удалось извлечь имя канала для {channel_url}")
            return None
            
        except Exception as e:
            logger.error(f"Ошибка при извлечении имени канала для {channel_url}: {e}")
            traceback.print_exc()
            return None

    def _get_channel_videos_api(self, channel_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Получает список видео с канала YouTube через HTML-парсинг без использования полного API.
        
        Args:
            channel_id (str): ID канала YouTube
            limit (int): Максимальное количество видео для получения
        
        Returns:
            List[Dict[str, Any]]: Список видео с канала
        """
        videos = []
        
        try:
            # Формируем URL канала
            if channel_id.startswith('@'):
                channel_url = f"https://www.youtube.com/{channel_id}/videos"
            else:
                channel_url = f"https://www.youtube.com/@{channel_id}/videos"
            
            logger.info(f"Загружаем страницу канала через API-метод: {channel_url}")
            
            # Используем requests для быстрой загрузки страницы
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
            }
            
            response = requests.get(channel_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                html = response.text
                
                # Ищем все URL видео на странице
                video_urls = re.findall(r'href=\"(/watch\?v=[^\"&]+)', html)
                video_urls = list(set(video_urls))  # Удаляем дубликаты
                
                if video_urls:
                    logger.info(f"Найдено {len(video_urls)} видео через API-метод")
                    
                    # Берем только нужное количество видео
                    for url_path in video_urls[:limit]:
                        full_url = f"https://www.youtube.com{url_path}"
                        videos.append({"url": full_url})
                    
                    return videos
                else:
                    logger.warning("Не найдено видео через API-метод")
                    
            else:
                logger.warning(f"Не удалось загрузить страницу канала. Код: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Ошибка при получении видео через API: {e}")
            
        return videos

    def _extract_video_details(self, element: WebElement) -> Dict[str, Any]:
        """
        Извлекает данные о видео из элемента страницы.
        
        Args:
            element (WebElement): Элемент страницы, содержащий данные о видео.
        
        Returns:
            Dict[str, Any]: Словарь с данными о видео.
        """
        video_info = {}
        
        try:
            # Извлекаем заголовок видео - пробуем разные селекторы для надёжности
            title_selectors = [
                "h1.title.style-scope.ytd-video-primary-info-renderer",
                "h1.ytd-video-primary-info-renderer",
                "h1.title",
                "#container h1",
                "#title h1",
                "#title"
            ]
            
            title = None
            for selector in title_selectors:
                try:
                    title_element = element.find_element(By.CSS_SELECTOR, selector)
                    title = title_element.text.strip()
                    if title:
                        logger.info(f"Найден заголовок с селектором {selector}: {title[:50]}...")
                        break
                except (NoSuchElementException, StaleElementReferenceException):
                    continue
            
            # Если CSS селекторы не сработали, пробуем XPath
            if not title:
                logger.warning("Не удалось найти заголовок через CSS селекторы, пробуем XPath")
                xpath_selectors = [
                    "//h1[contains(@class, 'title')]",
                    "//h1",
                    "//*[@id='title']/h1",
                    "//*[@id='title']"
                ]
                for xpath in xpath_selectors:
                    try:
                        title_element = element.find_element(By.XPATH, xpath)
                        title = title_element.text.strip()
                        if title:
                            logger.info(f"Найден заголовок с XPath {xpath}: {title[:50]}...")
                            break
                    except (NoSuchElementException, StaleElementReferenceException):
                        continue
            
            # Если все селекторы не сработали, берем title из head
            if not title:
                logger.warning("Не удалось найти заголовок через DOM, извлекаем из title страницы")
                try:
                    page_title = self.driver.title
                    if page_title and " - YouTube" in page_title:
                        title = page_title.replace(" - YouTube", "")
                        logger.info(f"Извлечен заголовок из title страницы: {title[:50]}...")
                except Exception as e:
                    logger.warning(f"Не удалось извлечь заголовок из title: {e}")
            
            # Если все методы не сработали, сохраняем HTML для диагностики
            if not title:
                logger.warning("Не удалось найти элемент заголовка видео")
                try:
                    # Сохраняем часть HTML для отладки
                    html_snippet = element.get_attribute("innerHTML")[:1000]
                    logger.debug(f"HTML фрагмент: {html_snippet}")
                except Exception as e:
                    logger.warning(f"Не удалось получить HTML для диагностики: {e}")
                
                # Используем URL как запасной вариант заголовка
                video_id = "unknown"
                if "url" in video_info and "watch?v=" in video_info["url"]:
                    video_id = video_info["url"].split("watch?v=")[1].split("&")[0]
                title = f"Видео {video_id}"
            
            video_info["title"] = title
            
            # Извлекаем количество просмотров - пробуем разные селекторы для надёжности
            views_selectors = [
                ".view-count",
                "#count .view-count",
                "#info .view-count",
                "span.view-count",
                "#info-text .view-count",
                ".ytd-video-view-count-renderer",
                "#info-strings yt-formatted-string",
                "#info ytd-video-view-count-renderer"
            ]
            
            views = None
            for selector in views_selectors:
                try:
                    views_element = element.find_element(By.CSS_SELECTOR, selector)
                    views_text = views_element.text.strip()
                    if views_text:
                        logger.info(f"Найдено количество просмотров: {views_text}")
                        # Извлекаем число просмотров из текста
                        # Ищем все цифры с возможными разделителями (пробел, запятая, точка)
                        views_match = re.search(r'([\d\s.,]+)', views_text)
                        if views_match:
                            # Извлекаем найденную группу и очищаем от символов
                            views_str = views_match.group(1).strip()
                            # Удаляем все нецифровые символы, кроме последней точки или запятой (может быть десятичным разделителем)
                            views_clean = re.sub(r'[^\d]', '', views_str)
                            try:
                                views = int(views_clean)
                                break
                            except ValueError:
                                pass
                except (NoSuchElementException, StaleElementReferenceException):
                    continue
            
            # Если селекторы не сработали, пробуем XPath с улучшенными селекторами
            if views is None:
                xpath_selectors = [
                    "//span[contains(@class, 'view-count')]",
                    "//span[contains(text(), 'просмотр')]",
                    "//span[contains(text(), 'view')]",
                    "//*[contains(@class, 'ytd-video-view-count-renderer')]",
                    "//ytd-video-view-count-renderer",
                    "//*[contains(text(), 'просмотр') or contains(text(), 'view')]"
                ]
                
                for xpath in xpath_selectors:
                    try:
                        views_element = element.find_element(By.XPATH, xpath)
                        views_text = views_element.text.strip()
                        if views_text:
                            # Пытаемся извлечь число просмотров с более гибким поиском
                            views_match = re.search(r'([\d\s.,]+)', views_text)
                            if views_match:
                                views_str = views_match.group(1).strip()
                                # Удаляем все нецифровые символы
                                views_clean = re.sub(r'[^\d]', '', views_str)
                                try:
                                    views = int(views_clean)
                                    break
                                except ValueError:
                                    pass
                    except (NoSuchElementException, StaleElementReferenceException):
                        continue
            
            # Если все методы не сработали, пробуем через JavaScript
            if views is None:
                try:
                    views_js = self.driver.execute_script("""
                        // Попытка получить просмотры через элементы DOM
                        var viewElements = document.querySelectorAll('.view-count, [class*="view-count"], span[class*="ViewCount"]');
                        
                        for (var i = 0; i < viewElements.length; i++) {
                            var text = viewElements[i].textContent || viewElements[i].innerText;
                            if (text && /\\d/.test(text)) {
                                return text.trim();
                            }
                        }
                        
                        // Проверка текстов, содержащих упоминания просмотров
                        var allElements = document.querySelectorAll('*');
                        for (var i = 0; i < allElements.length; i++) {
                            var text = allElements[i].textContent || allElements[i].innerText;
                            if (text && (text.includes('просмотр') || text.includes('view')) && /\\d/.test(text)) {
                                return text.trim();
                            }
                        }
                        
                        return null;
                    """)
                    
                    if views_js:
                        logger.info(f"Найдено количество просмотров через JavaScript: {views_js}")
                        views_match = re.search(r'([\d\s.,]+)', views_js)
                        if views_match:
                            views_str = views_match.group(1).strip()
                            views_clean = re.sub(r'[^\d]', '', views_str)
                            try:
                                views = int(views_clean)
                            except ValueError:
                                pass
                except Exception as js_error:
                    logger.warning(f"Ошибка при получении просмотров через JavaScript: {js_error}")
            
            # Если все методы не сработали, используем значение по умолчанию
            if views is None:
                views = 0
            
            video_info["views"] = views
            
            # Извлекаем дату публикации - пробуем разные селекторы для надёжности
            date_selectors = [
                "#info-strings yt-formatted-string",
                "#info-strings span",
                "#upload-info .date",
                "#metadata-line span:nth-child(2)",
                "#metadata .date",
                ".ytd-video-primary-info-renderer .date"
            ]
            
            pub_date = None
            date_text = None
            
            for selector in date_selectors:
                try:
                    date_element = element.find_element(By.CSS_SELECTOR, selector)
                    date_text = date_element.text.strip()
                    if date_text:
                        logger.info(f"Найдена дата публикации: {date_text}")
                        pub_date = self._parse_publication_date(date_text)
                        if pub_date:
                            break
                except (NoSuchElementException, StaleElementReferenceException):
                    continue
            
            # Если селекторы не сработали, пробуем XPath
            if pub_date is None:
                xpath_selectors = [
                    "//span[contains(text(), 'Опубликовано')]",
                    "//span[contains(text(), 'Премьера')]",
                    "//span[contains(@class, 'date')]",
                    "//*[contains(text(), 'Premiered')]",
                    "//*[contains(text(), 'Published')]",
                    "//*[contains(text(), 'Streamed')]"
                ]
                
                for xpath in xpath_selectors:
                    try:
                        date_element = element.find_element(By.XPATH, xpath)
                        date_text = date_element.text.strip()
                        if date_text:
                            pub_date = self._parse_publication_date(date_text)
                            if pub_date:
                                break
                    except (NoSuchElementException, StaleElementReferenceException):
                        continue
            
            # Если все методы не сработали или не смогли распарсить дату, используем текущую дату
            if pub_date is None:
                pub_date = datetime.now()
                
            video_info["publication_date"] = pub_date
            
            # Извлекаем URL миниатюры
            try:
                if "url" in video_info and "watch?v=" in video_info["url"]:
                    video_id = video_info["url"].split("watch?v=")[1].split("&")[0]
                    video_info["thumbnail_url"] = f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
            except (KeyError, IndexError):
                # Если не удалось извлечь ID видео из URL
                pass
            
            # Пытаемся извлечь имя канала
            channel_selectors = [
                "#channel-name a",
                "#channel-name",
                ".ytd-channel-name a",
                "#owner-name a",
                "#owner a"
            ]
            
            channel_name = None
            for selector in channel_selectors:
                try:
                    channel_element = element.find_element(By.CSS_SELECTOR, selector)
                    channel_name = channel_element.text.strip()
                    if channel_name:
                        video_info["channel_name"] = channel_name
                        
                        # Также извлекаем URL канала
                        try:
                            video_info["channel_url"] = channel_element.get_attribute("href")
                        except:
                            pass
                        
                        break
                except (NoSuchElementException, StaleElementReferenceException):
                    continue
                
            # Извлекаем описание видео
            description_selectors = [
                "#description-inline-expander",
                "#description-inline-expander .content",
                "#description",
                ".ytd-expandable-video-description-body-renderer",
                "#meta-contents #description"
            ]
            
            description = None
            for selector in description_selectors:
                try:
                    description_element = element.find_element(By.CSS_SELECTOR, selector)
                    description = description_element.text.strip()
                    if description:
                        video_info["description"] = description
                        break
                except (NoSuchElementException, StaleElementReferenceException):
                    continue
            
            # Если нет описания, добавим пустую строку
            if "description" not in video_info:
                video_info["description"] = ""
            
            return video_info
        
        except Exception as e:
            logger.error(f"Ошибка при извлечении данных о видео: {e}")
            traceback.print_exc()
            # Возвращаем пустой словарь, если произошла ошибка
            return video_info

    def _find_with_delay(self, parent_element, by, selector, delay=0.5, retries=1):
        """
        Находит элемент с задержкой и повторными попытками.
        Улучшает надежность при работе с динамическим контентом.
        """
        for attempt in range(retries + 1):
            try:
                elements = parent_element.find_elements(by, selector)
                if elements:
                    return elements[0]
                elif attempt < retries:
                    time.sleep(delay)
            except Exception as e:
                if attempt < retries:
                    logger.debug(f"Попытка {attempt+1} найти {selector} не удалась: {e}")
                    time.sleep(delay)
                else:
                    logger.debug(f"Не удалось найти элемент {selector} после {retries+1} попыток")
        return None

    def process_channels(self, channel_urls, max_videos=5, sections=None):
        """
        Обрабатывает список каналов YouTube и собирает информацию о последних видео.
        
        Args:
            channel_urls (list): Список URL-адресов каналов YouTube
            max_videos (int): Максимальное количество видео для сбора с каждого канала
            sections (list, optional): Разделы для анализа (например, 'videos', 'shorts')
            
        Returns:
            dict: Словарь с результатами анализа каналов
        """
        if not channel_urls:
            logger.warning("Не предоставлены URL-адреса каналов для обработки")
            return {"success": False, "error": "Не предоставлены URL-адреса каналов"}
            
        if not sections:
            sections = ["videos"]  # По умолчанию только обычные видео
            
        results = {
            "success": True,
            "channels_processed": 0,
            "channels_failed": 0,
            "channels": []
        }
        
        total_channels = len(channel_urls)
        logger.info(f"Начинаю обработку {total_channels} каналов...")
        
        for index, channel_url in enumerate(channel_urls, 1):
            logger.info(f"Обработка канала [{index}/{total_channels}]: {channel_url}")
            
            try:
                # Проверяем, что драйвер активен, при необходимости переинициализируем
                if not self.driver:
                    logger.warning("Драйвер не инициализирован, переинициализация...")
                    self.setup_driver()
                    
                    if not self.driver:
                        logger.error("Не удалось инициализировать драйвер, пропускаем канал")
                        results["channels_failed"] += 1
                        continue
                
                # Получаем ID канала
                channel_id = self._extract_channel_id(channel_url)
                if not channel_id:
                    logger.warning(f"Не удалось извлечь ID канала из URL: {channel_url}")
                    channel_id = "unknown"
                
                channel_info = {
                    "url": channel_url,
                    "id": channel_id,
                    "name": None,
                    "sections_processed": 0,
                    "videos_found": 0,
                    "videos": []
                }
                
                # Обрабатываем каждую указанную секцию
                for section in sections:
                    try:
                        logger.info(f"Получение видео из раздела '{section}' для канала {channel_url}")
                        videos = self.get_last_videos_from_channel(channel_url, max_videos, section)
                        
                        if videos:
                            # Если имя канала еще не получено, берем из первого видео
                            if not channel_info["name"] and videos[0].get("channel_name"):
                                channel_info["name"] = videos[0]["channel_name"]
                                
                            channel_info["videos"].extend(videos)
                            channel_info["videos_found"] += len(videos)
                            channel_info["sections_processed"] += 1
                            
                            logger.info(f"Получено {len(videos)} видео из раздела '{section}'")
                        else:
                            logger.warning(f"Видео не найдены в разделе '{section}' для канала {channel_url}")
                            
                    except Exception as section_err:
                        logger.error(f"Ошибка при обработке раздела '{section}' для канала {channel_url}: {section_err}")
                        traceback.print_exc()
                
                # Если имя канала все еще не получено, попробуем получить его напрямую
                if not channel_info["name"]:
                    try:
                        self.driver.get(channel_url)
                        time.sleep(3)  # Даем время на загрузку страницы
                        channel_name_element = self._find_with_delay(self.driver, By.CSS_SELECTOR, 
                                                                   "#channel-name yt-formatted-string, #text.ytd-channel-name", 
                                                                   delay=1, retries=2)
                        if channel_name_element:
                            channel_info["name"] = channel_name_element.text.strip()
                    except Exception as name_err:
                        logger.warning(f"Не удалось получить имя канала: {name_err}")
                
                # Добавляем информацию о канале в результаты
                results["channels"].append(channel_info)
                results["channels_processed"] += 1
                
            except Exception as channel_err:
                logger.error(f"Ошибка при обработке канала {channel_url}: {channel_err}")
                traceback.print_exc()
                results["channels_failed"] += 1
                
                # Проверим состояние драйвера и при необходимости переинициализируем
                try:
                    if self.driver:
                        self.driver.current_url  # Проверка активности драйвера
                except Exception:
                    logger.warning("Драйвер перестал отвечать, переинициализация...")
                    self.close_driver()
                    self.setup_driver()
        
        # Обновляем статус успешности
        if results["channels_processed"] == 0 and total_channels > 0:
            results["success"] = False
            results["error"] = "Не удалось обработать ни один канал"
            
        logger.info(f"Обработка каналов завершена. Успешно: {results['channels_processed']}, Неудачно: {results['channels_failed']}")
        return results

    def get_channel_videos(self, channel_url: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Получает список видео с канала YouTube.
        
        Args:
            channel_url (str): URL канала YouTube
            limit (int): Максимальное количество видео для получения
        
        Returns:
            List[Dict[str, Any]]: Список видео с канала
        """
        videos = []
        
        # Проверяем, инициализирован ли драйвер
        if self.driver is None:
            try:
                logger.info("Драйвер не инициализирован, пытаемся инициализировать в get_channel_videos")
                self.setup_driver()
                # Проверяем еще раз после инициализации
                if self.driver is None:
                    logger.error("Не удалось инициализировать драйвер в get_channel_videos")
                    return []
            except Exception as e:
                logger.error(f"Ошибка при инициализации драйвера в get_channel_videos: {e}")
                return []
        
        channel_id = self._extract_channel_id(channel_url)
        if not channel_id:
            logger.error(f"Не удалось извлечь ID канала из URL: {channel_url}")
            return []
        
        logger.info(f"Извлечен ID канала из URL: {channel_id}")
        
        # Пробуем сначала через API (быстрее и надежнее)
        try:
            logger.info(f"Пробуем получить видео через API для канала {channel_id}")
            api_videos = self._get_channel_videos_api(channel_id, limit)
            if api_videos:
                logger.info(f"Успешно получены {len(api_videos)} видео через API для канала {channel_id}")
                return api_videos[:limit]
        except Exception as e:
            logger.warning(f"Не удалось получить видео через API: {e}")
        
        # Если через API не удалось, используем Selenium
        logger.info(f"Используем основной метод получения видео через Selenium")

        # Упрощенный подход - просто возьмем видео с главной страницы канала
        try:
            # Формируем URL канала
            if not channel_url.endswith('/videos'):
                if '@' in channel_url:
                    if channel_url.endswith('/'):
                        channel_url = channel_url + 'videos'
                    else:
                        channel_url = channel_url + '/videos'
                else:
                    # Если не указан @ и ни одна из форм, пробуем форматировать как стандартный URL
                    channel_url = f"https://www.youtube.com/@{channel_id}/videos"
            
            logger.info(f"Загружаем страницу канала: {channel_url}")
            
            # Загружаем страницу напрямую через requests сначала для проверки
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
                response = requests.get(channel_url, headers=headers, timeout=10)
                
                if response.status_code == 200:
                    # Извлекаем ссылки на видео из HTML
                    html = response.text
                    
                    # Ищем ссылки на видео в HTML
                    video_urls = re.findall(r'href=\"(/watch\?v=[^\"&]+)', html)
                    video_urls = list(set(video_urls))  # Удаляем дубликаты
                    
                    if video_urls:
                        logger.info(f"Найдено {len(video_urls)} видео через HTML-парсинг")
                        for url_path in video_urls[:limit]:
                            full_url = f"https://www.youtube.com{url_path}"
                            videos.append({"url": full_url})
                        
                        # Если нашли достаточно видео, возвращаем результаты
                        if len(videos) >= limit:
                            return videos[:limit]
            except Exception as req_error:
                logger.warning(f"Не удалось получить видео через requests: {req_error}")
            
            # Если через requests не удалось получить достаточно видео, используем Selenium
            self.driver.get(channel_url)
            
            # Даем время загрузиться странице
            self._random_sleep(2.5, 3.5)
            
            # Прокручиваем вниз несколько раз для загрузки видео
            for i in range(3):
                self.driver.execute_script("window.scrollBy(0, 800);")
                self._random_sleep(1.5, 2.0)
            
            # Новый подход с использованием XPath для надежного поиска ссылок на видео
            try:
                # Ищем все элементы видео через XPath - простой и надежный метод
                xpath_video_links = "//a[contains(@href, '/watch?v=')]"
                video_elements = self.driver.find_elements(By.XPATH, xpath_video_links)
                
                if video_elements:
                    logger.info(f"Найдено {len(video_elements)} элементов с ссылками на видео")
                    
                    # Обрабатываем найденные элементы
                    processed_urls = set()
                    for element in video_elements:
                        try:
                            url = element.get_attribute("href")
                            if url and "/watch?v=" in url:
                                # Проверяем, что это не дубликат
                                if url not in processed_urls:
                                    processed_urls.add(url)
                                    videos.append({"url": url})
                        except Exception as elem_error:
                            logger.debug(f"Ошибка при обработке элемента: {elem_error}")
                    
                    logger.info(f"Добавлено {len(videos)} уникальных видео с канала")
                else:
                    logger.warning("Не найдено элементов с ссылками на видео")
                    
                    # Если не нашли элементы через Selenium, пробуем извлечь из HTML напрямую
                    try:
                        html = self.driver.page_source
                        
                        # Сохраняем HTML для диагностики
                        with open("channel_page.html", "w", encoding="utf-8") as f:
                            f.write(html)
                        
                        video_urls = re.findall(r'href=\"(/watch\?v=[^\"&]+)', html)
                        video_urls = list(set(video_urls))  # Удаляем дубликаты
                        
                        if video_urls:
                            logger.info(f"Найдено {len(video_urls)} видео через парсинг HTML")
                            for url_path in video_urls[:limit]:
                                full_url = f"https://www.youtube.com{url_path}"
                                if full_url not in [v["url"] for v in videos]:
                                    videos.append({"url": full_url})
                        else:
                            logger.error("Не удалось найти ссылки на видео в HTML")
                            
                            # Последняя попытка - создать скриншот для диагностики
                            self.driver.save_screenshot("channel_videos_not_found.png")
                    except Exception as html_error:
                        logger.error(f"Ошибка при парсинге HTML: {html_error}")
            except Exception as xpath_error:
                logger.error(f"Ошибка при поиске элементов через XPath: {xpath_error}")
            
            # Возвращаем найденные видео (не более limit)
            logger.info(f"Всего найдено {len(videos)} видео с канала {channel_url}")
            return videos[:limit]
            
        except Exception as e:
            logger.error(f"Ошибка при получении видео с канала {channel_url}: {e}")
            traceback.print_exc()
            
            # В случае ошибки пытаемся получить видео через альтернативный метод
            try:
                logger.info("Пробуем получить видео через альтернативный метод")
                alt_url = f"https://www.youtube.com/@{channel_id}"
                self.driver.get(alt_url)
                self._random_sleep(2.0, 3.0)
                
                # Прокручиваем вниз несколько раз для загрузки видео
                for i in range(3):
                    self.driver.execute_script("window.scrollBy(0, 800);")
                    self._random_sleep(1.0, 2.0)
                
                # Извлекаем все ссылки на страницы
                html = self.driver.page_source
                video_urls = re.findall(r'href=\"(/watch\?v=[^\"&]+)', html)
                video_urls = list(set(video_urls))  # Удаляем дубликаты
                
                if video_urls:
                    logger.info(f"Найдено {len(video_urls)} видео через альтернативный метод")
                    for url_path in video_urls[:limit]:
                        full_url = f"https://www.youtube.com{url_path}"
                        videos.append({"url": full_url})
                    
                    return videos[:limit]
            except Exception as alt_error:
                logger.error(f"Ошибка при использовании альтернативного метода: {alt_error}")
            
            return []

    def _extract_channel_id(self, channel_url: str) -> Optional[str]:
        """
        Извлекает ID канала из URL.
        
        Args:
            channel_url (str): URL канала YouTube
            
        Returns:
            Optional[str]: ID канала или None, если не удалось извлечь
        """
        try:
            logger.info(f"Извлечение ID канала из URL: {channel_url}")
            
            # Проверяем, что URL не пустой
            if not channel_url:
                logger.warning("URL канала пустой")
                return None
            
            # Нормализуем URL (добавляем https:// если отсутствует)
            if not channel_url.startswith(('http://', 'https://')):
                channel_url = f"https://{channel_url}"
            
            # Формат URL для каналов с ID
            channel_id_pattern = r'youtube\.com/channel/([^/?&]+)'
            channel_id_match = re.search(channel_id_pattern, channel_url)
            
            if channel_id_match:
                channel_id = channel_id_match.group(1)
                logger.info(f"Найден ID канала в стандартном формате: {channel_id}")
                return channel_id
            
            # Формат URL для каналов с пользовательским именем (@username)
            username_pattern = r'youtube\.com/@([^/?&]+)'
            username_match = re.search(username_pattern, channel_url)
            
            if username_match:
                username = username_match.group(1)
                logger.info(f"Найдено пользовательское имя канала: @{username}")
                
                # Поскольку мы не можем напрямую получить ID канала из @username,
                # нам нужно использовать API для поиска канала
                if hasattr(st, 'secrets') and 'youtube' in st.secrets and 'api_key' in st.secrets['youtube']:
                    api_key = st.secrets['youtube']['api_key']
                    logger.info(f"Попытка получить ID канала через API для @{username}")
                    
                    search_url = "https://www.googleapis.com/youtube/v3/search"
                    search_params = {
                        'part': 'snippet',
                        'q': f"@{username}",
                        'type': 'channel',
                        'maxResults': 1,
                        'key': api_key
                    }
                    
                    try:
                        search_response = requests.get(search_url, params=search_params)
                        
                        if search_response.status_code == 200:
                            search_data = search_response.json()
                            if search_data.get('items') and len(search_data['items']) > 0:
                                found_channel_id = search_data['items'][0]['id']['channelId']
                                logger.info(f"Получен ID канала через API: {found_channel_id}")
                                return found_channel_id
                        else:
                            logger.warning(f"Ошибка API при поиске ID канала: {search_response.status_code}")
                    except Exception as e:
                        logger.error(f"Ошибка при получении ID канала через API: {e}")
            
            # Формат URL для пользовательских URL (c или user)
            user_pattern = r'youtube\.com/(c|user)/([^/?&]+)'
            user_match = re.search(user_pattern, channel_url)
            
            if user_match:
                user_type = user_match.group(1)  # c или user
                username = user_match.group(2)
                logger.info(f"Найден формат URL канала: {user_type}/{username}")
                
                # Используем API для получения ID канала
                if hasattr(st, 'secrets') and 'youtube' in st.secrets and 'api_key' in st.secrets['youtube']:
                    api_key = st.secrets['youtube']['api_key']
                    logger.info(f"Попытка получить ID канала через API для {user_type}/{username}")
                    
                    search_url = "https://www.googleapis.com/youtube/v3/search"
                    search_params = {
                        'part': 'snippet',
                        'q': username,
                        'type': 'channel',
                        'maxResults': 1,
                        'key': api_key
                    }
                    
                    try:
                        search_response = requests.get(search_url, params=search_params)
                        
                        if search_response.status_code == 200:
                            search_data = search_response.json()
                            if search_data.get('items') and len(search_data['items']) > 0:
                                found_channel_id = search_data['items'][0]['id']['channelId']
                                logger.info(f"Получен ID канала через API: {found_channel_id}")
                                return found_channel_id
                        else:
                            logger.warning(f"Ошибка API при поиске ID канала: {search_response.status_code}")
                    except Exception as e:
                        logger.error(f"Ошибка при получении ID канала через API: {e}")
            
            # Если ни один метод не сработал, пробуем прямой запрос через API с использованием URL как запроса
            if hasattr(st, 'secrets') and 'youtube' in st.secrets and 'api_key' in st.secrets['youtube']:
                api_key = st.secrets['youtube']['api_key']
                logger.info(f"Попытка получить ID канала через API по прямому запросу: {channel_url}")
                
                search_url = "https://www.googleapis.com/youtube/v3/search"
                search_params = {
                    'part': 'snippet',
                    'q': channel_url,
                    'type': 'channel',
                    'maxResults': 1,
                    'key': api_key
                }
                
                try:
                    search_response = requests.get(search_url, params=search_params)
                    
                    if search_response.status_code == 200:
                        search_data = search_response.json()
                        if search_data.get('items') and len(search_data['items']) > 0:
                            found_channel_id = search_data['items'][0]['id']['channelId']
                            logger.info(f"Получен ID канала через API по прямому запросу: {found_channel_id}")
                            return found_channel_id
                except Exception as e:
                    logger.error(f"Ошибка при получении ID канала через API по прямому запросу: {e}")
            
            logger.warning(f"Не удалось извлечь ID канала из URL: {channel_url}")
            return None
                
        except Exception as e:
            logger.error(f"Ошибка при извлечении ID канала: {e}")
            return None

    def _set_random_proxy(self) -> None:
        """
        Выбирает случайный прокси из списка и применяет его к драйверу.
        """
        if not self.proxy_list or len(self.proxy_list) == 0:
            logger.warning("Список прокси пуст, невозможно установить случайный прокси")
            self.current_proxy = None
            return
        
        # Выбираем случайный прокси из списка
        self.current_proxy = random.choice(self.proxy_list)
        
        logger.info(f"Выбран прокси-сервер: {self.current_proxy['server']}")
        
        # Проверяем, инициализирован ли драйвер
        if not self.driver:
            logger.warning("Драйвер не инициализирован, прокси будет применен при инициализации")
            return
        
        # Извлекаем логин, пароль и адрес прокси
        username = self.current_proxy.get("username")
        password = self.current_proxy.get("password")
        server = self.current_proxy.get("server")
        
        # Вызываем метод аутентификации прокси
        if username and password:
            try:
                # Применяем аутентификацию прокси через CDP
                self._handle_proxy_auth()
                logger.info("Прокси успешно настроен для драйвера")
            except Exception as e:
                logger.error(f"Ошибка при настройке прокси: {e}")
                # Продолжаем без прокси в случае ошибки
                self.current_proxy = None

    def _get_channel_details_api(self, channel_id: str, api_key: str) -> Optional[Dict[str, Any]]:
        """
        Получает детальную информацию о канале через API.
        
        Args:
            channel_id (str): ID канала
            api_key (str): Ключ API YouTube
            
        Returns:
            Optional[Dict[str, Any]]: Словарь с информацией о канале или None в случае ошибки
        """
        try:
            base_url = "https://www.googleapis.com/youtube/v3/channels"
            params = {
                'part': 'snippet,statistics,contentDetails',
                'id': channel_id,
                'key': api_key
            }
            
            logger.info(f"Запрос деталей канала {channel_id}: {base_url} с параметрами {params}")
            response = requests.get(base_url, params=params)
            
            if response.status_code != 200:
                logger.warning(f"Ошибка API при получении деталей канала: {response.status_code}")
                logger.warning(f"Ответ API: {response.text}")
                return None
                
            data = response.json()
            
            if not data.get('items'):
                logger.warning(f"API не вернул данные для канала {channel_id}")
                return None
                
            channel_info = data['items'][0]
            snippet = channel_info.get('snippet', {})
            statistics = channel_info.get('statistics', {})
            
            # Расчет возраста канала
            published_at = snippet.get('publishedAt')
            channel_age_days = 0
            
            if published_at:
                try:
                    # Обработка формата даты с микросекундами (например 2025-02-17T13:42:15.172022Z)
                    if '.' in published_at:
                        # Если есть микросекунды, отрезаем их до точки и добавляем Z
                        date_part = published_at.split('.')[0]
                        published_date = datetime.strptime(date_part + 'Z', "%Y-%m-%dT%H:%M:%SZ")
                    else:
                        # Для формата без микросекунд
                        published_date = datetime.strptime(published_at, "%Y-%m-%dT%H:%M:%SZ")
                    
                    channel_age_days = (datetime.now() - published_date).days
                except ValueError as e:
                    logger.warning(f"Не удалось обработать дату публикации канала: {published_at}, ошибка: {e}")
                    # Пробуем другой подход к парсингу даты - через регулярное выражение
                    try:
                        import re
                        date_match = re.match(r'(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})', published_at)
                        if date_match:
                            date_str = f"{date_match.group(1)} {date_match.group(2)}"
                            published_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                            channel_age_days = (datetime.now() - published_date).days
                    except Exception as e2:
                        logger.error(f"Не удалось обработать дату альтернативным способом: {e2}")
            
            # Формируем результат
            subscriber_count = 0
            try:
                subscriber_count = int(statistics.get('subscriberCount', 0))
            except (ValueError, TypeError):
                logger.warning(f"Не удалось преобразовать subscriberCount в число: {statistics.get('subscriberCount')}")
            
            video_count = 0
            try:
                video_count = int(statistics.get('videoCount', 0))
            except (ValueError, TypeError):
                logger.warning(f"Не удалось преобразовать videoCount в число: {statistics.get('videoCount')}")
            
            view_count = 0
            try:
                view_count = int(statistics.get('viewCount', 0))
            except (ValueError, TypeError):
                logger.warning(f"Не удалось преобразовать viewCount в число: {statistics.get('viewCount')}")
            
            result = {
                "id": channel_id,
                "url": f"https://www.youtube.com/channel/{channel_id}",
                "title": snippet.get('title', 'Неизвестно'),
                "description": snippet.get('description', ''),
                "country": snippet.get('country', 'Неизвестно'),
                "thumbnail": snippet.get('thumbnails', {}).get('high', {}).get('url', ''),
                "subscriber_count": subscriber_count,
                "video_count": video_count,
                "view_count": view_count,
                "published_at": published_at,
                "channel_age_days": channel_age_days
            }
            
            logger.info(f"Получены детали канала: {result['title']}, подписчиков: {result['subscriber_count']}, просмотров: {result['view_count']}")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка при получении деталей канала {channel_id} через API: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    def _get_video_details_api(self, video_id: str, api_key: str) -> Optional[Dict[str, Any]]:
        """
        Получает детальную информацию о видео через API.
        
        Args:
            video_id (str): ID видео
            api_key (str): Ключ API YouTube
            
        Returns:
            Optional[Dict[str, Any]]: Словарь с информацией о видео или None в случае ошибки
        """
        try:
            base_url = "https://www.googleapis.com/youtube/v3/videos"
            params = {
                'part': 'snippet,statistics,contentDetails',
                'id': video_id,
                'key': api_key
            }
            
            logger.info(f"Запрос деталей видео {video_id}: {base_url} с параметрами {params}")
            response = requests.get(base_url, params=params)
            
            if response.status_code != 200:
                logger.warning(f"Ошибка API при получении деталей видео: {response.status_code}")
                logger.warning(f"Ответ API: {response.text}")
                return None
                
            data = response.json()
            
            if not data.get('items'):
                logger.warning(f"API не вернул данные для видео {video_id}")
                return None
                
            video_info = data['items'][0]
            snippet = video_info.get('snippet', {})
            statistics = video_info.get('statistics', {})
            content_details = video_info.get('contentDetails', {})
            
            # Форматирование даты публикации
            published_at = snippet.get('publishedAt')
            formatted_date = None
            
            if published_at:
                try:
                    # Обработка формата даты
                    if '.' in published_at:
                        # Если есть микросекунды, отрезаем их
                        date_part = published_at.split('.')[0]
                        published_date = datetime.strptime(date_part + 'Z', "%Y-%m-%dT%H:%M:%SZ")
                    else:
                        # Для формата без микросекунд
                        published_date = datetime.strptime(published_at, "%Y-%m-%dT%H:%M:%SZ")
                    
                    # Форматируем дату в нужный формат
                    formatted_date = published_date.strftime("%Y-%m-%d %H:%M")
                except ValueError as e:
                    logger.warning(f"Не удалось обработать дату публикации видео: {published_at}, ошибка: {e}")
            
            # Получаем количество просмотров
            view_count = 0
            try:
                view_count = int(statistics.get('viewCount', 0))
            except (ValueError, TypeError):
                logger.warning(f"Не удалось преобразовать viewCount в число: {statistics.get('viewCount')}")
            
            # Получаем URL превью
            thumbnail_url = ""
            thumbnails = snippet.get('thumbnails', {})
            if 'maxres' in thumbnails:
                thumbnail_url = thumbnails['maxres'].get('url', '')
            elif 'high' in thumbnails:
                thumbnail_url = thumbnails['high'].get('url', '')
            elif 'medium' in thumbnails:
                thumbnail_url = thumbnails['medium'].get('url', '')
            elif 'standard' in thumbnails:
                thumbnail_url = thumbnails['standard'].get('url', '')
            elif 'default' in thumbnails:
                thumbnail_url = thumbnails['default'].get('url', '')
            
            # Получаем транскрипцию (для этого требуется отдельный запрос к API captions)
            transcript = self._get_video_transcript(video_id, api_key)
            
            # Получаем название категории видео
            category_id = snippet.get('categoryId', '')
            category_name = "Неизвестно"
            if category_id:
                category_name = self._get_video_category_name(category_id, api_key)
            
            # Формируем результат
            result = {
                "id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "title": snippet.get('title', 'Неизвестно'),
                "description": snippet.get('description', ''),
                "channel_title": snippet.get('channelTitle', 'Неизвестно'),
                "channel_id": snippet.get('channelId', ''),
                "publication_date": formatted_date,
                "view_count": view_count,
                "category": category_name,
                "language": snippet.get('defaultLanguage', snippet.get('defaultAudioLanguage', 'Неизвестно')),
                "thumbnail_url": thumbnail_url,
                "transcript": transcript
            }
            
            logger.info(f"Получены детали видео: {result['title']}, просмотров: {result['view_count']}")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка при получении деталей видео {video_id} через API: {str(e)}")
            logger.error(traceback.format_exc())
            return None
            
    def _get_video_transcript(self, video_id: str, api_key: str) -> str:
        """
        Получает транскрипцию видео через API.
        
        Args:
            video_id (str): ID видео
            api_key (str): Ключ API YouTube
            
        Returns:
            str: Текст транскрипции или пустую строку, если транскрипция не найдена
        """
        try:
            # Сначала получаем список доступных субтитров
            captions_url = "https://www.googleapis.com/youtube/v3/captions"
            captions_params = {
                'part': 'snippet',
                'videoId': video_id,
                'key': api_key
            }
            
            logger.info(f"Запрос списка субтитров для видео {video_id}")
            captions_response = requests.get(captions_url, params=captions_params)
            
            if captions_response.status_code != 200:
                logger.warning(f"Ошибка API при получении списка субтитров: {captions_response.status_code}")
                return "Транскрипция недоступна"
                
            captions_data = captions_response.json()
            
            if not captions_data.get('items'):
                logger.warning(f"Субтитры не найдены для видео {video_id}")
                return "Транскрипция недоступна"
            
            # API не позволяет напрямую получить текст субтитров без авторизации
            # Поэтому возвращаем информацию о наличии субтитров
            caption_count = len(captions_data.get('items', []))
            languages = [item.get('snippet', {}).get('language', 'unknown') for item in captions_data.get('items', [])]
            
            return f"Доступно {caption_count} вариантов субтитров. Языки: {', '.join(languages)}"
            
        except Exception as e:
            logger.error(f"Ошибка при получении транскрипции видео {video_id}: {str(e)}")
            return "Ошибка при получении транскрипции"

    def _get_video_category_name(self, category_id: str, api_key: str) -> str:
        """
        Получает название категории видео по её ID.
        
        Args:
            category_id (str): ID категории
            api_key (str): Ключ API YouTube
            
        Returns:
            str: Название категории или 'Неизвестно', если категория не найдена
        """
        # Словарь с часто используемыми категориями для уменьшения количества запросов к API
        common_categories = {
            "1": "Фильмы и анимация",
            "2": "Автомобили и транспорт",
            "10": "Музыка",
            "15": "Животные",
            "17": "Спорт",
            "18": "Короткометражное кино",
            "19": "Путешествия и события",
            "20": "Игры",
            "21": "Видеоблоги",
            "22": "Люди и блоги",
            "23": "Комедия",
            "24": "Развлечения",
            "25": "Новости и политика",
            "26": "Практические советы и стиль",
            "27": "Образование",
            "28": "Наука и технологии",
            "29": "Некоммерческие и социальные проекты",
            "30": "Фильмы",
            "31": "Мультфильмы/Аниме",
            "32": "Экшен/Приключения",
            "33": "Классика",
            "34": "Комедия",
            "35": "Документальное",
            "36": "Драма",
            "37": "Семейное",
            "38": "Иностранное",
            "39": "Ужасы",
            "40": "Sci-Fi/Fantasy",
            "41": "Триллеры",
            "42": "Короткометражки",
            "43": "Шоу",
            "44": "Трейлеры"
        }
        
        # Если категория в словаре, возвращаем её название
        if category_id in common_categories:
            return common_categories[category_id]
            
        # Иначе делаем запрос к API
        try:
            base_url = "https://www.googleapis.com/youtube/v3/videoCategories"
            params = {
                'part': 'snippet',
                'id': category_id,
                'key': api_key
            }
            
            logger.info(f"Запрос категории видео {category_id}")
            response = requests.get(base_url, params=params)
            
            if response.status_code != 200:
                logger.warning(f"Ошибка API при получении категории видео: {response.status_code}")
                return "Неизвестно"
                
            data = response.json()
            
            if not data.get('items'):
                logger.warning(f"API не вернул данные для категории {category_id}")
                return "Неизвестно"
                
            return data['items'][0].get('snippet', {}).get('title', 'Неизвестно')
            
        except Exception as e:
            logger.error(f"Ошибка при получении категории видео {category_id}: {str(e)}")
            return "Неизвестно"

    def login_to_google(self) -> bool:
        """
        Авторизация в Google аккаунте.
        
        Returns:
            bool: True, если авторизация успешна, иначе False.
        """
        if not self.google_account or not self.driver:
            logger.error("Не указан Google аккаунт или драйвер не инициализирован")
            return False
            
        try:
            email = self.google_account.get('email')
            password = self.google_account.get('password')
            
            if not email or not password:
                logger.error("Не указан email или пароль для авторизации в Google")
                return False
                
            logger.info(f"Попытка авторизации в Google аккаунте {email}")
            
            # Проверяем, авторизованы ли мы уже
            current_url = self.driver.current_url
            if "youtube.com" in current_url or "google.com/accounts" in current_url:
                try:
                    # Проверяем аватар на YouTube или Google
                    avatar_found = self.driver.execute_script("""
                        return document.querySelector('button#avatar-btn') !== null || 
                               document.querySelector('img#avatar-btn') !== null || 
                               document.querySelector('[aria-label="Настройки аккаунта"]') !== null ||
                               document.querySelector('[aria-label="Account settings"]') !== null;
                    """)
                    
                    if avatar_found:
                        logger.info(f"Уже авторизованы в аккаунт Google {email}")
                        self.is_logged_in = True
                        return True
                except:
                    pass
            
            # Переходим на страницу авторизации Google
            self.driver.get("https://accounts.google.com/signin")
            
            # Ждем загрузки страницы
            self._random_sleep(2.0, 3.0)
            
            # Вводим email
            try:
                # Используем явное ожидание для элемента email
                email_input = WebDriverWait(self.driver, 15).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='email']"))
                )
                
                # Очищаем поле и вводим email
                email_input.clear()
                # Медленный ввод для имитации человека
                for char in email:
                    email_input.send_keys(char)
                    time.sleep(random.uniform(0.05, 0.15))
                
                logger.info("Email введен успешно")
                
                # Небольшая пауза перед нажатием кнопки
                time.sleep(random.uniform(0.5, 1.0))
                
                # Ищем кнопку "Далее" и нажимаем на нее - расширяем селекторы
                try:
                    next_button = None
                    for selector in ["button[jsname='LgbsSe']", "#identifierNext button", "#identifierNext", "button#next", "button.next", "button:contains('Next')"]:
                        try:
                            next_button = self.driver.find_element(By.CSS_SELECTOR, selector)
                            if next_button and next_button.is_displayed():
                                break
                        except:
                            continue
                            
                    if next_button:
                        next_button.click()
                    else:
                        # Альтернативный метод нажатия через JavaScript
                        self.driver.execute_script("""
                            var buttons = document.querySelectorAll('button[jsname="LgbsSe"], #identifierNext button, #identifierNext, button#next, button.next');
                            for (var i = 0; i < buttons.length; i++) {
                                if (buttons[i].offsetParent !== null) {  // Проверка видимости
                                    buttons[i].click();
                                    return true;
                                }
                            }
                            
                            // Если не нашли по селекторам, ищем по тексту
                            var allButtons = document.querySelectorAll('button');
                            for (var i = 0; i < allButtons.length; i++) {
                                if (allButtons[i].offsetParent !== null && 
                                    (allButtons[i].innerText.includes('Next') || 
                                     allButtons[i].innerText.includes('Далее'))) {
                                    allButtons[i].click();
                                    return true;
                                }
                            }
                            return false;
                        """)
                except Exception as e:
                    logger.warning(f"Ошибка при нажатии кнопки после ввода email: {e}")
                
                logger.info("Нажата кнопка 'Далее' после ввода email")
                
                # Ждем загрузки страницы ввода пароля
                self._random_sleep(3.0, 5.0)
                
                # Вводим пароль с явным ожиданием
                try:
                    # Используем явное ожидание с разными селекторами
                    password_input = None
                    password_selectors = [
                        "input[type='password']",
                        "input[name='password']",
                        "#password input",
                        "input.password"
                    ]
                    
                    for selector in password_selectors:
                        try:
                            password_input = WebDriverWait(self.driver, 10).until(
                                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                            )
                            if password_input:
                                break
                        except:
                            continue
                    
                    if not password_input:
                        # Если не нашли по селекторам, делаем снимок экрана и ищем через JavaScript
                        try:
                            self.driver.save_screenshot("password_page.png")
                            logger.info("Сохранен скриншот страницы пароля")
                        except:
                            pass
                            
                        # Попытка найти поле через JavaScript
                        password_input = self.driver.execute_script("""
                            var inputs = document.querySelectorAll('input');
                            for (var i = 0; i < inputs.length; i++) {
                                if (inputs[i].type === 'password' || 
                                    inputs[i].name === 'password' || 
                                    inputs[i].autocomplete === 'current-password') {
                                    return inputs[i];
                                }
                            }
                            return null;
                        """)
                        
                    if not password_input:
                        logger.error("Не удалось найти поле для ввода пароля")
                        return False
                    
                    # Очищаем поле и вводим пароль
                    password_input.clear()
                    # Медленный ввод для имитации человека
                    for char in password:
                        password_input.send_keys(char)
                        time.sleep(random.uniform(0.05, 0.15))
                    
                    logger.info("Пароль введен успешно")
                    
                    # Небольшая пауза перед нажатием кнопки
                    time.sleep(random.uniform(0.5, 1.0))
                    
                    # Ищем кнопку "Далее" и нажимаем на нее - расширяем селекторы
                    next_button_clicked = False
                    try:
                        next_button = None
                        for selector in ["button[jsname='LgbsSe']", "#passwordNext button", "#passwordNext", "button#next", "button.next", "button:contains('Next')"]:
                            try:
                                next_button = self.driver.find_element(By.CSS_SELECTOR, selector)
                                if next_button and next_button.is_displayed():
                                    next_button.click()
                                    next_button_clicked = True
                                    break
                            except:
                                continue
                                
                        if not next_button_clicked:
                            # Альтернативный метод нажатия через JavaScript
                            next_button_clicked = self.driver.execute_script("""
                                var buttons = document.querySelectorAll('button[jsname="LgbsSe"], #passwordNext button, #passwordNext, button#next, button.next');
                                for (var i = 0; i < buttons.length; i++) {
                                    if (buttons[i].offsetParent !== null) {  // Проверка видимости
                                        buttons[i].click();
                                        return true;
                                    }
                                }
                                
                                // Если не нашли по селекторам, ищем по тексту
                                var allButtons = document.querySelectorAll('button');
                                for (var i = 0; i < allButtons.length; i++) {
                                    if (allButtons[i].offsetParent !== null && 
                                        (allButtons[i].innerText.includes('Next') || 
                                         allButtons[i].innerText.includes('Далее'))) {
                                        allButtons[i].click();
                                        return true;
                                    }
                                }
                                return false;
                            """)
                    except Exception as e:
                        logger.warning(f"Ошибка при нажатии кнопки после ввода пароля: {e}")
                        
                    if next_button_clicked:
                        logger.info("Нажата кнопка 'Далее' после ввода пароля")
                except Exception as e:
                    logger.error(f"Ошибка при вводе пароля: {e}")
                    return False
                
                # Ждем загрузки страницы подтверждения входа или запроса дополнительной проверки
                self._random_sleep(5.0, 7.0)
                
                # Проверяем текущий URL для определения результата
                current_url = self.driver.current_url
                
                # Если требуется дополнительная проверка (двухфакторная аутентификация или подозрительная активность)
                if "challenge" in current_url or "signin/v2/challenge" in current_url:
                    logger.info("Требуется дополнительная проверка для входа в аккаунт")
                    logger.info("Ожидание ввода кода подтверждения...")
                    
                    # Делаем скриншот для диагностики
                    try:
                        self.driver.save_screenshot("auth_challenge.png")
                        logger.info("Сохранен скриншот страницы подтверждения")
                    except:
                        pass
                    
                    # Даем пользователю время для ручного ввода кода (30 секунд)
                    time.sleep(30)
                
                # Проверяем успешность входа сразу после авторизации
                if "myaccount.google.com" in self.driver.current_url or "accounts.google.com/signin/v2/challenge/selection" in self.driver.current_url:
                    logger.info(f"Обнаружена успешная авторизация в Google аккаунт {email}")
                    self.is_logged_in = True
                    return True
                
                # Переходим на YouTube для дополнительной проверки авторизации
                self.driver.get("https://www.youtube.com")
                self._random_sleep(3.0, 5.0)
                
                # Проверяем наличие признаков авторизации
                try:
                    # Сначала проверяем аватар профиля
                    avatar_selectors = [
                        "button#avatar-btn", 
                        "button[aria-label='Настройки аккаунта']",
                        "button[aria-label='Account settings']",
                        "img#img.style-scope.yt-img-shadow",
                        "#avatar-btn",
                        "ytd-topbar-menu-button-renderer"
                    ]
                    
                    avatar_found = False
                    for selector in avatar_selectors:
                        try:
                            avatar = self.driver.find_element(By.CSS_SELECTOR, selector)
                            if avatar.is_displayed():
                                avatar_found = True
                                break
                        except:
                            continue
                    
                    if avatar_found:
                        logger.info(f"Успешная авторизация в Google аккаунте {email} (найден аватар)")
                        self.is_logged_in = True
                        
                        # Сохраняем куки для возможного последующего использования
                        try:
                            self.cookies = self.driver.get_cookies()
                            logger.info("Cookies сохранены успешно")
                        except:
                            pass
                        
                        return True
                    else:
                        # Пробуем альтернативный метод проверки через JavaScript
                        is_logged_in = self.driver.execute_script("""
                            return document.querySelector('button#avatar-btn') !== null || 
                                   document.querySelector('ytd-topbar-menu-button-renderer') !== null ||
                                   document.querySelector('yt-formatted-string:contains("Выйти")') !== null ||
                                   document.querySelector('yt-formatted-string:contains("Sign out")') !== null ||
                                   document.querySelector('button[aria-label="Настройки аккаунта"]') !== null ||
                                   document.querySelector('button[aria-label="Account settings"]') !== null;
                        """)
                        
                        if is_logged_in:
                            logger.info(f"Успешная авторизация в Google аккаунте {email} (проверка через JavaScript)")
                            self.is_logged_in = True
                            return True
                        else:
                            # Проверяем содержимое страницы на наличие признаков авторизации
                            page_content = self.driver.page_source.lower()
                            if "выйти" in page_content or "sign out" in page_content or email.lower() in page_content:
                                logger.info(f"Успешная авторизация в Google аккаунте {email} (найдено упоминание в контенте страницы)")
                                self.is_logged_in = True
                                return True
                            else:
                                logger.warning("Не удалось обнаружить признаки авторизации на YouTube")
                                
                                # Делаем скриншот для диагностики
                                try:
                                    self.driver.save_screenshot("auth_youtube_check.png")
                                    logger.info("Сохранен скриншот страницы YouTube для диагностики")
                                except:
                                    pass
                                
                                return False
                except Exception as e:
                    logger.error(f"Ошибка при проверке авторизации: {e}")
                    return False
                    
            except Exception as e:
                logger.error(f"Ошибка при вводе данных авторизации: {e}")
                
            return False
                
        except Exception as e:
            logger.error(f"Ошибка при авторизации в Google: {e}")
            traceback.print_exc()
            return False
    
    def prewatch_videos(self, video_urls: List[str], min_watch_time: int = 15, max_watch_time: int = 45, 
                      like_probability: float = 0.7, watch_percentage: float = 0.3) -> None:
        """
        Предварительный просмотр видео для улучшения рекомендаций.
        
        Args:
            video_urls (List[str]): Список URL видео для просмотра.
            min_watch_time (int): Минимальное время просмотра каждого видео в секундах.
            max_watch_time (int): Максимальное время просмотра каждого видео в секундах.
            like_probability (float): Вероятность поставить лайк просматриваемому видео (от 0 до 1).
            watch_percentage (float): Процент от общей длительности видео для просмотра (от 0 до 1).
        """
        if not self.driver:
            logger.error("Драйвер не инициализирован, невозможно выполнить предварительный просмотр")
            return
            
        if not video_urls:
            logger.warning("Не указаны URL видео для предварительного просмотра")
            return
            
        logger.info(f"Начинаем предварительный просмотр {len(video_urls)} видео")
        logger.info(f"Настройки просмотра: время {min_watch_time}-{max_watch_time} сек, "
                    f"вероятность лайка {like_probability:.1%}, процент просмотра {watch_percentage:.1%}")
        
        videos_watched = 0
        
        # Для симуляции более реального поведения - не просматривать все видео подряд,
        # а делать небольшие паузы между просмотрами
        for idx, url in enumerate(video_urls):
            try:
                logger.info(f"Просмотр видео {idx+1}/{len(video_urls)}: {url}")
                
                # Загружаем страницу видео
                self.driver.get(url)
                
                # Ждем загрузки видео
                self._random_sleep(2.0, 3.0)
                
                # Сначала проверяем длительность видео, чтобы определить время просмотра
                video_duration_seconds = self._get_video_duration()
                
                # Рассчитываем время просмотра
                if video_duration_seconds and video_duration_seconds > 0:
                    # Если это короткое видео (меньше минуты)
                    if video_duration_seconds < 60:
                        # Для коротких видео просматриваем большую часть
                        actual_watch_time = min(video_duration_seconds, max_watch_time)
                    else:
                        # Для обычных видео используем процент от общей длительности
                        percentage_watch_time = int(video_duration_seconds * watch_percentage)
                        
                        # Но не меньше минимального и не больше максимального
                        actual_watch_time = max(min_watch_time, min(percentage_watch_time, max_watch_time))
                        
                        # Для длинных видео (более 10 минут) имитируем перемотку
                        if video_duration_seconds > 600 and random.random() < 0.7:
                            # В 70% случаев перематываем к случайному месту в видео
                            skip_to_position = random.uniform(0.1, 0.5) * video_duration_seconds  # 10-50% от длины
                            self._skip_to_position(skip_to_position)
                            logger.info(f"Перемотка видео к позиции {skip_to_position:.1f} секунд")
                else:
                    # Если не смогли определить длительность, используем случайное время между min и max
                    actual_watch_time = random.uniform(min_watch_time, max_watch_time)
                
                logger.info(f"Просмотр видео в течение {actual_watch_time:.1f} секунд "
                            f"(полная длительность: {video_duration_seconds if video_duration_seconds else 'неизвестно'} сек)")
                
                # Запускаем воспроизведение (может запуститься автоматически)
                try:
                    # Проверяем, запущено ли видео
                    is_playing = self.driver.execute_script("""
                        var video = document.querySelector('video');
                        if (video) {
                            return !video.paused;
                        }
                        return false;
                    """)
                    
                    # Если видео не запущено, пытаемся запустить
                    if not is_playing:
                        self.driver.execute_script("""
                            var video = document.querySelector('video');
                            if (video) {
                                video.play();
                            }
                            
                            // Альтернативный способ - клик по плееру
                            var player = document.querySelector('.html5-video-player');
                            if (player) {
                                player.click();
                            }
                        """)
                        
                    # Устанавливаем звук на минимум
                    self.driver.execute_script("""
                        var video = document.querySelector('video');
                        if (video) {
                            video.volume = 0.1;
                        }
                    """)
                    
                    # Принимаем cookies, если есть такое окно
                    try:
                        accept_button = self.driver.find_element(By.XPATH, 
                            "//button[contains(., 'Принять все') or contains(., 'Accept all')]")
                        accept_button.click()
                    except:
                        pass
                    
                    # Проверяем наличие рекламы и пытаемся пропустить её
                    self._handle_ads()
                    
                    # Ставим лайк видео с указанной вероятностью
                    if random.random() < like_probability and self.is_logged_in:
                        try:
                            # Проверяем, поставлен ли уже лайк
                            is_liked = self.driver.execute_script("""
                                var likeButton = document.querySelector('button[aria-label="Нравится" i], button[aria-label="Like" i]');
                                if (likeButton) {
                                    return likeButton.getAttribute('aria-pressed') === 'true';
                                }
                                return false;
                            """)
                            
                            if not is_liked:
                                like_button = self.driver.find_element(By.CSS_SELECTOR, 
                                    "button[aria-label='Нравится' i], button[aria-label='Like' i]")
                                like_button.click()
                                logger.info("Поставлен лайк видео")
                            else:
                                logger.info("Видео уже имеет лайк")
                        except Exception as e:
                            logger.warning(f"Не удалось поставить лайк: {e}")
                    
                    # Прокрутка комментариев с некоторой вероятностью
                    if random.random() < 0.4:  # 40% шанс
                        try:
                            # Прокручиваем вниз, чтобы увидеть комментарии
                            self.driver.execute_script("window.scrollBy(0, 800);")
                            self._random_sleep(2.0, 4.0)
                            
                            # Еще прокрутка для имитации чтения комментариев
                            self.driver.execute_script("window.scrollBy(0, 400);")
                            self._random_sleep(2.0, 3.0)
                            
                            logger.info("Прокрутка до комментариев выполнена")
                        except:
                            pass
                    
                    # "Смотрим" видео указанное время
                    time.sleep(actual_watch_time)
                    
                    # Для некоторых видео имитируем нажатие на рекомендацию
                    if random.random() < 0.3 and idx < len(video_urls) - 1:  # 30% шанс, если это не последнее видео
                        try:
                            # Прокручиваем к рекомендациям
                            self.driver.execute_script("window.scrollBy(0, 400);")
                            self._random_sleep(1.0, 2.0)
                            
                            # Проверяем рекомендации
                            rec_links = self.driver.find_elements(By.CSS_SELECTOR, "#related a#thumbnail")
                            if rec_links and len(rec_links) > 0:
                                # Выбираем случайную рекомендацию из первых 5
                                random_rec = random.choice(rec_links[:min(5, len(rec_links))])
                                rec_url = random_rec.get_attribute("href")
                                
                                if rec_url and "watch?v=" in rec_url:
                                    logger.info(f"Переход по рекомендации на {rec_url}")
                                    self.driver.get(rec_url)
                                    
                                    # Проверяем рекламу на новом видео
                                    self._random_sleep(2.0, 3.0)
                                    self._handle_ads()
                                    
                                    # Немного смотрим это видео
                                    bonus_time = random.uniform(5.0, 15.0)
                                    logger.info(f"Просмотр рекомендованного видео {bonus_time:.1f} секунд")
                                    time.sleep(bonus_time)
                        except Exception as e:
                            logger.warning(f"Ошибка при переходе по рекомендации: {e}")
                    
                    videos_watched += 1
                    
                except Exception as e:
                    logger.warning(f"Ошибка при воспроизведении видео: {e}")
                
                # Делаем случайную паузу между видео (от 1 до 3 секунд)
                if idx < len(video_urls) - 1:
                    pause_time = random.uniform(1.0, 3.0)
                    logger.info(f"Пауза между видео: {pause_time:.1f} секунд")
                    time.sleep(pause_time)
                
            except Exception as e:
                logger.error(f"Ошибка при просмотре видео {url}: {e}")
        
        logger.info(f"Предварительный просмотр завершен. Просмотрено {videos_watched} из {len(video_urls)} видео")
    
    def _get_video_duration(self) -> Optional[float]:
        """
        Определяет длительность текущего видео в секундах.
        
        Returns:
            Optional[float]: Длительность видео в секундах или None, если не удалось определить.
        """
        try:
            # Получаем длительность через JavaScript
            duration = self.driver.execute_script("""
                var video = document.querySelector('video');
                if (video && !isNaN(video.duration)) {
                    return video.duration;
                }
                
                // Если video.duration недоступно, пробуем через атрибуты
                var timeDisplay = document.querySelector('.ytp-time-duration');
                if (timeDisplay) {
                    var timeText = timeDisplay.textContent;
                    if (timeText) {
                        var parts = timeText.split(':');
                        if (parts.length === 2) {
                            // MM:SS
                            return parseInt(parts[0]) * 60 + parseInt(parts[1]);
                        } else if (parts.length === 3) {
                            // HH:MM:SS
                            return parseInt(parts[0]) * 3600 + parseInt(parts[1]) * 60 + parseInt(parts[2]);
                        }
                    }
                }
                
                return null;
            """)
            
            if duration is not None:
                logger.info(f"Определена длительность видео: {duration:.1f} секунд")
                return float(duration)
            else:
                logger.warning("Не удалось определить длительность видео")
                return None
                
        except Exception as e:
            logger.warning(f"Ошибка при определении длительности видео: {e}")
            return None
    
    def _skip_to_position(self, position_seconds: float) -> None:
        """
        Перематывает видео к указанной позиции.
        
        Args:
            position_seconds (float): Позиция в секундах.
        """
        try:
            # Перематываем видео к указанной позиции
            self.driver.execute_script(f"""
                var video = document.querySelector('video');
                if (video) {{
                    video.currentTime = {position_seconds};
                }}
            """)
            
            # Небольшая пауза после перемотки
            time.sleep(0.5)
            
        except Exception as e:
            logger.warning(f"Ошибка при перемотке видео: {e}")
    
    def _handle_ads(self) -> None:
        """
        Обрабатывает рекламу на YouTube, пытаясь пропустить её.
        """
        try:
            # Проверяем наличие кнопки "Пропустить рекламу"
            try:
                # Даем немного времени на появление рекламы
                self._random_sleep(1.0, 3.0)
                
                # Проверяем, идет ли реклама
                is_ad_playing = self.driver.execute_script("""
                    return document.querySelector('.ad-showing') !== null ||
                           document.querySelector('.ytp-ad-player-overlay') !== null;
                """)
                
                if is_ad_playing:
                    logger.info("Обнаружена реклама, ожидаем возможности пропуска")
                    
                    # Пытаемся найти и нажать кнопку пропуска рекламы
                    for attempt in range(5):  # Несколько попыток на случай, если кнопка появится не сразу
                        try:
                            skip_button = self.driver.find_element(By.CSS_SELECTOR, 
                                ".ytp-ad-skip-button, .ytp-ad-skip-button-modern")
                            
                            if skip_button.is_displayed():
                                skip_button.click()
                                logger.info("Реклама пропущена")
                                break
                        except:
                            # Кнопка еще не появилась, ждем
                            time.sleep(1)
                    
                    # Проверяем, все еще идет ли реклама
                    is_still_ad = self.driver.execute_script("""
                        return document.querySelector('.ad-showing') !== null ||
                               document.querySelector('.ytp-ad-player-overlay') !== null;
                    """)
                    
                    if is_still_ad:
                        # Если реклама непропускаемая, ждем немного, но не всю рекламу
                        logger.info("Непропускаемая реклама, ожидаем несколько секунд")
                        time.sleep(random.uniform(3.0, 7.0))
            except:
                pass
                
        except Exception as e:
            logger.warning(f"Ошибка при обработке рекламы: {e}")

    def test_video_parameters(self, video_urls: List[str]) -> pd.DataFrame:
        """
        Тестирует алгоритм сбора параметров видео.
        
        Args:
            video_urls (List[str]): Список URL видео для анализа.
            
        Returns:
            pd.DataFrame: Таблица с параметрами видео (URL, заголовок, дни с момента публикации, просмотры).
        """
        logger.info(f"Запуск тестирования параметров для {len(video_urls)} видео")
        
        # Используем быстрый метод вместо полного запуска браузера
        return self.test_video_parameters_fast(video_urls)

    def test_video_parameters_fast(self, video_urls: List[str]) -> pd.DataFrame:
        """
        Быстрый способ тестирования параметров видео без запуска полного браузера.
        Использует прямые HTTP запросы для получения данных.
        
        Args:
            video_urls (List[str]): Список URL видео для анализа.
            
        Returns:
            pd.DataFrame: Таблица с параметрами видео (URL, заголовок, дни с момента публикации, просмотры).
        """
        logger.info(f"Запуск быстрого тестирования параметров для {len(video_urls)} видео")
        
        results = []
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
        }
        
        for url in video_urls:
            try:
                # Извлекаем ID видео из URL
                video_id = None
                if "youtube.com/watch?v=" in url:
                    video_id = url.split("watch?v=")[1].split("&")[0]
                elif "youtu.be/" in url:
                    video_id = url.split("youtu.be/")[1].split("?")[0]
                
                if not video_id:
                    logger.warning(f"Не удалось извлечь ID видео из URL: {url}")
                    results.append({
                        "URL": url,
                        "Заголовок": "Ошибка: неверный формат URL",
                        "Дней с публикации": None,
                        "Просмотры": None,
                        "Канал URL": None,
                        "Ошибка": "Неверный формат URL"
                    })
                    continue
                
                # Формируем URL для запроса
                request_url = f"https://www.youtube.com/watch?v={video_id}"
                
                # Делаем запрос к странице видео
                response = requests.get(request_url, headers=headers, timeout=10)
                
                if response.status_code != 200:
                    logger.warning(f"Не удалось получить страницу видео, код: {response.status_code}")
                    results.append({
                        "URL": url,
                        "Заголовок": f"Ошибка: код {response.status_code}",
                        "Дней с публикации": None,
                        "Просмотры": None,
                        "Канал URL": None,
                        "Ошибка": f"Код ответа: {response.status_code}"
                    })
                    continue
                
                html_content = response.text
                
                # Извлекаем метаданные из ответа (два подхода)
                # 1. Через JSON-данные, встроенные в страницу
                try:
                    # Поиск JSON-данных в HTML
                    ytInitialData_match = re.search(r'ytInitialData\s*=\s*({.+?});</script>', html_content)
                    player_response_match = re.search(r'var ytInitialPlayerResponse\s*=\s*({.+?});</script>', html_content)
                    
                    title = None
                    views = None
                    publish_date = None
                    channel_url = None
                    
                    # Проверяем наличие данных о видео через ytInitialPlayerResponse
                    if player_response_match:
                        player_data = json.loads(player_response_match.group(1))
                        
                        # Извлекаем заголовок
                        if 'videoDetails' in player_data and 'title' in player_data['videoDetails']:
                            title = player_data['videoDetails']['title']
                        
                        # Извлекаем количество просмотров (как строку)
                        if 'videoDetails' in player_data and 'viewCount' in player_data['videoDetails']:
                            views_str = player_data['videoDetails']['viewCount']
                            views = int(views_str)
                        
                        # Извлекаем дату публикации
                        try:
                            if 'microformat' in player_data and 'playerMicroformatRenderer' in player_data['microformat']:
                                micro_format = player_data['microformat']['playerMicroformatRenderer']
                                if 'publishDate' in micro_format:
                                    publish_date_str = micro_format['publishDate']
                                    publish_date = datetime.strptime(publish_date_str, "%Y-%m-%d")
                                
                                # Извлекаем URL канала из microformat
                                if 'ownerProfileUrl' in micro_format:
                                    channel_url = micro_format['ownerProfileUrl']
                                    if not channel_url.startswith('http'):
                                        channel_url = 'https://www.youtube.com' + channel_url
                        except Exception as date_error:
                            logger.warning(f"Ошибка при обработке даты: {date_error}")
                    
                    # Если метаданные не найдены, используем альтернативный метод
                    if ytInitialData_match and (title is None or views is None or publish_date is None or channel_url is None):
                        data = json.loads(ytInitialData_match.group(1))
                        
                        # Извлекаем заголовок (если не найден ранее)
                        if title is None:
                            try:
                                video_primary_info = None
                                for renderer in data.get('contents', {}).get('twoColumnWatchNextResults', {}).get('results', {}).get('results', {}).get('contents', []):
                                    if 'videoPrimaryInfoRenderer' in renderer:
                                        video_primary_info = renderer['videoPrimaryInfoRenderer']
                                        break
                                
                                if video_primary_info and 'title' in video_primary_info:
                                    title_runs = video_primary_info['title'].get('runs', [])
                                    if title_runs:
                                        title = ''.join(run.get('text', '') for run in title_runs)
                            except Exception as title_error:
                                logger.warning(f"Ошибка при извлечении заголовка: {title_error}")
                        
                        # Извлекаем URL канала (если не найден ранее)
                        if channel_url is None:
                            try:
                                video_secondary_info = None
                                for renderer in data.get('contents', {}).get('twoColumnWatchNextResults', {}).get('results', {}).get('results', {}).get('contents', []):
                                    if 'videoSecondaryInfoRenderer' in renderer:
                                        video_secondary_info = renderer['videoSecondaryInfoRenderer']
                                        break
                                
                                if video_secondary_info and 'owner' in video_secondary_info:
                                    owner_info = video_secondary_info['owner'].get('videoOwnerRenderer', {})
                                    if 'navigationEndpoint' in owner_info:
                                        browse_endpoint = owner_info['navigationEndpoint'].get('browseEndpoint', {})
                                        if 'canonicalBaseUrl' in browse_endpoint:
                                            channel_url = 'https://www.youtube.com' + browse_endpoint['canonicalBaseUrl']
                                        elif 'browseId' in browse_endpoint:
                                            channel_url = f"https://www.youtube.com/channel/{browse_endpoint['browseId']}"
                            except Exception as channel_error:
                                logger.warning(f"Ошибка при извлечении URL канала: {channel_error}")
                        
                        # Извлекаем количество просмотров (если не найдено ранее)
                        if views is None:
                            try:
                                video_primary_info = None
                                for renderer in data.get('contents', {}).get('twoColumnWatchNextResults', {}).get('results', {}).get('results', {}).get('contents', []):
                                    if 'videoPrimaryInfoRenderer' in renderer:
                                        video_primary_info = renderer['videoPrimaryInfoRenderer']
                                        break
                                
                                if video_primary_info and 'viewCount' in video_primary_info:
                                    view_count_renderer = video_primary_info['viewCount'].get('videoViewCountRenderer', {})
                                    if 'viewCount' in view_count_renderer:
                                        views_text = view_count_renderer['viewCount'].get('simpleText', '')
                                        if not views_text and 'runs' in view_count_renderer['viewCount']:
                                            views_text = ''.join(run.get('text', '') for run in view_count_renderer['viewCount']['runs'])
                                        
                                        # Обработка строки с числом просмотров (форматы: "123 456 просмотров", "123,456 views", "1.2K views" и т.д.)
                                        views_str = re.sub(r'[^\d.,K]', '', views_text)
                                        
                                        # Обработка K, M, B суффиксов
                                        if 'K' in views_str or 'k' in views_str:
                                            views_str = views_str.replace('K', '').replace('k', '')
                                            views = int(float(views_str.replace(',', '.')) * 1000)
                                        elif 'M' in views_str or 'm' in views_str:
                                            views_str = views_str.replace('M', '').replace('m', '')
                                            views = int(float(views_str.replace(',', '.')) * 1000000)
                                        elif 'B' in views_str or 'b' in views_str:
                                            views_str = views_str.replace('B', '').replace('b', '')
                                            views = int(float(views_str.replace(',', '.')) * 1000000000)
                                        else:
                                            # Очищаем строку от разделителей
                                            views_str = views_str.replace(' ', '').replace(',', '')
                                            views = int(views_str) if views_str else 0
                            except Exception as views_error:
                                logger.warning(f"Ошибка при извлечении просмотров: {views_error}")
                    
                    # Если данные всё ещё не найдены, попробуем извлечь их из метатегов HTML
                    if title is None or views is None or publish_date is None:
                        # Извлекаем заголовок из метатегов
                        if title is None:
                            title_match = re.search(r'<meta\s+name="title"\s+content="([^"]+)"', html_content)
                            if title_match:
                                title = title_match.group(1)
                            else:
                                # Альтернативный поиск по og:title
                                title_match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html_content)
                                if title_match:
                                    title = title_match.group(1)
                        
                        # Поиск даты публикации
                        if publish_date is None:
                            date_match = re.search(r'<meta\s+itemprop="datePublished"\s+content="([^"]+)"', html_content)
                            if date_match:
                                publish_date_str = date_match.group(1)
                                try:
                                    if 'T' in publish_date_str:
                                        publish_date = datetime.strptime(publish_date_str.split('T')[0], "%Y-%m-%d")
                                    else:
                                        publish_date = datetime.strptime(publish_date_str, "%Y-%m-%d")
                                except Exception as e:
                                    logger.warning(f"Ошибка при парсинге даты публикации из метатегов: {e}")
                
                    # Расчет количества дней с момента публикации
                    days_since_publication = None
                    if publish_date:
                        days_since_publication = (datetime.now() - publish_date).days
                    
                    # Формируем запись для результата
                    result = {
                        "URL": url,
                        "Заголовок": title if title else "Нет заголовка",
                        "Дней с публикации": days_since_publication,
                        "Просмотры": views if views is not None else 0,
                        "Канал URL": channel_url,
                        "Ошибка": None
                    }
                    
                except Exception as extract_error:
                    logger.error(f"Ошибка при извлечении данных из JSON: {extract_error}")
                    # Резервный метод через регулярные выражения
                    try:
                        # Извлекаем заголовок
                        title_match = re.search(r'<title>([^<]+)</title>', html_content)
                        title = title_match.group(1).replace(' - YouTube', '') if title_match else "Нет заголовка"
                        
                        # Извлекаем URL канала
                        channel_url_match = re.search(r'<link itemprop="url" href="([^"]+)">', html_content) or re.search(r'<link rel="canonical" href="([^"]+)">', html_content)
                        channel_url = None
                        if channel_url_match:
                            channel_url_candidate = channel_url_match.group(1)
                            if "/channel/" in channel_url_candidate or "/c/" in channel_url_candidate or "/@" in channel_url_candidate:
                                channel_url = channel_url_candidate
                        
                        # Извлекаем количество просмотров с учетом разных форматов
                        views_match = re.search(r'"viewCount":\s*"(\d+)"', html_content)
                        views = int(views_match.group(1)) if views_match else 0
                        
                        if not views:
                            # Альтернативный поиск просмотров
                            views_match = re.search(r'(\d[\d\s,.]*)\s*просмотр', html_content) or \
                                        re.search(r'(\d[\d\s,.]*)\s*view', html_content)
                            if views_match:
                                views_str = views_match.group(1).replace(' ', '').replace(',', '')
                                views = int(views_str)
                        
                        # Извлекаем дату публикации
                        date_match = re.search(r'"publishDate":\s*"([^"]+)"', html_content)
                        publish_date = None
                        days_since_publication = None
                        
                        if date_match:
                            publish_date_str = date_match.group(1)
                            try:
                                publish_date = datetime.strptime(publish_date_str.split('T')[0], "%Y-%m-%d")
                                days_since_publication = (datetime.now() - publish_date).days
                            except Exception as date_error:
                                logger.warning(f"Ошибка при парсинге даты публикации: {date_error}")
                        
                        result = {
                            "URL": url,
                            "Заголовок": title,
                            "Дней с публикации": days_since_publication,
                            "Просмотры": views,
                            "Канал URL": channel_url,
                            "Ошибка": None
                        }
                        
                    except Exception as regex_error:
                        logger.error(f"Ошибка при извлечении данных через регулярные выражения: {regex_error}")
                        result = {
                            "URL": url,
                            "Заголовок": "Ошибка при извлечении данных",
                            "Дней с публикации": None,
                            "Просмотры": None,
                            "Канал URL": None,
                            "Ошибка": str(extract_error)
                        }
                
                results.append(result)
                
            except Exception as e:
                logger.error(f"Ошибка при анализе видео {url}: {e}")
                results.append({
                    "URL": url,
                    "Заголовок": "Ошибка",
                    "Дней с публикации": None,
                    "Просмотры": None,
                    "Канал URL": None,
                    "Ошибка": str(e)
                })
        
        # Создаем DataFrame с результатами
        df = pd.DataFrame(results)
        
        # Форматируем данные для читаемости
        try:
            if not df.empty:
                # Сохраняем оригинальные данные перед форматированием
                df["Просмотры_число"] = df["Просмотры"]
                
                # Форматируем количество просмотров для удобного отображения
                df["Просмотры"] = df["Просмотры"].apply(
                    lambda x: f"{x:,}".replace(",", " ") if pd.notna(x) else "—"
                )
                
                # Форматируем дни с публикации
                df["Дней с публикации"] = df["Дней с публикации"].apply(
                    lambda x: f"{int(x)}" if pd.notna(x) else "—"
                )
        except Exception as e:
            logger.warning(f"Ошибка при форматировании данных: {e}")
        
        logger.info(f"Тестирование параметров видео завершено. Проанализировано {len(results)} видео.")
        
        return df

    def render_video_tester_interface(self) -> str:
        """
        Создает HTML-разметку для веб-интерфейса тестирования параметров видео.
        
        Returns:
            str: HTML-код интерфейса тестирования
        """
        html = """
        <div class="video-tester-container" style="margin: 20px 0; border: 1px solid #ddd; border-radius: 6px; overflow: hidden;">
            <div class="video-tester-header" style="background-color: #f8f9fa; padding: 15px; cursor: pointer; border-bottom: 1px solid #ddd;" 
                 onclick="toggleVideoTester()">
                <h3 style="margin: 0; font-size: 18px; display: flex; align-items: center;">
                    <span id="video-tester-icon" style="margin-right: 10px;">▶</span>
                    Тестирование алгоритма сбора параметров видео
                </h3>
            </div>
            
            <div id="video-tester-content" style="display: none; padding: 20px; background-color: white;">
                <p style="margin-bottom: 15px; color: #666;">
                    Введите ссылки на YouTube видео (по одной в строке) для проверки точности алгоритма 
                    сбора данных. Для каждого видео будет показано количество дней с момента публикации 
                    и количество просмотров.
                </p>
                
                <div style="margin-bottom: 20px;">
                    <label for="video-urls" style="display: block; margin-bottom: 8px; font-weight: bold;">
                        Ссылки на YouTube видео:
                    </label>
                    <textarea id="video-urls" style="width: 100%; min-height: 100px; padding: 10px; border: 1px solid #ddd; border-radius: 4px; resize: vertical;"
                         placeholder="https://www.youtube.com/watch?v=..."></textarea>
                </div>
                
                <div style="display: flex; align-items: center; margin-bottom: 20px;">
                    <button id="test-videos-btn" style="padding: 8px 16px; background-color: #4285f4; color: white; border: none; border-radius: 4px; cursor: pointer;">
                        Проверить параметры
                    </button>
                    <div id="loader" style="display: none; margin-left: 15px;">
                        Анализ видео... <span style="display: inline-block; width: 16px; height: 16px; border: 3px solid #ddd; border-top: 3px solid #3498db; border-radius: 50%; animation: spin 1s linear infinite;"></span>
                    </div>
                </div>
                
                <div id="results-container" style="display: none;">
                    <h4 style="margin-top: 0; margin-bottom: 15px;">Результаты анализа:</h4>
                    <div id="results-table" style="overflow-x: auto;"></div>
                </div>
                
                <style>
                @keyframes spin {
                    0% { transform: rotate(0deg); }
                    100% { transform: rotate(360deg); }
                }
                #video-tester-content table {
                    width: 100%;
                    border-collapse: collapse;
                    margin-top: 10px;
                }
                #video-tester-content th, #video-tester-content td {
                    padding: 10px;
                    border: 1px solid #ddd;
                    text-align: left;
                }
                #video-tester-content th {
                    background-color: #f8f9fa;
                }
                #video-tester-content tr:nth-child(even) {
                    background-color: #f8f9fa;
                }
                #video-tester-content tr:hover {
                    background-color: #f2f2f2;
                }
                #video-tester-content .numeric {
                    text-align: right;
                }
                </style>
                
                <script>
                // Функция для открытия/закрытия блока тестирования
                function toggleVideoTester() {
                    const content = document.getElementById('video-tester-content');
                    const icon = document.getElementById('video-tester-icon');
                    
                    if (content.style.display === 'none') {
                        content.style.display = 'block';
                        icon.textContent = '▼';
                    } else {
                        content.style.display = 'none';
                        icon.textContent = '▶';
                    }
                }
                
                // Обработчик для кнопки тестирования
                document.getElementById('test-videos-btn').addEventListener('click', function() {
                    const urlsInput = document.getElementById('video-urls').value.trim();
                    if (!urlsInput) {
                        alert('Пожалуйста, введите хотя бы одну ссылку на YouTube видео');
                        return;
                    }
                    
                    // Разбиваем текст на строки и очищаем их
                    const urls = urlsInput.split('\\n')
                        .map(url => url.trim())
                        .filter(url => url.length > 0);
                    
                    // Проверяем на корректность URL
                    const youtubePattern = /^(https?:\\/\\/)?(www\\.)?(youtube\\.com\\/watch\\?v=|youtu\\.be\\/)([a-zA-Z0-9_-]{11}).*$/i;
                    const invalidUrls = urls.filter(url => !youtubePattern.test(url));
                    
                    if (invalidUrls.length > 0) {
                        alert('Следующие URL имеют некорректный формат:\\n' + invalidUrls.join('\\n'));
                        return;
                    }
                    
                    // Показываем индикатор загрузки
                    document.getElementById('loader').style.display = 'inline-block';
                    document.getElementById('results-container').style.display = 'none';
                    
                    // Делаем запрос на сервер
                    analyzeVideos(urls);
                });
                
                // Функция для анализа видео
                function analyzeVideos(urls) {
                    // В реальном приложении здесь был бы AJAX-запрос
                    // Имитируем задержку и получение данных
                    setTimeout(function() {
                        // Скрываем индикатор загрузки
                        document.getElementById('loader').style.display = 'none';
                        
                        // Имитация данных от сервера
                        const results = [];
                        for (let url of urls) {
                            results.push({
                                'URL': url,
                                'Заголовок': 'Заголовок будет получен при реальном запросе',
                                'Дней с публикации': '42', // Будет заменено реальными данными
                                'Просмотры': '123 456' // Будет заменено реальными данными
                            });
                        }
                        
                        // Создаем таблицу результатов
                        showResults(results);
                    }, 1500); // Имитация времени загрузки
                }
                
                // Функция для отображения результатов
                function showResults(results) {
                    const container = document.getElementById('results-container');
                    const tableContainer = document.getElementById('results-table');
                    
                    // Создаем таблицу
                    let tableHTML = '<table>';
                    
                    // Заголовок таблицы
                    tableHTML += '<thead><tr>';
                    tableHTML += '<th>URL</th>';
                    tableHTML += '<th>Заголовок</th>';
                    tableHTML += '<th class="numeric">Дней с публикации</th>';
                    tableHTML += '<th class="numeric">Просмотры</th>';
                    tableHTML += '</tr></thead>';
                    
                    // Тело таблицы
                    tableHTML += '<tbody>';
                    for (let result of results) {
                        tableHTML += '<tr>';
                        tableHTML += `<td><a href="${result.URL}" target="_blank">${result.URL}</a></td>`;
                        tableHTML += `<td>${result.Заголовок}</td>`;
                        tableHTML += `<td class="numeric">${result['Дней с публикации']}</td>`;
                        tableHTML += `<td class="numeric">${result.Просмотры}</td>`;
                        tableHTML += '</tr>';
                    }
                    tableHTML += '</tbody></table>';
                    
                    // Вставляем таблицу и показываем контейнер
                    tableContainer.innerHTML = tableHTML;
                    container.style.display = 'block';
                }
                </script>
            </div>
        </div>
        """
        return html

    def get_recommended_videos_fast(self, video_url: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Быстрый метод получения рекомендованных видео через HTTP-запросы без использования Selenium.
        
        Args:
            video_url (str): URL видео.
            limit (int): Максимальное количество рекомендованных видео для получения.
            
        Returns:
            List[Dict[str, Any]]: Список рекомендованных видео.
        """
        recommendations = []
        start_time = time.time()
        logger.info(f"Быстрое получение рекомендаций для видео: {video_url}")
        
        try:
            # Извлекаем ID видео из URL
            video_id = None
            if "youtube.com/watch?v=" in video_url:
                video_id = video_url.split("watch?v=")[1].split("&")[0]
            elif "youtu.be/" in video_url:
                video_id = video_url.split("youtu.be/")[1].split("?")[0]
            
            if not video_id:
                logger.warning(f"Не удалось извлечь ID видео из URL: {video_url}")
                return []
                
            # Формируем URL для запроса
            request_url = f"https://www.youtube.com/watch?v={video_id}"
            
            # Создаем headers для запроса
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
            }
            
            # Используем прокси, если настроен
            proxies = None
            if self.use_proxy and self.current_proxy:
                proxies = {
                    "http": self.current_proxy["http"],
                    "https": self.current_proxy["https"]
                }
            
            # Делаем запрос к странице видео
            logger.info(f"Отправка HTTP-запроса для получения страницы видео: {request_url}")
            response = requests.get(request_url, headers=headers, proxies=proxies, timeout=10)
            request_time = time.time() - start_time
            logger.info(f"Получен ответ за {request_time:.2f} сек, код: {response.status_code}")
            
            if response.status_code != 200:
                logger.warning(f"Ошибка при запросе страницы видео: {response.status_code}")
                return []
                
            # Получаем HTML-контент страницы
            html_content = response.text
            
            # Извлекаем рекомендации из HTML: два подхода
            # 1. Через регулярные выражения для поиска ссылок на видео
            video_urls = set()  # Используем множество для избежания дубликатов
            
            # Поиск ссылок на видео через регулярные выражения
            logger.info("Извлечение рекомендаций из HTML с помощью регулярных выражений")
            regex_start_time = time.time()
            
            # Ищем все URL видео в HTML
            url_patterns = [
                r'href=\"(/watch\?v=[^\"&]+)',  # Ссылки на видео в стандартном формате
                r'videoId\":\"([a-zA-Z0-9_-]{11})\"',  # ID видео в JSON-данных
                r'watchEndpoint\":{\"videoId\":\"([a-zA-Z0-9_-]{11})\"'  # ID видео в данных рекомендаций
            ]
            
            for pattern in url_patterns:
                matches = re.findall(pattern, html_content)
                for match in matches:
                    if len(match) == 11 and not match.startswith('/'):  # Прямой ID видео
                        full_url = f"https://www.youtube.com/watch?v={match}"
                        video_urls.add(full_url)
                    elif match.startswith('/watch?v='):  # Относительный URL
                        full_url = f"https://www.youtube.com{match}"
                        video_urls.add(full_url)
            
            # 2. Через JSON-данные, встроенные в страницу
            try:
                # Ищем ytInitialData, содержащий информацию о рекомендациях
                json_start_time = time.time()
                json_data_match = re.search(r'ytInitialData\s*=\s*({.+?});</script>', html_content)
                
                if json_data_match:
                    data = json.loads(json_data_match.group(1))
                    
                    # Извлекаем рекомендации из секции secondary results (справа от видео)
                    secondary_results = None
                    try:
                        secondary_results = data.get('contents', {}).get('twoColumnWatchNextResults', {}).get('secondaryResults', {})
                        if 'secondaryResults' in secondary_results:
                            secondary_results = secondary_results.get('secondaryResults', {})
                    except (KeyError, TypeError, AttributeError):
                        pass
                        
                    # Извлекаем данные рекомендаций
                    if secondary_results and 'results' in secondary_results:
                        results = secondary_results.get('results', [])
                        for result in results:
                            try:
                                # Проверяем разные форматы компонентов рекомендаций
                                if 'compactVideoRenderer' in result:
                                    video_id = result['compactVideoRenderer'].get('videoId')
                                    if video_id:
                                        title = None
                                        title_runs = result['compactVideoRenderer'].get('title', {}).get('runs', [])
                                        if title_runs:
                                            title = ''.join(run.get('text', '') for run in title_runs)
                                            
                                        full_url = f"https://www.youtube.com/watch?v={video_id}"
                                        if title:
                                            video_urls.add(full_url)
                                            recommendations.append({"url": full_url, "title": title})
                                        else:
                                            video_urls.add(full_url)
                            except Exception as item_error:
                                logger.warning(f"Ошибка при обработке элемента рекомендации: {item_error}")
                                continue
                    
                    json_time = time.time() - json_start_time
                    logger.info(f"Извлечение рекомендаций из JSON заняло {json_time:.2f} сек")
            except Exception as json_error:
                logger.warning(f"Ошибка при извлечении рекомендаций из JSON: {json_error}")
            
            # Для всех URL из регулярных выражений, которых нет в recommendations, добавляем их
            for url in video_urls:
                # Пропускаем текущее видео
                if url == video_url:
                    continue
                    
                # Пропускаем плейлисты и прямые эфиры
                if "list=" in url or "live" in url or "&t=" in url:
                    continue
                    
                # Проверяем, есть ли уже этот URL в рекомендациях
                if not any(rec.get("url") == url for rec in recommendations):
                    recommendations.append({"url": url})
            
            # Удаляем дубликаты, сохраняя порядок
            unique_recommendations = []
            seen_urls = set()
            for rec in recommendations:
                if rec["url"] not in seen_urls:
                    seen_urls.add(rec["url"])
                    unique_recommendations.append(rec)
            
            recommendations = unique_recommendations[:limit]
            
            total_time = time.time() - start_time
            logger.info(f"Быстрое получение рекомендаций заняло {total_time:.2f} сек, найдено {len(recommendations)} рекомендаций")
            
            return recommendations
            
        except Exception as e:
            total_time = time.time() - start_time
            logger.error(f"Ошибка при быстром получении рекомендаций для {video_url}: {e} (за {total_time:.2f} сек)")
            traceback.print_exc()
            return []

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
    
    for proxy_string in proxy_list:
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

# Пример использования
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="YouTube Scraper")
    parser.add_argument("--mode", choices=["proxy_test", "video_test"], 
                        default="proxy_test", help="Режим работы скрипта")
    parser.add_argument("--urls", nargs="+", help="Список URL для анализа видео")
    parser.add_argument("--render-html", action="store_true", help="Вывести HTML-интерфейс для тестирования")
    
    args = parser.parse_args()
    
    if args.mode == "proxy_test":
        # Пример списка прокси для проверки
        servers = [
            "185.241.70.43:8000:2e1U2g:Aju5tn",
            "213.139.218.40:8000:2e1U2g:Aju5tn",
            "213.139.218.131:8000:2e1U2g:Aju5tn"
        ]
        
        working_proxies = test_proxies(servers)
        
        # Вывод рабочих прокси для использования
        if working_proxies:
            print("\nРабочие прокси для использования:")
            for proxy in working_proxies:
                print(f"Сервер: {proxy['server']}, HTTP: {proxy['http']}")
        else:
            print("\nНе найдено рабочих прокси. Проверьте настройки или попробуйте другие серверы.")
    
    elif args.mode == "video_test":
        # Инициализируем анализатор
        analyzer = YouTubeAnalyzer(headless=True, use_proxy=False)
        
        # Если запрошен вывод HTML-интерфейса
        if args.render_html:
            # Выводим HTML-интерфейс для веб-приложения
            html_interface = analyzer.render_video_tester_interface()
            print(html_interface)
            analyzer.quit_driver()
            exit(0)
        
        # Тестирование параметров видео через консоль
        print("\n=== Тестирование алгоритма сбора параметров видео ===")
        
        # Если URL не указаны, используем тестовые
        if not args.urls:
            print("URL видео не указаны, используются тестовые примеры")
            test_urls = [
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",  # Известное видео Rick Astley
                "https://www.youtube.com/watch?v=jNQXAC9IVRw"   # Первое видео на YouTube
            ]
        else:
            test_urls = args.urls
            
        print(f"Анализируем {len(test_urls)} видео...")
        
        try:
            # Получаем и выводим результаты
            results_df = analyzer.test_video_parameters(test_urls)
            
            if not results_df.empty:
                # Выводим результаты в консоль
                print("\nРезультаты анализа параметров видео:")
                print("=" * 80)
                for _, row in results_df.iterrows():
                    print(f"URL: {row['URL']}")
                    print(f"Заголовок: {row['Заголовок']}")
                    print(f"Дней с публикации: {row['Дней с публикации']}")
                    print(f"Просмотры: {row['Просмотры']}")
                    if row['Ошибка']:
                        print(f"Ошибка: {row['Ошибка']}")
                    print("-" * 80)
            else:
                print("Не удалось получить данные о видео")
                
            # Закрываем драйвер
            analyzer.quit_driver()
            
        except Exception as e:
            print(f"Ошибка при анализе видео: {e}")
            import traceback
            traceback.print_exc()
    
    print("Работа скрипта завершена")