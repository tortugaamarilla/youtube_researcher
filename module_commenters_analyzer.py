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
            
            # Ждем загрузки страницы - уменьшаем время ожидания
            time.sleep(3)  # Было 5, уменьшаем до 3 секунд
            
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
                            // Прокручиваем к элементу (без плавной анимации для ускорения)
                            commentsSection.scrollIntoView({block: 'center'});
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
            
            # Дополнительная задержка для загрузки комментариев - уменьшаем
            time.sleep(2)  # Было 3, уменьшаем до 2 секунд
            
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
                    time.sleep(2)  # Было 3, уменьшаем до 2 секунд
                    
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
            
            # Оптимизированное извлечение комментариев через JavaScript
            # Это гораздо быстрее, чем перебирать элементы через Selenium
            try:
                comments_data = driver.execute_script("""
                    // Функция для получения URL и имени канала комментатора
                    function extractCommentatorInfo(commentElement) {
                        const authorElement = commentElement.querySelector('a[href*="/channel/"], a[href*="/@"], #author-text');
                        if (!authorElement) return null;
                        
                        return {
                            channel_url: authorElement.href,
                            channel_name: authorElement.textContent.trim() || authorElement.getAttribute('aria-label') || ""
                        };
                    }
                    
                    // Находим все комментарии на странице
                    const commentElements = document.querySelectorAll("ytd-comment-thread-renderer, ytd-comment-renderer, .comment-renderer, [id^='comment-'], .comment");
                    
                    // Ограничиваем количество комментариев
                    const maxComments = arguments[0];
                    const results = [];
                    
                    // Извлекаем данные о комментариях
                    for (let i = 0; i < Math.min(commentElements.length, maxComments); i++) {
                        const info = extractCommentatorInfo(commentElements[i]);
                        if (info && info.channel_url) {
                            results.push(info);
                        }
                    }
                    
                    // Возвращаем данные
                    return results;
                """, max_comments)
                
                if comments_data and isinstance(comments_data, list):
                    logger.info(f"Успешно извлечено {len(comments_data)} комментариев через JavaScript")
                    return comments_data
                
                logger.warning("JavaScript извлечение комментариев не вернуло данные, используем запасной метод")
            except Exception as js_e:
                logger.warning(f"Ошибка при извлечении комментариев через JavaScript: {str(js_e)}. Используем запасной метод.")
            
            # Запасной метод - скроллинг и извлечение комментариев через Selenium
            # Скроллим для загрузки большего количества комментариев
            logger.info(f"Загружаем до {max_comments} комментариев")
            last_comments_count = 0
            retry_count = 0
            
            # Определяем селектор для комментариев, который сработал
            working_selector = next((s for s in comment_selectors if driver.find_elements(By.CSS_SELECTOR, s)), comment_selectors[0])
            
            while len(comments) < max_comments and retry_count < 3:  # Уменьшаем количество попыток с 5 до 3
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
                    time.sleep(1)  # Уменьшаем задержку с 2 до 1 секунды
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
            time.sleep(3)  # Уменьшаем задержку с 5 до 3 секунд
            
            channel_name = "Канал YouTube"
            subscribers = 0
            has_videos = True  # По умолчанию предполагаем, что видео есть
            video_count = 0  # Количество видео на канале
            
            # Оптимизированное извлечение данных канала через JavaScript в одном запросе
            try:
                channel_data = driver.execute_script("""
                    // Функция для извлечения числа из строки с учетом множителей (тыс, млн)
                    function extractNumber(text) {
                        if (!text) return 0;
                        
                        const numMatch = text.match(/([\d\s,.]+)/);
                        if (!numMatch) return 0;
                        
                        let num = parseFloat(numMatch[1].replace(/\\s/g, '').replace(',', '.'));
                        
                        // Проверяем наличие множителей
                        if (text.match(/тыс|К|k/i)) {
                            return Math.round(num * 1000);
                        } else if (text.match(/млн|М|m/i)) {
                            return Math.round(num * 1000000);
                        } else if (text.match(/млрд|Г|g|b/i)) {
                            return Math.round(num * 1000000000);
                        }
                        
                        return Math.round(num);
                    }
                    
                    // Получаем название канала
                    let channelName = "";
                    // Пробуем заголовок страницы
                    if (document.title && document.title.includes(" - YouTube")) {
                        channelName = document.title.replace(" - YouTube", "").trim();
                        channelName = channelName.replace(/^\\(\\d+\\)\\s+/, ''); // Удаляем префикс "(1) "
                    }
                    
                    // Если не вышло, ищем другие элементы
                    if (!channelName || channelName === "YouTube") {
                        const selectors = [
                            '#channel-name',
                            '#text-container ytd-channel-name yt-formatted-string',
                            '#channel-header ytd-channel-name #text',
                            '#inner-header-container ytd-channel-name',
                            'meta[property="og:title"]',
                            'meta[name="title"]'
                        ];
                        
                        for (const selector of selectors) {
                            const element = document.querySelector(selector);
                            if (element) {
                                if (element.tagName === 'META') {
                                    channelName = element.getAttribute('content');
                                } else {
                                    channelName = element.textContent.trim();
                                }
                                if (channelName) break;
                            }
                        }
                    }
                    
                    // Получаем число подписчиков
                    let subscriberCount = 0;
                    let subscriberText = "";
                    
                    // Прямой поиск элемента с числом подписчиков
                    const subscriberElement = document.querySelector('#subscriber-count');
                    if (subscriberElement) {
                        subscriberText = subscriberElement.textContent.trim();
                    } else {
                        // Ищем через aria-label
                        const elements = document.querySelectorAll('[aria-label*="подписчик"], [aria-label*="subscriber"]');
                        for (const element of elements) {
                            subscriberText = element.getAttribute('aria-label');
                            if (subscriberText) break;
                        }
                        
                        // Ищем в метаданных
                        if (!subscriberText) {
                            const metaElements = document.querySelectorAll('#metadata-line, .metadata-stats, .ytd-channel-meta-info-renderer');
                            for (const element of metaElements) {
                                const text = element.textContent.trim();
                                if (text.includes('подписчик') || text.includes('subscriber')) {
                                    subscriberText = text;
                                    break;
                                }
                            }
                        }
                    }
                    
                    if (subscriberText) {
                        subscriberCount = extractNumber(subscriberText);
                    }
                    
                    // Проверяем наличие видео и их количество
                    const videoElements = document.querySelectorAll("ytd-grid-video-renderer, ytd-rich-item-renderer, ytd-video-renderer");
                    const hasVideos = videoElements.length > 0;
                    let videoCount = 0;
                    
                    // Ищем счетчик видео
                    let videoCountText = "";
                    
                    // Проверка элементов с метаданными
                    const metaElements = document.querySelectorAll('.ytd-channel-meta, #metadata, #stats, .ytd-channel-about-metadata-renderer');
                    for (const element of metaElements) {
                        const text = element.textContent.trim();
                        if (text.includes('видео') || text.includes('video')) {
                            videoCountText = text;
                            break;
                        }
                    }
                    
                    // Проверка числа видео в заголовках вкладок
                    if (!videoCountText) {
                        const tabElements = document.querySelectorAll('tp-yt-paper-tab, [role="tab"]');
                        for (const tab of tabElements) {
                            const text = tab.textContent.trim();
                            if ((text.includes('Видео') || text.includes('Videos')) && /\\d+/.test(text)) {
                                videoCountText = text;
                                break;
                            }
                        }
                    }
                    
                    // Счетчики видео в других местах
                    if (!videoCountText) {
                        const counterElements = document.querySelectorAll('[id*="video-count"], [class*="video-count"], [aria-label*="видео"], [aria-label*="video"]');
                        for (const counter of counterElements) {
                            videoCountText = counter.textContent.trim() || counter.getAttribute('aria-label');
                            if (videoCountText) break;
                        }
                    }
                    
                    // Если нашли текст с количеством видео, извлекаем число
                    if (videoCountText) {
                        videoCount = extractNumber(videoCountText);
                    } else if (hasVideos) {
                        // Если не нашли счетчик, но видео есть, используем количество на странице
                        videoCount = videoElements.length;
                    }
                    
                    // Если видео есть, но счетчик показывает 0, ставим минимум 1
                    if (hasVideos && videoCount === 0) {
                        videoCount = 1;
                    }
                    
                    // Возвращаем собранные данные
                    return {
                        channel_name: channelName.trim(),
                        subscribers: subscriberCount,
                        has_videos: hasVideos,
                        video_count: videoCount
                    };
                """)
                
                if channel_data and isinstance(channel_data, dict):
                    channel_name = channel_data.get("channel_name", "Канал YouTube")
                    subscribers = channel_data.get("subscribers", 0)
                    has_videos = channel_data.get("has_videos", True)
                    video_count = channel_data.get("video_count", 0)
                    
                    logger.info(f"Успешно получены данные канала через JavaScript: {json.dumps(channel_data, ensure_ascii=False)}")
                else:
                    logger.warning("JavaScript извлечение данных канала не вернуло корректных данных, используем запасной метод")
            except Exception as js_e:
                logger.warning(f"Ошибка при извлечении данных канала через JavaScript: {str(js_e)}. Используем запасной метод.")
            
            # Если какие-то данные не удалось получить через JavaScript, используем запасные методы
            
            # 1. НАЗВАНИЕ КАНАЛА - если не получили через JavaScript
            if channel_name == "Канал YouTube":
                try:
                    title = driver.title
                    if " - YouTube" in title:
                        channel_name = title.replace(" - YouTube", "").strip()
                        # Удаляем префикс "(1) " или любые другие подобные префиксы
                        channel_name = re.sub(r'^\(\d+\)\s+', '', channel_name)
                        logger.info(f"Получено название канала из заголовка страницы: {channel_name}")
                
                    # Если все способы не сработали, извлекаем имя из URL
                    if channel_name == "Канал YouTube":
                        username_match = re.search(r'@([^/]+)', channel_url)
                        if username_match:
                            channel_name = '@' + username_match.group(1)
                            logger.info(f"Получено название канала из URL: {channel_name}")
                except Exception as e:
                    logger.warning(f"Не удалось получить название канала через запасные методы: {str(e)}")
            
            # 3. ПРОВЕРКА НАЛИЧИЯ ВИДЕО И ПОЛУЧЕНИЕ ИХ КОЛИЧЕСТВА - если не получили через JavaScript
            if video_count == 0 and not has_videos:
                try:
                    # Проверяем, есть ли ссылка на раздел с видео
                    video_tab_elements = driver.find_elements(By.CSS_SELECTOR, "tp-yt-paper-tab, a[href*='/videos'], a[href*='?view=0']")
                    
                    for element in video_tab_elements:
                        element_text = element.text.lower()
                        if 'видео' in element_text or 'video' in element_text:
                            # Найдена вкладка "Видео" - пробуем перейти на нее
                            try:
                                element.click()
                                time.sleep(2)  # Уменьшаем задержку с 3 до 2 секунд
                                # Проверяем наличие видео
                                video_elements = driver.find_elements(By.CSS_SELECTOR, "ytd-grid-video-renderer, ytd-rich-item-renderer, ytd-video-renderer")
                                has_videos = len(video_elements) > 0
                                
                                # Если нашли видео, но счетчик все еще 0, используем количество на странице
                                if has_videos and video_count == 0:
                                    video_count = len(video_elements)
                                    logger.info(f"Используем количество видео на странице после перехода на вкладку: {video_count}")
                                
                                break
                            except Exception as click_e:
                                logger.warning(f"Не удалось кликнуть на вкладку 'Видео': {str(click_e)}")
                except Exception as e:
                    logger.warning(f"Не удалось проверить наличие видео через запасные методы: {str(e)}")
            
            # Если видео не найдены, но на вкладку удалось перейти, проверяем текст на странице
            if has_videos and video_count == 0:
                video_count = 1  # Предполагаем как минимум 1 видео, если has_videos == True
            
            # Возвращаем собранные данные
            channel_info = {
                "channel_url": channel_url,
                "channel_name": channel_name.strip(),  # Дополнительно очищаем название от лишних пробелов
                "subscribers": subscribers,
                "has_videos": has_videos,
                "video_count": video_count
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
                "has_videos": True,
                "video_count": 0
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

    def check_channel_relevance(self, channel_info: Dict[str, Any], min_videos: int = 1, keywords: List[str] = None) -> bool:
        """
        Проверяет, соответствует ли канал критериям поиска.
        
        Args:
            channel_info (Dict[str, Any]): Информация о канале
            min_videos (int): Минимальное число видео, опубликованное на канале
            keywords (List[str], optional): Список ключевых слов для проверки названия канала
            
        Returns:
            bool: True, если канал соответствует критериям, иначе False
        """
        # Используем стандартные ключевые слова, если не переданы
        if keywords is None:
            keywords = ["revenge", "stories", "story", "reddit", "tale"]
            
        # Проверяем наличие достаточного количества видео на канале
        video_count = channel_info.get("video_count", 0)
        if video_count >= min_videos:
            return True
            
        # Проверяем, содержит ли название канала ключевые слова
        channel_name = channel_info.get("channel_name", "").lower()
        
        for keyword in keywords:
            if keyword.lower() in channel_name:
                return True
                
        return False
        
    def analyze_video_commenters(self, video_urls: List[str], max_comments_per_video: int = 100, min_videos: int = 1, keywords: List[str] = None) -> pd.DataFrame:
        """
        Анализирует комментаторов для списка видео.
        
        Args:
            video_urls (List[str]): Список URL видео для анализа
            max_comments_per_video (int): Максимальное количество комментариев для загрузки с каждого видео
            min_videos (int): Минимальное число видео на канале комментатора
            keywords (List[str], optional): Список ключевых слов для проверки названия канала
            
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
                    if channel_info and self.check_channel_relevance(channel_info, min_videos, keywords):
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

    def get_video_comments_api(self, video_url: str, max_comments: int = 100, api_key: str = None) -> List[Dict[str, Any]]:
        """
        Получает комментарии к видео через YouTube Data API.
        
        Args:
            video_url (str): URL видео для анализа
            max_comments (int): Максимальное количество комментариев для загрузки
            api_key (str): Ключ API YouTube
            
        Returns:
            List[Dict[str, Any]]: Список словарей с данными о комментариях
        """
        if not api_key:
            logger.error("Не указан API ключ для получения комментариев.")
            return []
            
        comments = []
        
        try:
            # Извлекаем ID видео из URL
            video_id = None
            if "youtube.com/watch?v=" in video_url:
                video_id = video_url.split("watch?v=")[1].split("&")[0]
            elif "youtu.be/" in video_url:
                video_id = video_url.split("youtu.be/")[1].split("?")[0]
                
            if not video_id:
                logger.error(f"Не удалось извлечь ID видео из URL: {video_url}")
                return []
                
            # Формируем URL для запроса комментариев
            comments_url = "https://www.googleapis.com/youtube/v3/commentThreads"
            params = {
                "part": "snippet,replies",
                "videoId": video_id,
                "maxResults": 100,  # Максимально возможное значение для одного запроса
                "key": api_key
            }
            
            # Запрашиваем комментарии через API
            total_comments = 0
            next_page_token = None
            
            logger.info(f"Запрашиваем комментарии для видео {video_id} через API")
            
            while total_comments < max_comments:
                # Добавляем токен следующей страницы, если есть
                if next_page_token:
                    params["pageToken"] = next_page_token
                
                # Делаем запрос
                response = requests.get(comments_url, params=params)
                
                # Проверяем успешность запроса
                if response.status_code != 200:
                    logger.error(f"Ошибка API при получении комментариев: {response.status_code}")
                    logger.error(f"Ответ API: {response.text}")
                    
                    # Проверяем, не исчерпана ли квота
                    if "quota" in response.text.lower():
                        logger.error("Превышен лимит квоты API.")
                        # Сохраняем ошибку для внешнего обработчика
                        if hasattr(self, 'youtube_analyzer'):
                            self.youtube_analyzer.last_api_error = "quotaExceeded"
                    
                    break
                
                # Получаем данные из ответа
                data = response.json()
                
                # Обрабатываем комментарии
                items = data.get("items", [])
                
                if not items:
                    logger.info("Комментарии не найдены или их больше нет.")
                    break
                    
                # Извлекаем информацию о комментаторах
                for item in items:
                    snippet = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
                    
                    if snippet:
                        channel_name = snippet.get("authorDisplayName", "")
                        channel_url = snippet.get("authorChannelUrl", "")
                        
                        if channel_url:
                            comments.append({
                                "channel_name": channel_name,
                                "channel_url": channel_url
                            })
                            total_comments += 1
                            
                            if total_comments >= max_comments:
                                break
                                
                # Получаем токен следующей страницы, если есть
                next_page_token = data.get("nextPageToken")
                
                # Если токена следующей страницы нет, значит комментарии закончились
                if not next_page_token:
                    break
                    
                # Для предотвращения блокировки запросов
                time.sleep(0.5)
            
            logger.info(f"Получено {len(comments)} комментариев через API")
            return comments
            
        except Exception as e:
            logger.error(f"Ошибка при получении комментариев через API: {str(e)}")
            logger.error(traceback.format_exc())
            return []
            
    def get_channel_info_api(self, channel_url: str, api_key: str = None) -> Dict[str, Any]:
        """
        Получает информацию о канале через YouTube Data API.
        
        Args:
            channel_url (str): URL канала
            api_key (str): Ключ API YouTube
            
        Returns:
            Dict[str, Any]: Словарь с данными о канале
        """
        if not api_key:
            logger.error("Не указан API ключ для получения информации о канале.")
            return {}
            
        try:
            # Извлекаем ID канала или имя канала из URL
            channel_id = None
            username = None
            
            # Проверяем формат URL канала
            if "youtube.com/channel/" in channel_url:
                channel_id = channel_url.split("youtube.com/channel/")[1].split("/")[0]
                logger.info(f"Извлечен ID канала из URL: {channel_id}")
            elif "youtube.com/@" in channel_url:
                username = channel_url.split("youtube.com/@")[1].split("/")[0]
                logger.info(f"Извлечено имя канала из URL: @{username}")
            elif "youtube.com/c/" in channel_url:
                username = channel_url.split("youtube.com/c/")[1].split("/")[0]
                logger.info(f"Извлечено имя канала из URL: c/{username}")
            elif "youtube.com/user/" in channel_url:
                username = channel_url.split("youtube.com/user/")[1].split("/")[0]
                logger.info(f"Извлечено имя канала из URL: user/{username}")
            else:
                logger.error(f"Неизвестный формат URL канала: {channel_url}")
                return {}
                
            # Если у нас есть только имя канала, нужно найти ID через поиск
            if not channel_id and username:
                search_url = "https://www.googleapis.com/youtube/v3/search"
                search_params = {
                    "part": "snippet",
                    "q": username,
                    "type": "channel",
                    "maxResults": 1,
                    "key": api_key
                }
                
                logger.info(f"Поиск ID канала по имени: {username}")
                
                search_response = requests.get(search_url, params=search_params)
                
                if search_response.status_code != 200:
                    logger.error(f"Ошибка API при поиске канала: {search_response.status_code}")
                    logger.error(f"Ответ API: {search_response.text}")
                    
                    # Проверяем, не исчерпана ли квота
                    if "quota" in search_response.text.lower():
                        logger.error("Превышен лимит квоты API.")
                        # Сохраняем ошибку для внешнего обработчика
                        if hasattr(self, 'youtube_analyzer'):
                            self.youtube_analyzer.last_api_error = "quotaExceeded"
                    
                    return {}
                    
                search_data = search_response.json()
                items = search_data.get("items", [])
                
                if not items:
                    logger.error(f"Канал {username} не найден через API")
                    return {}
                    
                channel_id = items[0].get("id", {}).get("channelId")
                logger.info(f"Найден ID канала: {channel_id}")
                
                # Для предотвращения блокировки запросов
                time.sleep(0.5)
                
            # Если ID канала все еще не найден, возвращаем пустой результат
            if not channel_id:
                return {}
                
            # Получаем информацию о канале через API
            channel_url = f"https://www.googleapis.com/youtube/v3/channels"
            channel_params = {
                "part": "snippet,statistics,contentDetails",
                "id": channel_id,
                "key": api_key
            }
            
            logger.info(f"Запрашиваем информацию о канале {channel_id} через API")
            
            channel_response = requests.get(channel_url, params=channel_params)
            
            if channel_response.status_code != 200:
                logger.error(f"Ошибка API при получении данных канала: {channel_response.status_code}")
                logger.error(f"Ответ API: {channel_response.text}")
                
                # Проверяем, не исчерпана ли квота
                if "quota" in channel_response.text.lower():
                    logger.error("Превышен лимит квоты API.")
                    # Сохраняем ошибку для внешнего обработчика
                    if hasattr(self, 'youtube_analyzer'):
                        self.youtube_analyzer.last_api_error = "quotaExceeded"
                
                return {}
                
            channel_data = channel_response.json()
            items = channel_data.get("items", [])
            
            if not items:
                logger.error(f"Данные о канале {channel_id} не найдены через API")
                return {}
                
            # Извлекаем данные о канале
            channel_item = items[0]
            snippet = channel_item.get("snippet", {})
            statistics = channel_item.get("statistics", {})
            
            # Формируем URL канала
            channel_url = f"https://www.youtube.com/channel/{channel_id}"
            
            # Получаем название канала
            channel_name = snippet.get("title", "Неизвестно")
            
            # Получаем число подписчиков
            subscribers = int(statistics.get("subscriberCount", 0))
            
            # Получаем число видео
            video_count = int(statistics.get("videoCount", 0))
            
            # Возвращаем собранные данные
            channel_info = {
                "channel_url": channel_url,
                "channel_name": channel_name,
                "subscribers": subscribers,
                "has_videos": video_count > 0,
                "video_count": video_count
            }
            
            logger.info(f"Данные канала через API: {json.dumps(channel_info, ensure_ascii=False)}")
            return channel_info
                
        except Exception as e:
            logger.error(f"Ошибка при получении информации о канале через API {channel_url}: {str(e)}")
            logger.error(traceback.format_exc())
            return {}


def render_commenters_analyzer_section():
    """
    Отображает раздел анализа комментаторов YouTube.
    """
    st.header("Анализ комментаторов YouTube")
    
    st.write("""
    Этот раздел анализирует комментарии к YouTube-видео и находит каналы, которые соответствуют заданным критериям.
    Вы можете настроить:
    - Минимальное число видео на канале
    - Ключевые слова, наличие которых в названии канала делает канал релевантным
    - Метод сбора данных: через браузер или через API (быстрее, но с ограничениями квоты)
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
    
    # Настройка параметров анализа - экспандер открыт по умолчанию
    with st.expander("Настройка параметров анализа", expanded=True):
        # Основные параметры - заменяем слайдеры на числовые поля ввода
        col1, col2 = st.columns(2)
        
        with col1:
            max_comments_per_video = st.number_input(
                "Максимальное количество комментариев для анализа с каждого видео",
                min_value=0,
                value=30,
                help="Большее количество комментариев даст более полные результаты, но анализ займет больше времени."
            )
        
        with col2:
            min_videos = st.number_input(
                "Минимальное число видео на канале комментатора",
                min_value=0,
                value=0,
                help="Этот параметр поможет отфильтровать каналы, на которых опубликовано меньше видео, чем указано."
            )
        
        # Значения ключевых слов по умолчанию
        default_keywords = "revenge\nstories\nstory\nreddit\ntale"
        keywords_input = st.text_area(
            "Ключевые слова для поиска в названии канала (по одному в строке)",
            value=default_keywords,
            height=150,
            help="Если название канала содержит хотя бы одно из этих ключевых слов, канал будет считаться релевантным. Поиск осуществляется без учета регистра."
        )
        
        # Преобразуем введенные ключевые слова в список
        keywords = [kw.strip() for kw in keywords_input.split('\n') if kw.strip()]
        
        # Добавляем разделитель
        st.markdown("---")
        st.subheader("Настройки API")
        st.info("API даёт более быстрый сбор данных, но имеет суточные квоты на запросы.")
        
        # Опции API для сбора комментариев
        use_api_for_comments = st.checkbox(
            "Использовать API для сбора комментариев",
            value=False,
            help="Ускоряет сбор комментариев, но использует квоту YouTube API"
        )
        
        # Опции API для сбора данных о каналах
        use_api_for_channels = st.checkbox(
            "Использовать API для сбора данных о каналах",
            value=False,
            help="Ускоряет получение данных о каналах, но использует квоту YouTube API"
        )
        
        if use_api_for_comments or use_api_for_channels:
            st.warning("""
            ⚠️ Лимиты YouTube API:
            - Суточная квота: 10,000 единиц.
            - Стоимость запросов: ~1-5 единиц за запрос.
            - При превышении квоты сбор данных может быть прерван.
            """)

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
        
        if not auth_analyzer or (not auth_analyzer.driver and not use_api_for_comments):
            st.error("❌ Отсутствует инициализированный драйвер браузера. Пожалуйста, перезагрузите страницу и выполните авторизацию заново.")
            return
        
        # Создаем анализатор комментаторов
        commenters_analyzer = CommentersAnalyzer(auth_analyzer)
        
        # Метрики производительности
        start_time = time.time()
        timing_stats = {
            "video_total": 0,
            "comments_fetch_time": 0,
            "channel_info_time": 0,
            "comment_count": 0,
            "channel_count": 0,
            "relevant_channels": 0
        }
        
        # Статус-бар для отображения текущей активности
        status_placeholder = st.empty()
        
        # Запускаем анализ с отображением прогресса
        with st.spinner("Анализируем комментаторов... Это может занять некоторое время."):
            progress_bar = st.progress(0)
            
            # Анализируем комментаторов для каждого видео с отображением прогресса
            all_commenters = {}  # Словарь для хранения всех комментаторов
            comments_count = defaultdict(int)  # Счетчик комментариев для каждого канала
            video_count = defaultdict(set)  # Множество видео, где встречается каждый канал
            
            # Отслеживаем, была ли исчерпана квота API
            quota_exceeded = False
            
            for i, video_url in enumerate(valid_urls):
                video_start_time = time.time()
                
                # Пропускаем дальнейшую обработку, если квота API исчерпана и используется API
                if quota_exceeded and (use_api_for_comments or use_api_for_channels):
                    st.error("⚠️ Квота YouTube API исчерпана. Дальнейшие запросы невозможны.")
                    break
                
                # Обновляем прогресс-бар
                progress = (i + 1) / len(valid_urls)
                progress_bar.progress(progress)
                
                # Отображаем текущее видео
                status_placeholder.info(f"Анализируем комментарии к видео {i+1} из {len(valid_urls)}: {video_url}")
                
                # Получаем комментарии - через API или через Selenium
                comments_start = time.time()
                comments = []
                if use_api_for_comments:
                    status_placeholder.info(f"Получаем комментарии через API для видео {i+1}/{len(valid_urls)}")
                    comments = commenters_analyzer.get_video_comments_api(video_url, max_comments_per_video, youtube_api_key)
                    # Проверяем, не исчерпана ли квота API
                    if hasattr(auth_analyzer, 'last_api_error') and 'quotaExceeded' in str(auth_analyzer.last_api_error):
                        quota_exceeded = True
                        st.warning("⚠️ Квота API для сбора комментариев исчерпана. Переключаемся на браузерный метод.")
                        status_placeholder.info(f"Переключаемся на браузерный метод для видео {i+1}/{len(valid_urls)}")
                        comments = commenters_analyzer.get_video_comments(video_url, max_comments_per_video)
                else:
                    status_placeholder.info(f"Получаем комментарии через браузер для видео {i+1}/{len(valid_urls)}")
                    comments = commenters_analyzer.get_video_comments(video_url, max_comments_per_video)
                
                comments_end = time.time()
                timing_stats["comments_fetch_time"] += (comments_end - comments_start)
                timing_stats["comment_count"] += len(comments)
                
                # Обрабатываем комментарии
                status_placeholder.info(f"Найдено {len(comments)} комментариев для видео {i+1}/{len(valid_urls)}. Анализируем каналы...")
                
                channels_processed = 0
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
                    
                    # Получаем информацию о канале - через API или через Selenium
                    channel_start = time.time()
                    channels_processed += 1
                    
                    if channels_processed % 5 == 0:
                        status_placeholder.info(f"Обработано {channels_processed} каналов из видео {i+1}/{len(valid_urls)}...")
                    
                    channel_info = {}
                    if use_api_for_channels and not quota_exceeded:
                        channel_info = commenters_analyzer.get_channel_info_api(channel_url, youtube_api_key)
                        # Проверяем, не исчерпана ли квота API
                        if hasattr(auth_analyzer, 'last_api_error') and 'quotaExceeded' in str(auth_analyzer.last_api_error):
                            quota_exceeded = True
                            st.warning("⚠️ Квота API для сбора данных о каналах исчерпана. Переключаемся на браузерный метод.")
                            channel_info = commenters_analyzer.get_channel_info(channel_url)
                    else:
                        channel_info = commenters_analyzer.get_channel_info(channel_url)
                    
                    channel_end = time.time()
                    timing_stats["channel_info_time"] += (channel_end - channel_start)
                    timing_stats["channel_count"] += 1
                    
                    # Проверяем соответствие критериям
                    if channel_info and commenters_analyzer.check_channel_relevance(channel_info, min_videos, keywords):
                        all_commenters[channel_url] = channel_info
                        timing_stats["relevant_channels"] += 1
                        # Логируем найденный релевантный канал с полной информацией
                        logger.info(f"Найден релевантный канал: {channel_info.get('channel_name', 'Неизвестно')} ({channel_url}), подписчиков: {channel_info.get('subscribers', 0)}")
                    
                    # Добавляем небольшую задержку между запросами для избежания блокировки
                    time.sleep(0.2)
                
                video_end_time = time.time()
                timing_stats["video_total"] += (video_end_time - video_start_time)
                
                # Отображаем статистику по видео
                status_placeholder.info(
                    f"Завершен анализ видео {i+1}/{len(valid_urls)}: {len(comments)} комментариев, "
                    f"{channels_processed} уникальных каналов, "
                    f"время: {video_end_time - video_start_time:.1f}с"
                )
            
            # Преобразуем словарь в DataFrame
            if all_commenters:
                # Отображаем итоговую статистику производительности
                total_time = time.time() - start_time
                st.info(
                    f"📊 Статистика: обработано {timing_stats['comment_count']} комментариев, "
                    f"исследовано {timing_stats['channel_count']} каналов, "
                    f"найдено {timing_stats['relevant_channels']} релевантных каналов.\n"
                    f"Затраченное время: {total_time:.1f}с (получение комментариев: {timing_stats['comments_fetch_time']:.1f}с, "
                    f"получение информации о каналах: {timing_stats['channel_info_time']:.1f}с)"
                )
                
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
                total_time = time.time() - start_time
                st.warning(
                    f"⚠️ Не найдено релевантных каналов, соответствующих критериям. "
                    f"Время работы: {total_time:.1f}с, обработано {timing_stats['comment_count']} комментариев "
                    f"и {timing_stats['channel_count']} каналов."
                ) 