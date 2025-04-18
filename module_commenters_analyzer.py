import streamlit as st
import pandas as pd
import re
import logging
import time
import json
import traceback
from typing import List, Dict, Any, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
import requests
from bs4 import BeautifulSoup
from youtube_scraper import YouTubeAnalyzer
from collections import defaultdict

# Настройка логирования
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CommentersAnalyzer:
    """
    Класс для анализа комментаторов на YouTube видео.
    """
    
    def __init__(self, youtube_analyzer: Optional[YouTubeAnalyzer] = None):
        """
        Инициализация анализатора комментаторов.
        
        Args:
            youtube_analyzer (YouTubeAnalyzer, optional): Инициализированный анализатор YouTube.
        """
        self.youtube_analyzer = youtube_analyzer
        self.is_ready = youtube_analyzer is not None and youtube_analyzer.driver is not None

    def get_video_comments(self, video_url: str, max_comments: int = 100) -> List[Dict[str, Any]]:
        """
        Получает комментарии к видео с использованием Selenium.
        
        Args:
            video_url (str): URL видео для анализа
            max_comments (int): Максимальное количество комментариев для загрузки
            
        Returns:
            List[Dict[str, Any]]: Список словарей с данными о комментариях
        """
        if not self.is_ready or not self.youtube_analyzer.driver:
            logger.error("Драйвер не инициализирован. Невозможно получить комментарии.")
            return []
            
        comments = []
        driver = self.youtube_analyzer.driver
        
        try:
            # Открываем страницу видео
            logger.info(f"Открываем страницу видео: {video_url}")
            driver.get(video_url)
            
            # Ждем загрузки страницы и содержимого
            time.sleep(5)
            
            # Скроллим вниз, чтобы загрузить комментарии - используем более надежный метод
            logger.info("Скроллим к секции комментариев")
            try:
                # Сначала проверяем наличие секции комментариев
                comments_section_exists = driver.execute_script("""
                    return document.querySelector('#comments, ytd-comments, [id="comments"]') !== null;
                """)
                
                if comments_section_exists:
                    # Прокручиваем к комментариям, если секция существует
                    driver.execute_script("""
                        // Найдем секцию комментариев с учетом разных возможных селекторов
                        const commentsSection = document.querySelector('#comments, ytd-comments, [id="comments"]');
                        if (commentsSection) {
                            // Плавно прокрутим к элементу
                            commentsSection.scrollIntoView({behavior: 'smooth', block: 'center'});
                            return true;
                        }
                        // Если секция не найдена, прокрутим на фиксированное расстояние вниз
                        window.scrollBy(0, 800);
                        return false;
                    """)
                else:
                    # Если секция комментариев не найдена, просто прокручиваем вниз
                    logger.warning("Секция комментариев не найдена. Выполняем обычную прокрутку.")
                    driver.execute_script("window.scrollBy(0, 800);")
            except Exception as scroll_e:
                logger.warning(f"Ошибка при прокрутке к комментариям: {str(scroll_e)}. Пробуем альтернативный метод.")
                # Альтернативный метод прокрутки
                driver.execute_script("window.scrollBy(0, 800);")
            
            # Дополнительная задержка для загрузки комментариев
            time.sleep(3)
            
            # Проверяем, загрузились ли комментарии, используя несколько селекторов
            comment_loaded = False
            comment_selectors = [
                "ytd-comment-thread-renderer",
                "ytd-comment-renderer",
                ".comment-renderer",
                "[id^='comment-']",
                ".comment"
            ]
            
            for selector in comment_selectors:
                try:
                    comment_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if comment_elements:
                        comment_loaded = True
                        logger.info(f"Найдены комментарии с селектором: {selector}")
                        break
                    else:
                        logger.debug(f"Селектор {selector} не нашел комментариев")
                except Exception as e:
                    logger.debug(f"Ошибка при проверке селектора {selector}: {str(e)}")
            
            if not comment_loaded:
                logger.warning("Комментарии не загрузились. Возможно, они отключены для этого видео.")
                # Попробуем дополнительную прокрутку и ожидание
                try:
                    # Еще одна попытка прокрутки
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
                    time.sleep(3)
                    
                    # Ищем комментарии снова
                    for selector in comment_selectors:
                        comment_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        if comment_elements:
                            comment_loaded = True
                            logger.info(f"Найдены комментарии после дополнительной прокрутки с селектором: {selector}")
                            break
                except Exception as e:
                    logger.warning(f"Ошибка при дополнительной попытке загрузки комментариев: {str(e)}")
            
            if not comment_loaded:
                logger.warning("Не удалось загрузить комментарии после нескольких попыток.")
                return []
            
            # Скроллим для загрузки большего количества комментариев
            logger.info(f"Загружаем до {max_comments} комментариев")
            last_comments_count = 0
            retry_count = 0
            
            # Определяем селектор для комментариев, который сработал
            working_selector = next((s for s in comment_selectors if driver.find_elements(By.CSS_SELECTOR, s)), comment_selectors[0])
            
            while len(comments) < max_comments and retry_count < 5:
                # Получаем все доступные комментарии на странице
                comment_elements = driver.find_elements(By.CSS_SELECTOR, working_selector)
                
                # Перебираем комментарии, которые еще не обработали
                for i in range(last_comments_count, len(comment_elements)):
                    if len(comments) >= max_comments:
                        break
                        
                    try:
                        # Извлекаем данные о комментарии
                        comment_data = self._extract_comment_data(comment_elements[i])
                        if comment_data:
                            comments.append(comment_data)
                    except (StaleElementReferenceException, NoSuchElementException) as e:
                        logger.warning(f"Ошибка при извлечении данных комментария: {str(e)}")
                        continue
                
                # Проверяем, получили ли новые комментарии
                if len(comments) == last_comments_count:
                    retry_count += 1
                else:
                    retry_count = 0
                
                last_comments_count = len(comments)
                
                # Скроллим вниз для загрузки дополнительных комментариев
                try:
                    driver.execute_script("window.scrollBy(0, 1000);")
                    time.sleep(2)
                except Exception as scroll_e:
                    logger.warning(f"Ошибка при прокрутке для загрузки дополнительных комментариев: {str(scroll_e)}")
                    break
            
            logger.info(f"Загружено {len(comments)} комментариев")
            return comments
            
        except Exception as e:
            logger.error(f"Ошибка при получении комментариев: {str(e)}")
            logger.error(traceback.format_exc())
            return []
    
    def _extract_comment_data(self, comment_element) -> Dict[str, Any]:
        """
        Извлекает данные из элемента комментария.
        
        Args:
            comment_element: WebElement, содержащий комментарий
            
        Returns:
            Dict[str, Any]: Словарь с данными о комментарии
        """
        try:
            # Находим элемент с именем автора и ссылкой на канал - пробуем несколько селекторов
            channel_selectors = [
                "#author-text",
                ".comment-author-text",
                "a[href*='/channel/'], a[href*='/@']",
                ".yt-simple-endpoint[href*='/channel/'], .yt-simple-endpoint[href*='/@']",
                "#author-thumbnail"
            ]
            
            channel_name = ""
            channel_url = ""
            
            for selector in channel_selectors:
                try:
                    elements = comment_element.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        for element in elements:
                            # Проверяем, содержит ли элемент ссылку на канал
                            href = element.get_attribute("href")
                            if href and ('youtube.com/channel/' in href or 'youtube.com/@' in href):
                                channel_url = href
                                channel_name = element.text.strip()
                                if not channel_name:
                                    # Если текст пустой, пробуем получить его из атрибута
                                    channel_name = element.get_attribute("aria-label") or ""
                                break
                        
                        if channel_url:  # Если нашли ссылку, прекращаем поиск
                            break
                except (NoSuchElementException, StaleElementReferenceException):
                    continue
            
            # Если имя канала не найдено, но есть URL, извлекаем из URL
            if not channel_name and channel_url:
                username_match = re.search(r'@([^/]+)', channel_url)
                if username_match:
                    channel_name = '@' + username_match.group(1)
            
            # Если не удалось получить информацию через селекторы, попробуем через JavaScript
            if not channel_url:
                try:
                    # Используем JavaScript для извлечения информации о канале
                    channel_info = self.youtube_analyzer.driver.execute_script("""
                        var commentElement = arguments[0];
                        var authorElement = commentElement.querySelector('a[href*="/channel/"], a[href*="/@"], #author-text');
                        if (authorElement) {
                            return {
                                url: authorElement.href,
                                name: authorElement.textContent.trim()
                            };
                        }
                        return null;
                    """, comment_element)
                    
                    if channel_info:
                        channel_url = channel_info.get('url', '')
                        channel_name = channel_info.get('name', '')
                except Exception as js_e:
                    logger.warning(f"Ошибка при извлечении информации о канале через JavaScript: {str(js_e)}")
            
            # Возвращаем данные о комментарии
            if channel_url:
                return {
                    "channel_name": channel_name,
                    "channel_url": channel_url
                }
            return {}
        except (NoSuchElementException, StaleElementReferenceException) as e:
            logger.warning(f"Не удалось извлечь данные комментария: {str(e)}")
            return {}

    def get_channel_info(self, channel_url: str) -> Dict[str, Any]:
        """
        Получает информацию о канале через прямые HTTP-запросы.
        
        Args:
            channel_url (str): URL канала
            
        Returns:
            Dict[str, Any]: Словарь с данными о канале
        """
        try:
            # Проверяем наличие драйвера
            if not self.is_ready or not self.youtube_analyzer.driver:
                logger.error("Драйвер не инициализирован. Невозможно получить информацию о канале.")
                return {}
                
            # Открываем страницу канала
            driver = self.youtube_analyzer.driver
            logger.info(f"Открываем страницу канала: {channel_url}")
            driver.get(channel_url)
            time.sleep(5)  # Увеличиваем задержку для полной загрузки
            
            channel_name = "Канал YouTube"
            subscribers = 0
            has_videos = True  # По умолчанию предполагаем, что видео есть
            
            # Делаем скриншот и сохраняем HTML для отладки
            try:
                page_source = driver.page_source
                logger.debug(f"Длина HTML страницы: {len(page_source)}")
            except Exception as e:
                logger.error(f"Не удалось получить исходный код страницы: {str(e)}")
            
            # 1. ПОЛУЧЕНИЕ НАЗВАНИЯ КАНАЛА
            
            # Пробуем использовать заголовок страницы - самый надежный способ
            try:
                title = driver.title
                if " - YouTube" in title:
                    channel_name = title.replace(" - YouTube", "").strip()
                    # Удаляем префикс "(1) " или любые другие подобные префиксы
                    channel_name = re.sub(r'^\(\d+\)\s+', '', channel_name)
                    logger.info(f"Получено название канала из заголовка страницы: {channel_name}")
            except Exception as e:
                logger.warning(f"Не удалось получить заголовок страницы: {str(e)}")
            
            # Если не удалось получить из заголовка, пробуем CSS-селекторы
            if channel_name == "Канал YouTube":
                try:
                    # Используем JavaScript для получения названия канала
                    channel_name_js = driver.execute_script("""
                        // Различные селекторы для получения названия канала
                        const selectors = [
                            '#channel-name',
                            '#text-container ytd-channel-name yt-formatted-string',
                            '#channel-header ytd-channel-name #text',
                            '#inner-header-container ytd-channel-name',
                            // Мета-данные
                            'meta[property="og:title"]',
                            'meta[name="title"]'
                        ];
                        
                        // Пробуем каждый селектор
                        for (const selector of selectors) {
                            const element = document.querySelector(selector);
                            if (element) {
                                // Для мета-тегов
                                if (element.tagName === 'META') {
                                    return element.getAttribute('content');
                                }
                                // Для обычных элементов
                                return element.textContent.trim();
                            }
                        }
                        
                        // Возвращаем значение по умолчанию
                        return null;
                    """)
                    
                    if channel_name_js and channel_name_js != "null" and channel_name_js.strip():
                        channel_name = channel_name_js.strip()
                        logger.info(f"Получено название канала через JavaScript: {channel_name}")
                except Exception as e:
                    logger.warning(f"Не удалось получить название канала через JavaScript: {str(e)}")
            
            # Если все способы не сработали, извлекаем имя из URL
            if channel_name == "Канал YouTube":
                try:
                    username_match = re.search(r'@([^/]+)', channel_url)
                    if username_match:
                        channel_name = '@' + username_match.group(1)
                        logger.info(f"Получено название канала из URL: {channel_name}")
                except Exception as e:
                    logger.warning(f"Не удалось извлечь имя канала из URL: {str(e)}")
            
            # 2. ПОЛУЧЕНИЕ КОЛИЧЕСТВА ПОДПИСЧИКОВ
            
            try:
                # Прямой поиск элемента с числом подписчиков с помощью JavaScript
                subscriber_count_raw = driver.execute_script("""
                    // Прямой способ получения количества подписчиков
                    const subscriberElements = document.querySelectorAll('#subscriber-count');
                    if (subscriberElements.length > 0) {
                        return subscriberElements[0].textContent.trim();
                    }
                    
                    // Поиск элемента с подписчиками через атрибут "aria-label"
                    const elements = document.querySelectorAll('[aria-label*="подписчик"], [aria-label*="subscriber"]');
                    for (const element of elements) {
                        return element.getAttribute('aria-label');
                    }
                    
                    // Поиск по тексту в метаданных канала
                    const metaElements = document.querySelectorAll('#metadata-line, .metadata-stats, .ytd-channel-meta-info-renderer');
                    for (const element of metaElements) {
                        const text = element.textContent.trim();
                        if (text.includes('подписчик') || text.includes('subscriber')) {
                            return text;
                        }
                    }
                    
                    return "";
                """)
                
                if subscriber_count_raw:
                    logger.info(f"Найден текст с подписчиками: {subscriber_count_raw}")
                    
                    # Извлекаем числа из текста
                    num_pattern = r'([\d\s\.,]+)'
                    multiplier_pattern = r'(тыс|К|k|млн|М|m|млрд|Г|g|b)'
                    
                    num_match = re.search(num_pattern, subscriber_count_raw)
                    multiplier_match = re.search(multiplier_pattern, subscriber_count_raw, re.IGNORECASE)
                    
                    if num_match:
                        num_text = num_match.group(1).strip().replace(' ', '').replace(',', '.')
                        
                        try:
                            base_number = float(num_text)
                            
                            # Определяем множитель
                            multiplier = 1
                            if multiplier_match:
                                multiplier_text = multiplier_match.group(1).lower()
                                if multiplier_text in ['тыс', 'к', 'k']:
                                    multiplier = 1000
                                elif multiplier_text in ['млн', 'м', 'm']:
                                    multiplier = 1000000
                                elif multiplier_text in ['млрд', 'г', 'g', 'b']:
                                    multiplier = 1000000000
                            
                            subscribers = int(base_number * multiplier)
                            logger.info(f"Извлечено количество подписчиков: {subscribers}")
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Не удалось преобразовать число подписчиков: {str(e)}")
                
                # Если первый метод не сработал, пробуем второй подход
                if subscribers == 0:
                    # Используем менее прямой подход - парсим HTML страницы
                    page_source = driver.page_source
                    subscriber_patterns = [
                        r'(\d+[\d\s,.]*)\s*(?:тыс|K|k)?\s*(?:подписчик|subscriber)',
                        r'(?:подписчик|subscriber)[^<>\d]*([\d\s,.]+)',
                        r'(\d+[\d\s,.]*)\s*(?:тыс|K|k|млн|M|m)'
                    ]
                    
                    for pattern in subscriber_patterns:
                        sub_match = re.search(pattern, page_source, re.IGNORECASE)
                        if sub_match:
                            num_str = sub_match.group(1).strip().replace(' ', '').replace(',', '.')
                            try:
                                base_num = float(num_str)
                                # Проверяем наличие указателей на тысячи/миллионы в контексте
                                if 'тыс' in page_source[sub_match.start()-10:sub_match.end()+10].lower() or 'k' in page_source[sub_match.start()-10:sub_match.end()+10].lower():
                                    subscribers = int(base_num * 1000)
                                elif 'млн' in page_source[sub_match.start()-10:sub_match.end()+10].lower() or 'm' in page_source[sub_match.start()-10:sub_match.end()+10].lower():
                                    subscribers = int(base_num * 1000000)
                                else:
                                    subscribers = int(base_num)
                                    
                                logger.info(f"Извлечено количество подписчиков из HTML: {subscribers}")
                                break
                            except (ValueError, TypeError):
                                continue
            except Exception as e:
                logger.warning(f"Не удалось получить количество подписчиков: {str(e)}")
            
            # 3. ПРОВЕРКА НАЛИЧИЯ ВИДЕО
            
            try:
                # Ищем элементы видео на текущей странице
                video_elements = driver.find_elements(By.CSS_SELECTOR, "ytd-grid-video-renderer, ytd-rich-item-renderer, ytd-video-renderer")
                has_videos = len(video_elements) > 0
                
                # Если на текущей странице нет видео, проверяем наличие вкладки "Видео"
                if not has_videos:
                    # Проверяем, есть ли ссылка на раздел с видео
                    video_tab_elements = driver.find_elements(By.CSS_SELECTOR, "tp-yt-paper-tab, a[href*='/videos'], a[href*='?view=0']")
                    
                    for element in video_tab_elements:
                        element_text = element.text.lower()
                        if 'видео' in element_text or 'video' in element_text:
                            # Найдена вкладка "Видео" - пробуем перейти на нее
                            try:
                                element.click()
                                time.sleep(3)
                                # Проверяем наличие видео
                                video_elements = driver.find_elements(By.CSS_SELECTOR, "ytd-grid-video-renderer, ytd-rich-item-renderer, ytd-video-renderer")
                                has_videos = len(video_elements) > 0
                                break
                            except Exception as click_e:
                                logger.warning(f"Не удалось кликнуть на вкладку 'Видео': {str(click_e)}")
            except Exception as e:
                logger.warning(f"Не удалось проверить наличие видео: {str(e)}")
            
            # Возвращаем собранные данные
            channel_info = {
                "channel_url": channel_url,
                "channel_name": channel_name.strip(),  # Дополнительно очищаем название от лишних пробелов
                "subscribers": subscribers,
                "has_videos": has_videos
            }
            
            logger.info(f"Данные канала: {json.dumps(channel_info, ensure_ascii=False)}")
            return channel_info
                
        except Exception as e:
            logger.error(f"Ошибка при получении информации о канале {channel_url}: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                "channel_url": channel_url,
                "channel_name": "Канал YouTube",
                "subscribers": 0,
                "has_videos": True
            }
    
    def _extract_channel_id(self, channel_url: str) -> Optional[str]:
        """
        Извлекает ID канала из URL.
        
        Args:
            channel_url (str): URL канала
            
        Returns:
            Optional[str]: ID канала или None, если не удалось извлечь
        """
        # Для работы через прямые HTTP-запросы не требуется извлекать channel_id
        # Возвращаем полный URL канала
        return channel_url

    def get_channel_info_http(self, channel_url: str) -> Dict[str, Any]:
        """
        Получает информацию о канале через прямые HTTP-запросы (без Selenium).
        
        Args:
            channel_url (str): URL канала
            
        Returns:
            Dict[str, Any]: Словарь с данными о канале
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8'
            }
            
            # Отправляем запрос на страницу канала
            response = requests.get(channel_url, headers=headers)
            if response.status_code != 200:
                logger.warning(f"Ошибка HTTP при запросе данных канала: {response.status_code}")
                return {}
                
            # Используем BeautifulSoup для парсинга HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Пытаемся найти название канала
            channel_name = ""
            channel_name_tag = soup.select_one('meta[property="og:title"]')
            if channel_name_tag and channel_name_tag.get('content'):
                channel_name = channel_name_tag['content']
            
            # Для более подробной информации требуется Selenium,
            # так как на YouTube используется JavaScript для загрузки данных
            
            return {
                "channel_url": channel_url,
                "channel_name": channel_name,
                "subscribers": 0,  # Невозможно надежно получить через обычный HTTP запрос
                "has_videos": True  # По умолчанию предполагаем, что видео есть
            }
            
        except Exception as e:
            logger.error(f"Ошибка при получении информации о канале через HTTP {channel_url}: {str(e)}")
            logger.error(traceback.format_exc())
            return {}

    def check_channel_relevance(self, channel_info: Dict[str, Any]) -> bool:
        """
        Проверяет, соответствует ли канал критериям поиска.
        
        Args:
            channel_info (Dict[str, Any]): Информация о канале
            
        Returns:
            bool: True, если канал соответствует критериям, иначе False
        """
        # Проверяем наличие видео на канале
        if channel_info.get("has_videos", False):
            return True
            
        # Проверяем, содержит ли название канала ключевые слова
        keywords = ["revenge", "stories", "story", "reddit", "tale"]
        channel_name = channel_info.get("channel_name", "").lower()
        
        for keyword in keywords:
            if keyword.lower() in channel_name:
                return True
                
        return False
        
    def analyze_video_commenters(self, video_urls: List[str], max_comments_per_video: int = 100) -> pd.DataFrame:
        """
        Анализирует комментаторов для списка видео.
        
        Args:
            video_urls (List[str]): Список URL видео для анализа
            max_comments_per_video (int): Максимальное количество комментариев для загрузки с каждого видео
            
        Returns:
            pd.DataFrame: Таблица с данными о релевантных комментаторах
        """
        if not self.is_ready:
            logger.error("Анализатор не готов к работе. Необходимо инициализировать драйвер.")
            return pd.DataFrame()
            
        all_commenters = {}  # Словарь для хранения уникальных комментаторов
        
        # Перебираем все видео
        for video_url in video_urls:
            try:
                logger.info(f"Анализируем комментарии к видео: {video_url}")
                
                # Получаем комментарии
                comments = self.get_video_comments(video_url, max_comments_per_video)
                
                # Перебираем комментарии и собираем данные о каналах
                for comment in comments:
                    channel_url = comment.get("channel_url")
                    if not channel_url or channel_url in all_commenters:
                        continue
                        
                    # Получаем информацию о канале
                    channel_info = self.get_channel_info(channel_url)
                    
                    # Проверяем соответствие критериям
                    if channel_info and self.check_channel_relevance(channel_info):
                        all_commenters[channel_url] = channel_info
                        
                        # Логируем найденный релевантный канал
                        logger.info(f"Найден релевантный канал: {channel_info.get('channel_name')} ({channel_url})")
                    
                    # Небольшая задержка между запросами к API
                    time.sleep(0.2)
                
            except Exception as e:
                logger.error(f"Ошибка при анализе комментариев видео {video_url}: {str(e)}")
                logger.error(traceback.format_exc())
                continue
        
        # Преобразуем словарь в DataFrame
        if all_commenters:
            result_df = pd.DataFrame(list(all_commenters.values()))
            # Оставляем только нужные колонки
            if not result_df.empty:
                result_df = result_df[["channel_url", "channel_name", "subscribers"]]
                # Сортируем по числу подписчиков (по убыванию)
                result_df = result_df.sort_values(by="subscribers", ascending=False)
            
            return result_df
        else:
            return pd.DataFrame(columns=["channel_url", "channel_name", "subscribers"])


def render_commenters_analyzer_section():
    """
    Отображает раздел анализа комментаторов YouTube.
    """
    st.header("Анализ комментаторов YouTube")
    
    st.write("""
    Этот раздел анализирует комментарии к YouTube-видео и находит каналы, которые соответствуют заданным критериям:
    - Каналы, на которых опубликовано хотя бы одно видео
    - Каналы, в названии которых есть одно из слов: revenge, stories, story, reddit, tale (без учёта регистра)
    """)
    
    # Проверяем, авторизован ли пользователь
    is_logged_in = st.session_state.get("is_logged_in", False)
    
    if not is_logged_in:
        st.warning("⚠️ Для работы с YouTube необходимо авторизоваться во вкладке 'Авторизация в Google'")
        return
    
    # Проверяем наличие API ключа
    youtube_api_key = st.session_state.get("youtube_api_key", "")
    if not youtube_api_key:
        st.warning("⚠️ API ключ YouTube не найден. Пожалуйста, добавьте его во вкладке 'Тест API каналов'")
        return
    
    # Поле для ввода ссылок на видео
    video_urls_input = st.text_area(
        "Введите ссылки на YouTube-видео (по одной в строке)",
        height=150,
        help="Вставьте ссылки на YouTube-видео, комментаторов которых нужно проанализировать. Каждая ссылка должна быть на новой строке."
    )
    
    # Настройка параметров анализа
    with st.expander("Настройка параметров анализа", expanded=False):
        max_comments_per_video = st.slider(
            "Максимальное количество комментариев для анализа с каждого видео",
            min_value=10,
            max_value=500,
            value=100,
            step=10,
            help="Большее количество комментариев даст более полные результаты, но анализ займет больше времени."
        )

    # Кнопка для запуска анализа
    analyze_button = st.button("🔍 Запустить анализ", disabled=not video_urls_input)
    
    if analyze_button and video_urls_input:
        # Парсим ссылки на видео
        video_urls = [url.strip() for url in video_urls_input.split('\n') if url.strip()]
        
        # Удаляем дубликаты и проверяем корректность ссылок
        valid_urls = []
        for url in video_urls:
            if 'youtube.com/watch?v=' in url or 'youtu.be/' in url:
                valid_urls.append(url)
        
        if not valid_urls:
            st.error("❌ Не найдено корректных ссылок на YouTube-видео. Проверьте ввод.")
            return
            
        st.info(f"Найдено {len(valid_urls)} видео для анализа. Начинаем сбор данных...")
        
        # Получаем анализатор YouTube из сессии
        auth_analyzer = st.session_state.get("auth_analyzer")
        
        if not auth_analyzer or not auth_analyzer.driver:
            st.error("❌ Отсутствует инициализированный драйвер браузера. Пожалуйста, перезагрузите страницу и выполните авторизацию заново.")
            return
        
        # Создаем анализатор комментаторов
        commenters_analyzer = CommentersAnalyzer(auth_analyzer)
        
        # Запускаем анализ с отображением прогресса
        with st.spinner("Анализируем комментаторов... Это может занять некоторое время."):
            progress_bar = st.progress(0)
            
            # Анализируем комментаторов для каждого видео с отображением прогресса
            all_commenters = {}  # Словарь для хранения всех комментаторов
            comments_count = defaultdict(int)  # Счетчик комментариев для каждого канала
            video_count = defaultdict(set)  # Множество видео, где встречается каждый канал
            
            for i, video_url in enumerate(valid_urls):
                # Обновляем прогресс-бар
                progress = (i + 1) / len(valid_urls)
                progress_bar.progress(progress)
                
                # Отображаем текущее видео
                st.info(f"Анализируем комментарии к видео {i+1} из {len(valid_urls)}: {video_url}")
                
                # Получаем комментарии
                comments = commenters_analyzer.get_video_comments(video_url, max_comments_per_video)
                
                # Обрабатываем комментарии
                for comment in comments:
                    channel_url = comment.get("channel_url")
                    if not channel_url:
                        continue
                    
                    # Увеличиваем счетчик комментариев
                    comments_count[channel_url] += 1
                    
                    # Добавляем видео в множество
                    video_count[channel_url].add(video_url)
                    
                    # Если канал уже обработан, пропускаем получение информации
                    if channel_url in all_commenters:
                        continue
                        
                    # Получаем информацию о канале
                    channel_info = commenters_analyzer.get_channel_info(channel_url)
                    
                    # Проверяем соответствие критериям
                    if channel_info and commenters_analyzer.check_channel_relevance(channel_info):
                        all_commenters[channel_url] = channel_info
                        # Логируем найденный релевантный канал с полной информацией
                        logger.info(f"Найден релевантный канал: {channel_info.get('channel_name', 'Неизвестно')} ({channel_url}), подписчиков: {channel_info.get('subscribers', 0)}")
                    
                    # Небольшая задержка между запросами
                    time.sleep(0.2)
            
            # Преобразуем словарь в DataFrame
            if all_commenters:
                # Преобразуем данные в список словарей для DataFrame
                commenters_data = []
                for channel_url, info in all_commenters.items():
                    # Создаем строку о комментариях в формате "5 комментариев под 4 видео"
                    comments_info = f"{comments_count[channel_url]} комментариев под {len(video_count[channel_url])} видео"
                    
                    commenters_data.append({
                        "channel_url": channel_url,
                        "channel_name": info.get("channel_name", "Неизвестно"),
                        "subscribers": info.get("subscribers", 0),
                        "comments_info": comments_info
                    })
                
                # Создаем DataFrame
                result_df = pd.DataFrame(commenters_data)
                
                # Сортируем по числу подписчиков (по убыванию)
                result_df = result_df.sort_values(by="subscribers", ascending=False)
                
                # Отображаем результаты
                st.success(f"✅ Анализ завершен! Найдено {len(result_df)} релевантных каналов.")
                
                # Убеждаемся, что в DataFrame есть необходимые колонки
                required_columns = ["channel_url", "channel_name", "subscribers", "comments_info"]
                for col in required_columns:
                    if col not in result_df.columns:
                        result_df[col] = "Н/Д"  # Добавляем отсутствующие колонки
                
                # Отображаем данные в таблице
                st.dataframe(result_df[required_columns], use_container_width=True)
                
                # Добавляем возможность скачать результаты в CSV
                csv = result_df.to_csv(index=False).encode('utf-8')
                
                # Добавляем возможность скачать результаты в TSV
                tsv = result_df.to_csv(index=False, sep='\t').encode('utf-8')
                
                # Кнопки для скачивания
                col1, col2 = st.columns(2)
                with col1:
                    st.download_button(
                        label="📥 Скачать результаты (CSV)",
                        data=csv,
                        file_name="youtube_commenters_analysis.csv",
                        mime="text/csv"
                    )
                with col2:
                    st.download_button(
                        label="📥 Скачать результаты (TSV)",
                        data=tsv,
                        file_name="youtube_commenters_analysis.tsv",
                        mime="text/tab-separated-values"
                    )
            else:
                st.warning("⚠️ Не найдено релевантных каналов, соответствующих критериям.") 