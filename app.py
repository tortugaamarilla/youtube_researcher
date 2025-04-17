import os
import time
import logging
import tempfile
import concurrent.futures
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
import traceback
import requests
import random
import base64
import json
import hashlib
import uuid
from io import BytesIO
import re

from youtube_scraper import YouTubeAnalyzer, check_proxy
from llm_analyzer import LLMAnalyzer
from utils import parse_youtube_url, get_proxy_list

# Настройка логирования
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Инициализация логгера
logger = logging.getLogger("youtube_analyzer")

# Функция для загрузки API ключа из secrets.toml
def load_api_key_from_secrets():
    """
    Загружает YouTube API ключ из файла secrets.toml
    
    Returns:
        str: YouTube API ключ или None, если ключ не найден
    """
    try:
        # Streamlit автоматически загружает secrets.toml в st.secrets
        if hasattr(st, 'secrets') and 'youtube' in st.secrets and 'api_key' in st.secrets['youtube']:
            api_key = st.secrets['youtube']['api_key']
            
            # Проверяем, что ключ не является значением по умолчанию
            if api_key != "ВАШЕ_ЗНАЧЕНИЕ_КЛЮЧА_API_YOUTUBE":
                logger.info("YouTube API ключ успешно загружен из secrets.toml")
                return api_key
            else:
                logger.warning("Найден YouTube API ключ по умолчанию, требуется замена на реальный")
                return None
        else:
            logger.warning("Секция youtube.api_key не найдена в secrets.toml")
            return None
    except Exception as e:
        logger.error(f"Ошибка при загрузке YouTube API ключа из secrets: {str(e)}")
        return None

# Глобальная переменная для хранения результатов поиска похожих каналов
similar_channels_df = None

# Функция для настройки логирования
def setup_logging():
    """
    Настраивает логирование для приложения.
    Устанавливает уровень логирования, формат и обработчики.
    """
    # Настраиваем корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Проверяем, есть ли уже обработчики, чтобы избежать дублирования
    if not root_logger.handlers:
        # Создаем обработчик для вывода в консоль
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # Устанавливаем формат сообщений
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        
        # Добавляем обработчик к логгеру
        root_logger.addHandler(console_handler)
        
        # Создаем директорию для логов, если её нет
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        # Создаем обработчик для записи в файл
        try:
            file_handler = logging.FileHandler(f"{log_dir}/app.log")
            file_handler.setLevel(logging.INFO)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except Exception as e:
            print(f"Не удалось настроить логирование в файл: {e}")
    
    logger.info("Логирование настроено успешно")

# Настройка страницы Streamlit (должно быть первой командой)
st.set_page_config(
    page_title="YouTube Researcher",
    page_icon="🎥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Определение моделей OpenAI и Claude
OPENAI_MODELS = [
    "gpt-4o",
    "gpt-4-turbo",
    "gpt-4-vision-preview",
    "gpt-3.5-turbo"
]

CLAUDE_MODELS = [
    "claude-3-7-sonnet-20240620",
    "claude-3-5-sonnet-20240620",
    "claude-3-opus-20240229"
]

# Функция для фильтрации видео по дате
def filter_by_date(df: pd.DataFrame, max_days: int) -> pd.DataFrame:
    """
    Фильтрует DataFrame по дате публикации.
    
    Args:
        df (pd.DataFrame): DataFrame с данными о видео.
        max_days (int): Максимальное количество дней с момента публикации.
        
    Returns:
        pd.DataFrame: Отфильтрованный DataFrame.
    """
    if max_days <= 0 or "Дата публикации" not in df.columns:
        return df
    
    # Преобразуем строки даты в datetime объекты и фильтруем
    try:
        # Проверяем формат даты, если это строка
        if pd.api.types.is_string_dtype(df["Дата публикации"]):
            # Преобразуем в datetime
            df_with_date = df.copy()
            df_with_date["temp_date"] = pd.to_datetime(df["Дата публикации"], errors="coerce")
            
            # Расчитываем дни с публикации
            now = datetime.now()
            days_since = (now - df_with_date["temp_date"]).dt.days
            
            # Фильтруем
            mask = days_since <= max_days
            return df_with_date[mask].drop(columns=["temp_date"])
        else:
            # Если дата уже в формате datetime
            now = datetime.now()
            days_since = (now - df["Дата публикации"]).dt.days
            return df[days_since <= max_days]
    except Exception as e:
        logger.error(f"Ошибка при фильтрации по дате: {e}")
        return df

# Функция для фильтрации видео по просмотрам
def filter_by_views(df: pd.DataFrame, min_views: int) -> pd.DataFrame:
    """
    Фильтрует DataFrame по количеству просмотров.
    
    Args:
        df (pd.DataFrame): DataFrame с данными о видео.
        min_views (int): Минимальное количество просмотров.
        
    Returns:
        pd.DataFrame: Отфильтрованный DataFrame.
    """
    if min_views <= 0 or "Количество просмотров" not in df.columns:
        return df
    
    try:
        # Убедимся, что колонка с просмотрами содержит числа
        views_col = df["Количество просмотров"].copy()
        
        # Если значения уже числовые
        if pd.api.types.is_numeric_dtype(views_col):
            return df[views_col >= min_views]
        
        # Если значения строковые, пробуем преобразовать
        # Удаляем нечисловые символы и преобразуем в числа
        df_with_numeric_views = df.copy()
        df_with_numeric_views["numeric_views"] = views_col.astype(str).str.replace(r'[^\d]', '', regex=True).astype(float)
        
        # Фильтруем по преобразованным значениям
        mask = df_with_numeric_views["numeric_views"] >= min_views
        return df_with_numeric_views[mask].drop(columns=["numeric_views"])
        
    except Exception as e:
        logger.error(f"Ошибка при фильтрации по просмотрам: {e}")
        return df

def filter_by_search(df: pd.DataFrame, search_query: str) -> pd.DataFrame:
    """
    Фильтрует DataFrame по поисковому запросу в заголовке видео.
    
    Args:
        df (pd.DataFrame): DataFrame с данными о видео.
        search_query (str): Поисковый запрос.
        
    Returns:
        pd.DataFrame: Отфильтрованный DataFrame.
    """
    if not search_query or search_query.strip() == "":
        return df
    
    # Преобразуем запрос к нижнему регистру для регистронезависимого поиска
    search_query = search_query.lower()
    
    # Ищем в заголовке видео
    if "Заголовок видео" in df.columns:
        # Создаем маску для фильтрации, игнорируя регистр
        mask = df["Заголовок видео"].str.lower().str.contains(search_query, na=False)
        return df[mask]
    else:
        # Если нет колонки с заголовком, возвращаем исходный DataFrame
        return df

@st.cache_data(ttl=3600, show_spinner=False)
def get_video_data(url: str, _youtube_analyzer: YouTubeAnalyzer, max_retries: int = 2, cached_data: Dict = None) -> Dict:
    """
    Получает данные о видео с кэшированием
    
    Args:
        url: URL видео
        _youtube_analyzer: Экземпляр анализатора YouTube (не кэшируется)
        max_retries: Максимальное число попыток получения данных
        cached_data: Словарь с кэшированными данными
        
    Returns:
        Dict: Данные о видео
    """
    # Проверяем валидность URL
    if not url or not isinstance(url, str) or "youtube.com/watch" not in url and "youtu.be/" not in url:
        logger.warning(f"Недопустимый URL видео: {url}")
        return {
            "url": url,
            "title": "Недопустимый URL",
            "views": 0,
            "publication_date": "01.01.2000",
            "channel_name": "Недоступно"
        }
    
    # Очищаем URL от параметров
    clean_url = clean_youtube_url(url)
    
    # Проверяем кэш
    if cached_data and clean_url in cached_data:
        logger.info(f"Использование кэшированных данных для {clean_url}")
        return cached_data[clean_url]
    
    # Получаем данные с повторными попытками через быстрый метод
    for attempt in range(max_retries):
        try:
            logger.info(f"Попытка {attempt+1}/{max_retries} получения данных видео: {clean_url}")
            
            # Используем быстрый метод вместо Selenium
            df = _youtube_analyzer.test_video_parameters_fast([clean_url])
            
            if not df.empty:
                # Преобразуем результаты в словарь
                video_data = {
                    "url": clean_url,  # Используем очищенный URL
                    "title": df.iloc[0]["Заголовок"],
                    "views": df.iloc[0]["Просмотры_число"] if "Просмотры_число" in df.columns else int(df.iloc[0]["Просмотры"].replace(" ", "")),
                    "publication_date": datetime.now() - timedelta(days=int(df.iloc[0]["Дней с публикации"])) if df.iloc[0]["Дней с публикации"] != "—" else datetime.now(),
                    "days_since_publication": int(df.iloc[0]["Дней с публикации"]) if df.iloc[0]["Дней с публикации"] != "—" else 0,
                    "channel_name": "YouTube" # Примечание: быстрый метод не извлекает имя канала
                }
                
                logger.info(f"Успешно получены данные для {clean_url}")
                return video_data
            else:
                logger.warning(f"Попытка {attempt+1}: Не удалось получить полные данные для {clean_url}")
                time.sleep(1)  # Короткая пауза перед повторной попыткой
        
        except Exception as e:
            logger.error(f"Ошибка при получении данных для {clean_url} (попытка {attempt+1}): {e}")
            time.sleep(1)
    
    # Если быстрый метод не сработал, пробуем запасной вариант через Selenium
    try:
        logger.info(f"Используем запасной вариант через Selenium для {clean_url}")
        video_data = _youtube_analyzer.get_video_details(clean_url)
        
        if video_data and video_data.get("title") and video_data["title"] != "Недоступно":
            logger.info(f"Успешно получены данные через Selenium для {clean_url}")
            return video_data
    except Exception as e:
        logger.error(f"Ошибка при использовании запасного варианта для {clean_url}: {e}")
    
    # Возвращаем базовую информацию, если все попытки не удались
    logger.warning(f"Все попытки получить данные для {clean_url} не удались. Возвращаем базовую информацию.")
    return {
        "url": clean_url,
        "title": f"Недоступно ({clean_url.split('/')[-1]})",
        "views": 0,
        "publication_date": "01.01.2000",
        "channel_name": "Недоступно",
        "error": "Не удалось получить данные после нескольких попыток"
    }

def process_source_links(links: list, 
                        relevance_filters: dict = None, 
                        use_proxies: bool = True,
                        use_all_proxies: bool = False,
                        google_account: dict = None,
                        prewatch_settings: dict = None,
                        progress_container=None,
                        msg_container=None) -> Tuple[list, list]:
    """
    Обрабатывает исходные ссылки для получения рекомендаций.
    
    Args:
        links: Список исходных ссылок
        relevance_filters: Фильтры релевантности
        use_proxies: Использовать ли прокси
        use_all_proxies: Использовать ли все прокси (даже непроверенные)
        google_account: Словарь с данными аккаунта Google (email, password)
        prewatch_settings: Настройки предварительного просмотра
        progress_container: Контейнер для отображения прогресса
        msg_container: Контейнер для отображения сообщений
    
    Returns:
        Tuple[list, list]: Кортеж из списка рекомендаций первого и второго уровня
    """
    if not links:
        if msg_container:
            msg_container.warning("Не указаны исходные ссылки")
        return [], []

    # Проверяем, есть ли валидные YouTube-ссылки
    valid_links = [link.strip() for link in links if is_youtube_link(link.strip())]
    if not valid_links:
        if msg_container:
            msg_container.warning("Не найдено валидных YouTube-ссылок")
        return [], []
    
    if msg_container:
        msg_container.info(f"Найдено {len(valid_links)} валидных YouTube-ссылок")
    
    # Инициализируем YouTubeAnalyzer
    try:
        progress_text = "Инициализация..."
        if progress_container:
            progress_bar = progress_container.progress(0, text=progress_text)
        else:
            progress_bar = None
            
        # Получаем прокси, если используются
        proxies = None
        if use_proxies:
            proxies = get_proxy_list(force_all=use_all_proxies)
            if not proxies and not use_all_proxies:
                if msg_container:
                    msg_container.warning("Не найдено рабочих прокси. Попробуйте использовать все прокси или отключить их использование.")
                return [], []
        
        yt = YouTubeAnalyzer(proxy=proxies, google_account=google_account)
        
        # Если настройки предварительного просмотра указаны, выполняем предварительный просмотр
        if google_account and prewatch_settings and prewatch_settings.get('enabled', False):
            total_videos = prewatch_settings.get('total_videos', 10)
            distribution = prewatch_settings.get('distribution', 'even')
            min_watch_time = prewatch_settings.get('min_watch_time', 15)
            max_watch_time = prewatch_settings.get('max_watch_time', 45)
            like_probability = prewatch_settings.get('like_probability', 0.7)
            watch_percentage = prewatch_settings.get('watch_percentage', 0.3)
            
            if msg_container:
                msg_container.info(f"Выполняется предварительный просмотр {total_videos} видео...")
            
            # Собираем видео для просмотра
            videos_to_watch = []
            
            if distribution == 'even':
                # Равномерное распределение видео по каналам
                videos_per_channel = max(1, total_videos // len(valid_links))
                remaining_videos = total_videos - (videos_per_channel * len(valid_links))
                
                if msg_container:
                    msg_container.info(f"Просмотр примерно {videos_per_channel} видео с каждого канала")
                
                for link in valid_links:
                    try:
                        # Проверяем, это прямая ссылка на видео или канал
                        if "youtube.com/watch" in link or "youtu.be/" in link:
                            videos_to_watch.append(link)
                        else:
                            # Это канал, получаем последние видео
                            channel_videos = yt.get_last_videos_from_channel(link, limit=videos_per_channel)
                            if channel_videos:
                                videos_to_watch.extend(channel_videos)
                                if msg_container:
                                    msg_container.info(f"Получено {len(channel_videos)} видео с канала {link}")
                    except Exception as e:
                        if msg_container:
                            msg_container.warning(f"Ошибка при получении видео с {link}: {e}")
                
                # Если не набрали нужное количество видео, добавляем из оставшихся
                if len(videos_to_watch) < total_videos and remaining_videos > 0:
                    # Получаем больше видео с первых каналов
                    for link in valid_links[:min(3, len(valid_links))]:
                        try:
                            if not ("youtube.com/watch" in link or "youtu.be/" in link):
                                extra_videos = yt.get_last_videos_from_channel(
                                    link, 
                                    limit=videos_per_channel + remaining_videos,
                                    offset=videos_per_channel
                                )
                                if extra_videos:
                                    videos_to_watch.extend(extra_videos[:remaining_videos])
                                    remaining_videos -= len(extra_videos[:remaining_videos])
                                    if remaining_videos <= 0:
                                        break
                        except Exception as e:
                            if msg_container:
                                msg_container.warning(f"Ошибка при получении дополнительных видео: {e}")
            else:
                # Берем только самые новые видео
                if msg_container:
                    msg_container.info(f"Просмотр {total_videos} самых новых видео по всем каналам")
                
                all_channel_videos = []
                
                for link in valid_links:
                    try:
                        if "youtube.com/watch" in link or "youtu.be/" in link:
                            all_channel_videos.append((link, datetime.now())) # Для прямых ссылок используем текущую дату
                        else:
                            # Получаем видео с датами
                            channel_videos = yt.get_last_videos_from_channel(link, limit=min(10, total_videos))
                            if channel_videos:
                                for video_url in channel_videos:
                                    try:
                                        # Используем быстрый метод для получения данных
                                        video_data_df = yt.test_video_parameters_fast([video_url])
                                        if not video_data_df.empty:
                                            days_since_pub = int(video_data_df.iloc[0]["Дней с публикации"]) if video_data_df.iloc[0]["Дней с публикации"] != "—" else 0
                                            publish_date = datetime.now() - timedelta(days=days_since_pub)
                                            all_channel_videos.append((video_url, publish_date))
                                        else:
                                            all_channel_videos.append((video_url, datetime.now()))
                                    except:
                                        all_channel_videos.append((video_url, datetime.now()))
                    except Exception as e:
                        if msg_container:
                            msg_container.warning(f"Ошибка при получении видео с {link}: {e}")
                
                # Сортируем по дате (от новых к старым)
                all_channel_videos.sort(key=lambda x: x[1], reverse=True)
                
                # Берем только URL видео
                videos_to_watch = [video[0] for video in all_channel_videos[:total_videos]]
            
            # Выполняем предварительный просмотр
            if videos_to_watch:
                if msg_container:
                    msg_container.info(f"Начинаем предварительный просмотр {len(videos_to_watch)} видео...")
                    
                yt.prewatch_videos(
                    videos_to_watch[:total_videos],
                    min_watch_time=min_watch_time,
                    max_watch_time=max_watch_time,
                    like_probability=like_probability,
                    watch_percentage=watch_percentage
                )
                
                if msg_container:
                    msg_container.success(f"Предварительный просмотр завершен")
            else:
                if msg_container:
                    msg_container.warning("Не удалось найти видео для предварительного просмотра")
        
        # Инициализируем списки для хранения рекомендаций
        first_level_recommendations = []
        second_level_recommendations = []
        
        # Общее количество исходных ссылок для расчета прогресса
        total_links = len(valid_links)
        
        # Обрабатываем каждую ссылку
        for i, link in enumerate(valid_links):
            try:
                # Проверяем тип ссылки (видео или канал)
                is_video = "youtube.com/watch" in link or "youtu.be/" in link
                
                # Если это видео, очищаем URL от параметров
                if is_video:
                    link = clean_youtube_url(link)
                
                # Обновляем прогресс
                current_progress = (i / total_links)
                progress_text = f"Обработка ссылки {i+1}/{total_links}: {link[:50]}..."
                
                if progress_bar:
                    progress_bar.progress(current_progress, text=progress_text)
                
                # Если это прямая ссылка на видео
                if is_video:
                    if msg_container:
                        msg_container.info(f"Получение рекомендаций для видео: {link}")
                        
                    # Получаем рекомендации первого уровня
                    rec1 = yt.get_recommended_videos(link, limit=20)
                    
                    # Очищаем URL рекомендаций
                    clean_rec1 = []
                    for rec in rec1:
                        if isinstance(rec, dict) and "url" in rec:
                            clean_url = clean_youtube_url(rec["url"])
                            clean_rec = rec.copy()
                            clean_rec["url"] = clean_url
                            clean_rec1.append(clean_rec)
                        elif isinstance(rec, str):
                            clean_rec1.append(clean_youtube_url(rec))
                        else:
                            clean_rec1.append(rec)
                    
                    if clean_rec1:
                        first_level_recommendations.extend(clean_rec1)
                        if msg_container:
                            msg_container.success(f"Получено {len(clean_rec1)} рекомендаций первого уровня")
                    else:
                        if msg_container:
                            msg_container.warning(f"Не удалось получить рекомендации для видео: {link}")
                else:
                    # Иначе, это канал
                    if msg_container:
                        msg_container.info(f"Обработка канала: {link}")
                        
                    # Получаем последние видео с канала
                    videos = yt.get_last_videos_from_channel(link, limit=5)
                    
                    if videos:
                        if msg_container:
                            msg_container.success(f"Получено {len(videos)} видео с канала")
                        
                        # Получаем рекомендации для каждого видео с канала
                        for j, video_url in enumerate(videos):
                            # Очищаем URL видео
                            clean_video_url = clean_youtube_url(video_url)
                            
                            rec1 = yt.get_recommended_videos(clean_video_url, limit=20)
                            
                            # Очищаем URL рекомендаций
                            clean_rec1 = []
                            for rec in rec1:
                                if isinstance(rec, dict) and "url" in rec:
                                    clean_url = clean_youtube_url(rec["url"])
                                    clean_rec = rec.copy()
                                    clean_rec["url"] = clean_url
                                    clean_rec1.append(clean_rec)
                                elif isinstance(rec, str):
                                    clean_rec1.append(clean_youtube_url(rec))
                                else:
                                    clean_rec1.append(rec)
                            
                            if clean_rec1:
                                first_level_recommendations.extend(clean_rec1)
                                if msg_container:
                                    msg_container.success(f"Получено {len(clean_rec1)} рекомендаций из видео {j+1}/{len(videos)}")
                            else:
                                if msg_container:
                                    msg_container.warning(f"Не удалось получить рекомендации для видео {j+1}")
                    else:
                        if msg_container:
                            msg_container.warning(f"Не удалось получить видео с канала: {link}")
                
            except Exception as e:
                if msg_container:
                    msg_container.error(f"Ошибка при обработке ссылки {link}: {str(e)}")
                logger.error(f"Ошибка при обработке ссылки {link}: {str(e)}")
        
        # Удаляем дубликаты из рекомендаций первого уровня
        first_level_recommendations = list(set(first_level_recommendations))
        
        if msg_container:
            msg_container.success(f"Всего получено {len(first_level_recommendations)} уникальных рекомендаций первого уровня")
        
        # Получаем рекомендации второго уровня, если есть рекомендации первого уровня
        if first_level_recommendations:
            # Обновляем прогресс
            progress_text = "Получение рекомендаций второго уровня..."
            if progress_bar:
                progress_bar.progress(0.7, text=progress_text)
            
            # Выбираем случайные рекомендации первого уровня для получения рекомендаций второго уровня
            sample_size = min(len(first_level_recommendations), 5)
            sample_recommendations = random.sample(first_level_recommendations, sample_size)
            
            if msg_container:
                msg_container.info(f"Выбрано {sample_size} видео для получения рекомендаций второго уровня")
            
            # Получаем рекомендации второго уровня
            for j, rec_url in enumerate(sample_recommendations):
                try:
                    # Обновляем прогресс
                    if progress_bar:
                        current_progress = 0.7 + (0.3 * (j / sample_size))
                        progress_bar.progress(current_progress, text=f"Рекомендации 2-го уровня {j+1}/{sample_size}")
                    
                    # Очищаем URL рекомендации
                    clean_rec_url = clean_youtube_url(rec_url)
                    
                    rec2 = yt.get_recommended_videos(clean_rec_url, limit=10)
                    
                    # Очищаем URL рекомендаций второго уровня
                    clean_rec2 = []
                    for rec in rec2:
                        if isinstance(rec, dict) and "url" in rec:
                            clean_url = clean_youtube_url(rec["url"])
                            clean_rec = rec.copy()
                            clean_rec["url"] = clean_url
                            clean_rec2.append(clean_rec)
                        elif isinstance(rec, str):
                            clean_rec2.append(clean_youtube_url(rec))
                        else:
                            clean_rec2.append(rec)
                    
                    if clean_rec2:
                        second_level_recommendations.extend(clean_rec2)
                        if msg_container:
                            msg_container.success(f"Получено {len(clean_rec2)} рекомендаций второго уровня из видео {j+1}/{sample_size}")
                    else:
                        if msg_container:
                            msg_container.warning(f"Не удалось получить рекомендации второго уровня для видео {j+1}")
                            
                except Exception as e:
                    if msg_container:
                        msg_container.error(f"Ошибка при получении рекомендаций второго уровня: {str(e)}")
                    logger.error(f"Ошибка при получении рекомендаций второго уровня: {str(e)}")
            
            # Удаляем дубликаты из рекомендаций второго уровня
            second_level_recommendations = list(set(second_level_recommendations))
            
            # Удаляем рекомендации, которые уже есть в первом уровне
            second_level_recommendations = [url for url in second_level_recommendations if url not in first_level_recommendations]
            
            if msg_container:
                msg_container.success(f"Всего получено {len(second_level_recommendations)} уникальных рекомендаций второго уровня")
        
        # Завершаем прогресс
        progress_bar.progress(1.0)
        status_text.text("Обработка завершена!")
        
        # Финальное обновление статистики больше не нужно, так как вся информация
        # уже отображена для каждого канала/видео
        # update_stats(force=True, source_videos_count=len(source_videos), recommendations_count=len(results) - len(source_videos))
        
        # Закрываем драйвер
        try:
            yt.close()
        except:
            pass
        
        return first_level_recommendations, second_level_recommendations
            
    except Exception as e:
        if msg_container:
            msg_container.error(f"Ошибка: {str(e)}")
            msg_container.error("Проверьте работоспособность браузера Chrome и драйвера chromedriver.")
            
            driver_status = "❌ Не удалось инициализировать браузер"
            proxy_status = "❌ Ошибка обработки прокси" if use_proxies else "⚠️ Прокси отключены"
            
            msg_container.error(f"""
            **Статус драйвера:** {driver_status}
            **Статус прокси:** {proxy_status}
            
            **Детали ошибки:**
            ```
            {str(e)}
            ```
            """)
            
        logger.error(f"Ошибка: {str(e)}")
        return [], []

def check_video_relevance(
    llm_analyzer: LLMAnalyzer,
    videos: List[Dict[str, Any]],
    reference_topics: List[str],
    relevance_temp: float
) -> List[Dict[str, Any]]:
    """
    Проверяет релевантность видео относительно эталонных тем.
    
    Args:
        llm_analyzer (LLMAnalyzer): Анализатор LLM.
        videos (List[Dict[str, Any]]): Список видео для проверки.
        reference_topics (List[str]): Список эталонных тем.
        relevance_temp (float): Температура релевантности.
        
    Returns:
        List[Dict[str, Any]]: Список релевантных видео.
    """
    relevant_videos = []
    
    for video in videos:
        if not video.get("title"):
            continue
            
        relevance_result = llm_analyzer.check_relevance(
            video["title"],
            reference_topics,
            temperature=relevance_temp
        )
        
        video["relevance_score"] = relevance_result.get("score", 0.0)
        video["relevance_explanation"] = relevance_result.get("explanation", "")
        
        if relevance_result.get("relevant", True):
            relevant_videos.append(video)
            
    return relevant_videos

def extract_thumbnail_text(
    llm_analyzer: LLMAnalyzer,
    youtube_analyzer: YouTubeAnalyzer,
    videos: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Извлекает текст из миниатюр видео.
    
    Args:
        llm_analyzer (LLMAnalyzer): Анализатор LLM.
        youtube_analyzer (YouTubeAnalyzer): Анализатор YouTube.
        videos (List[Dict[str, Any]]): Список видео.
        
    Returns:
        List[Dict[str, Any]]: Список видео с извлеченным текстом.
    """
    for video in videos:
        if not video.get("thumbnail_url"):
            video["thumbnail_text"] = ""
            continue
            
        thumbnail = youtube_analyzer.download_thumbnail(video["thumbnail_url"])
        
        if thumbnail:
            video["thumbnail_text"] = llm_analyzer.extract_text_from_thumbnail(thumbnail)
        else:
            video["thumbnail_text"] = ""
            
    return videos

def create_results_dataframe(videos: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Создает DataFrame из списка видео.
    
    Args:
        videos (List[Dict[str, Any]]): Список видео.
        
    Returns:
        pd.DataFrame: DataFrame с результатами.
    """
    if not videos:
        # Возвращаем пустой DataFrame с нужными колонками
        return pd.DataFrame(columns=[
            "Заголовок видео", "URL", "Дата публикации", 
            "Количество просмотров", "Источник", 
            "Оценка релевантности", "Текст из Thumbnail"
        ])
        
    data = []
    
    for video in videos:
        source_type = video.get("source_type", "unknown")
        if source_type == "channel" or source_type == "direct_link":
            source = "Исходный список"
        elif source_type == "recommendation_level_1":
            source = "Рекомендации 1го уровня"
        elif source_type == "recommendation_level_2":
            source = "Рекомендации 2го уровня"
        else:
            source = "Неизвестно"
            
        pub_date = video.get("publication_date")
        if pub_date and isinstance(pub_date, datetime):
            formatted_date = pub_date.strftime("%Y-%m-%d %H:%M")
        else:
            formatted_date = "Неизвестно"
            
        data.append({
            "Заголовок видео": video.get("title", "Нет заголовка"),
            "URL": video.get("url", ""),
            "Дата публикации": formatted_date,
            "Количество просмотров": video.get("views", 0),
            "Источник": source,
            "Оценка релевантности": video.get("relevance_score", 0.0),
            "Текст из Thumbnail": video.get("thumbnail_text", "")
        })
        
    # Создаем DataFrame и убеждаемся, что все ожидаемые колонки присутствуют
    df = pd.DataFrame(data)
    
    # Логируем структуру DataFrame для отладки
    logger.info(f"Создан DataFrame с колонками: {df.columns.tolist()}")
    logger.info(f"Количество строк в DataFrame: {len(df)}")
    
    return df

def check_proxies() -> List[Dict[str, str]]:
    """
    Проверяет доступность прокси серверов.
    
    Returns:
        List[Dict[str, str]]: Список рабочих прокси.
    """
    working_proxies = []
    all_proxies = get_proxy_list()
    
    if not all_proxies:
        st.warning("В конфигурации не найдено ни одного прокси-сервера. Работа возможна, но вероятны блокировки YouTube.")
        return []
    
    st.info(f"Проверка {len(all_proxies)} прокси-серверов...")
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # Создаем форсированный вывод текста
    check_details = st.empty()
    proxy_details = []
    
    for i, proxy in enumerate(all_proxies):
        try:
            # Обновляем прогресс
            progress_value = float(i) / len(all_proxies)
            progress_bar.progress(progress_value)
            status_text.text(f"Проверяем прокси {proxy['server']}...")
            
            # Формат для вывода
            proxy_info = f"Прокси {proxy['server']}, логин: {proxy.get('username', 'нет')}"
            proxy_details.append(proxy_info)
            check_details.text("\n".join(proxy_details + ["Выполняется проверка..."]))
            
            # Используем функцию check_proxy из youtube_scraper.py
            proxy_string = f"{proxy['server'].split(':')[0]}:{proxy['server'].split(':')[1]}:{proxy['username']}:{proxy['password']}"
            is_working, message = check_proxy(proxy_string)
            
            if is_working:
                working_proxies.append(proxy)
                proxy_details[-1] = f"{proxy_info} - РАБОТАЕТ! ({message})"
                st.success(f"Прокси {proxy['server']} работает! {message}")
            else:
                proxy_details[-1] = f"{proxy_info} - НЕ РАБОТАЕТ: {message}"
                st.error(f"Прокси {proxy['server']} не работает: {message}")
                
        except Exception as e:
            logger.error(f"Прокси {proxy['server']} не работает: {e}")
            proxy_details[-1] = f"{proxy_info} - ОШИБКА: {str(e)[:50]}..."
            st.error(f"Прокси {proxy['server']} вызвал ошибку: {str(e)[:100]}...")
    
    # Завершаем прогресс
    progress_bar.progress(1.0)
    status_text.empty()
    
    if not working_proxies:
        # Если прокси не найдены, предлагаем выбор
        st.warning("Не найдено рабочих прокси-серверов. Выберите один из вариантов:")
        option_cols = st.columns(2)
        with option_cols[0]:
            if st.button("Продолжить со всеми прокси"):
                all_proxies = get_proxy_list()
                if all_proxies:
                    st.session_state.working_proxies = all_proxies
                    st.success(f"Добавлены все {len(all_proxies)} прокси-серверы")
        with option_cols[1]:
            if st.button("Работать без прокси"):
                st.session_state.use_proxy = False
                st.warning("Вы выбрали работу без прокси. YouTube может заблокировать доступ.")
    else:
        st.success(f"Найдено {len(working_proxies)} рабочих прокси из {len(all_proxies)}")
        
    return working_proxies

def process_youtube_channels(youtube_urls, proxies=None, max_videos=5, sections=None):
    """
    Обрабатывает список каналов YouTube и возвращает собранные данные
    
    Args:
        youtube_urls (list): Список URL-адресов каналов YouTube
        proxies (list, optional): Список прокси для использования
        max_videos (int): Максимальное количество видео для анализа с каждого канала
        sections (list, optional): Разделы для анализа (videos, shorts и т.д.)
        
    Returns:
        dict: Результаты анализа каналов
    """
    logger.info(f"Начинаю анализ {len(youtube_urls)} YouTube каналов")
    
    # Инициализируем YouTube скрапер с прокси, если они указаны
    try:
        youtube_analyzer = None
        if proxies:
            # Используем валидный прокси из списка
            for proxy in proxies:
                try:
                    logger.info(f"Пробуем использовать прокси: {proxy}")
                    youtube_analyzer = YouTubeAnalyzer(proxy=proxy)
                    if youtube_analyzer and youtube_analyzer.driver:
                        logger.info(f"Успешно инициализирован драйвер с прокси: {proxy}")
                        break
                except Exception as e:
                    logger.error(f"Ошибка при инициализации с прокси {proxy}: {e}")
                    if youtube_analyzer:
                        youtube_analyzer.close_driver()
        
        # Если не удалось инициализировать с прокси, пробуем без них
        if not youtube_analyzer or not youtube_analyzer.driver:
            logger.warning("Не удалось инициализировать с прокси, пробуем без прокси")
            youtube_analyzer = YouTubeAnalyzer()
            
        # Если даже без прокси не получилось, возвращаем ошибку
        if not youtube_analyzer or not youtube_analyzer.driver:
            logger.error("Не удалось инициализировать YouTube анализатор")
            return {
                "success": False,
                "error": "Не удалось инициализировать браузер для анализа YouTube",
                "channels_processed": 0,
                "channels": []
            }
        
        # Используем новый метод для обработки списка каналов
        results = youtube_analyzer.process_channels(
            channel_urls=youtube_urls,
            max_videos=max_videos,
            sections=sections
        )
        
        # Закрываем драйвер после завершения
        youtube_analyzer.close_driver()
        
        return results
        
    except Exception as e:
        logger.error(f"Ошибка при обработке YouTube каналов: {e}")
        traceback.print_exc()
        
        # Закрываем драйвер в случае ошибки
        if youtube_analyzer:
            youtube_analyzer.close_driver()
            
        return {
            "success": False,
            "error": str(e),
            "channels_processed": 0,
            "channels": []
        }

def test_recommendations(source_links: List[str], 
                         google_account: Dict[str, str] = None, 
                         prewatch_settings: Dict[str, Any] = None,
                         channel_videos_limit: int = 5,
                         recommendations_per_video: int = 5,
                         max_days_since_publication: int = 7,
                         min_video_views: int = 10000,
                         existing_analyzer: YouTubeAnalyzer = None) -> pd.DataFrame:
    """
    Функция для сбора рекомендаций из списка исходных ссылок.
    
    Args:
        source_links (List[str]): Список ссылок на видео/каналы YouTube
        google_account (Dict[str, str], optional): Аккаунт Google для авторизации
        prewatch_settings (Dict[str, Any], optional): Настройки предварительного просмотра
        channel_videos_limit (int): Количество последних видео с канала
        recommendations_per_video (int): Количество рекомендаций для каждого видео
        max_days_since_publication (int): Максимальное количество дней с момента публикации
        min_video_views (int): Минимальное количество просмотров
        existing_analyzer (YouTubeAnalyzer, optional): Существующий экземпляр анализатора
        
    Returns:
        pd.DataFrame: Датафрейм с результатами
    """
    results = []
    source_videos = []  # Видео с исходных каналов, они всегда добавляются в результаты
    progress_bar = st.progress(0)
    status_text = st.empty()
    stats_container = st.container()
    
    # Статистика для отслеживания производительности
    stats = {
        "processed_links": 0,
        "processed_videos": 0,
        "skipped_views": 0,
        "skipped_date": 0,
        "added_videos": 0,
        "total_time": 0,
        # Дополнительная статистика для замера времени операций
        "time_get_recommendations": 0,
        "time_get_video_data": 0,
        "count_get_recommendations": 0,
        "count_get_video_data": 0
    }
    
    # Таймеры для детального отслеживания
    timers = {
        "current_operation_start": 0,
        "recommendation_times": [],
        "video_data_times": []
    }
    
    # Функция для обновления таймеров
    def start_timer(operation_name):
        timers["current_operation"] = operation_name
        timers["current_operation_start"] = time.time()
        logger.info(f"Начало операции: {operation_name}")
        
    def end_timer(operation_name):
        if timers["current_operation_start"] == 0:
            return 0
            
        elapsed_time = time.time() - timers["current_operation_start"]
        logger.info(f"Завершение операции: {operation_name}, время: {elapsed_time:.2f}с")
        
        # Сохраняем время в зависимости от типа операции
        if "получение рекомендаций" in operation_name.lower():
            timers["recommendation_times"].append(elapsed_time)
            stats["time_get_recommendations"] += elapsed_time
            stats["count_get_recommendations"] += 1
        elif "получение данных" in operation_name.lower():
            timers["video_data_times"].append(elapsed_time)
            stats["time_get_video_data"] += elapsed_time
            stats["count_get_video_data"] += 1
            
        return elapsed_time
    
    # Функция для вывода статистики о времени выполнения
    def update_timing_stats():
        pass
    
    start_time = time.time()
    
    # Используем существующий анализатор, если он передан
    if existing_analyzer and existing_analyzer.driver:
        youtube_analyzer = existing_analyzer
        status_text.text("Используем существующую сессию браузера...")
        logger.info("Используется существующий экземпляр анализатора YouTube")
    else:
        # Создаем новый анализатор YouTube
        status_text.text("Инициализация нового браузера...")
        youtube_analyzer = YouTubeAnalyzer(headless=True, use_proxy=False, google_account=google_account)
        
        # Инициализируем драйвер
        youtube_analyzer.setup_driver()
        
    try:
        # Проверяем, инициализирован ли драйвер
        if youtube_analyzer.driver is None:
            status_text.error("Не удалось инициализировать драйвер. Попробуйте перезапустить приложение.")
            return pd.DataFrame()
        
        # Фильтруем только валидные ссылки YouTube
        valid_links = [link.strip() for link in source_links if "youtube.com" in link or "youtu.be" in link]
        
        if not valid_links:
            status_text.warning("Не найдено валидных ссылок YouTube. Пожалуйста, проверьте список ссылок.")
            return pd.DataFrame()
            
        # Если пользователь выбрал предварительный просмотр, выполняем его
        if prewatch_settings and prewatch_settings.get("enabled", False):
            # Логика предварительного просмотра...
            pass
        
        status_text.text(f"Начинаем обработку {len(valid_links)} ссылок...")
        
        # Список для хранения всех источников и рекомендаций до фильтрации
        all_video_sources = []
        all_recommendations = []
        
        # Функция для обновления статистики
        last_update_time = 0
        update_interval = 5.0  # Увеличиваем интервал между обновлениями статистики до 5 секунд
        last_processed_videos = 0
        last_added_videos = 0
        link_stats = {}  # Словарь для хранения статистики по каждой ссылке
        
        def update_stats(force=False, current_link=None, source_videos_count=0, recommendations_count=0):
            nonlocal last_update_time, last_processed_videos, last_added_videos
            current_time = time.time()
            
            # Обновляем только если:
            # 1. Прошло не менее update_interval секунд с последнего обновления
            # 2. Или требуется принудительное обновление (force=True)
            # 3. Или есть существенные изменения в количестве обработанных/добавленных видео
            substantial_change = (stats['processed_videos'] - last_processed_videos >= 5) or (stats['added_videos'] - last_added_videos >= 5)
            
            if not (force or substantial_change or (current_time - last_update_time >= update_interval)):
                return
                
            # Обновляем время последнего обновления и счетчики
            last_update_time = current_time
            last_processed_videos = stats['processed_videos']
            last_added_videos = stats['added_videos']
            
            # Вычисляем общее время выполнения
            time_elapsed = current_time - start_time
            stats["total_time"] = time_elapsed
            
            # Обновляем отображение статистики
            with stats_container:
                if current_link:
                    # Если передана текущая ссылка, записываем статистику для неё
                    if current_link not in link_stats:
                        link_stats[current_link] = {
                            "source_videos": source_videos_count,
                            "recommendations": recommendations_count
                        }
                    else:
                        # Обновляем только если переданы ненулевые значения
                        if source_videos_count > 0:
                            link_stats[current_link]["source_videos"] = source_videos_count
                        if recommendations_count > 0:
                            link_stats[current_link]["recommendations"] = recommendations_count
                    
                    st.markdown(f"При обработке строки {current_link} добавлено в результаты {link_stats[current_link]['source_videos']} видео с канала/источника и {link_stats[current_link]['recommendations']} видео с рекомендаций.")
                else:
                    # Если ссылка не передана, но это принудительное обновление, показываем последнюю обработанную ссылку
                    if force and stats['processed_links'] > 0 and stats['processed_links'] <= len(valid_links):
                        last_link = valid_links[stats['processed_links']-1]
                        if last_link in link_stats:
                            st.markdown(f"При обработке строки {last_link} добавлено в результаты {link_stats[last_link]['source_videos']} видео с канала/источника и {link_stats[last_link]['recommendations']} видео с рекомендаций.")
            
            # Обновляем статистику о времени выполнения
            update_timing_stats()
        
        # Функция для быстрой предварительной фильтрации рекомендаций
        def quick_filter_video(video_data):
            if not video_data:
                return False
                
            # Проверяем просмотры (быстрее получить)
            views_count = video_data.get("views", 0)
            # Защита от None значений
            if views_count is None:
                views_count = 0
            # Убеждаемся, что views_count - число
            if not isinstance(views_count, (int, float)):
                try:
                    views_count = int(views_count)
                except (ValueError, TypeError):
                    views_count = 0
                    
            if views_count < min_video_views:
                stats["skipped_views"] += 1
                logger.info(f"Видео не соответствует критерию просмотров: {video_data.get('url')} (просмотров: {views_count}, минимум: {min_video_views})")
                return False
                
            # Проверяем дату публикации
            pub_date = video_data.get("publication_date")
            if pub_date:
                try:
                    days_since_publication = (datetime.now() - pub_date).days
                    if days_since_publication > max_days_since_publication:
                        stats["skipped_date"] += 1
                        logger.info(f"Видео не соответствует критерию даты: {video_data.get('url')} (дней с публикации: {days_since_publication}, максимум: {max_days_since_publication})")
                        return False
                except Exception as e:
                    # Если возникла ошибка при расчете дней, лучше не фильтровать по этому критерию
                    logger.warning(f"Ошибка при проверке даты публикации для {video_data.get('url')}: {e}")
            else:
                logger.warning(f"Отсутствует дата публикации для {video_data.get('url')}")
                
            # Видео прошло все проверки
            logger.info(f"Видео удовлетворяет критериям: {video_data.get('url')} (просмотров: {views_count}, соответствует параметрам)")
            return True
        
        for i, link in enumerate(valid_links):
            # Обновляем прогресс
            progress_value = float(i) / len(valid_links)
            progress_bar.progress(progress_value)
            status_text.text(f"Обрабатываем ссылку {i+1}/{len(valid_links)}: {link}")
            stats["processed_links"] += 1
            
            # Проверяем тип ссылки (канал или видео)
            url, is_channel = parse_youtube_url(link)
            
            # Запоминаем текущее количество видео из источников перед обработкой нового канала/видео
            source_videos_before = len(source_videos)
            # Запоминаем текущее количество рекомендаций
            recommendations_before = len(all_recommendations)
            
            if is_channel:
                # Для канала получаем последние видео (используем channel_videos_limit)
                status_text.text(f"Получение последних видео с канала: {url}")
                start_timer(f"Получение видео с канала: {url}")
                channel_videos = youtube_analyzer.get_last_videos_from_channel(url, limit=channel_videos_limit)
                channel_time = end_timer(f"Получение видео с канала: {url}")
                status_text.text(f"Получено видео с канала за {channel_time:.2f}с")
                
                if not channel_videos:
                    status_text.warning(f"Не удалось получить видео с канала {url}")
                    continue
                
                # Обрабатываем каждое видео с канала
                for video_index, video_info in enumerate(channel_videos):
                    video_url = video_info.get("url")
                    if not video_url:
                        continue
                    
                    stats["processed_videos"] += 1
                    logger.info(f"Обработка видео {video_index+1}/{len(channel_videos)} с канала: {video_url}")
                    
                    # Получаем детали видео
                    status_text.text(f"Получение деталей видео: {video_url}")
                    start_timer(f"Получение данных о видео: {video_url}")
                    
                    # Используем быстрый метод вместо get_video_details
                    video_data_df = youtube_analyzer.test_video_parameters_fast([video_url])
                    video_data = None
                    if not video_data_df.empty:
                        # Преобразуем результат в формат словаря, совместимый с исходным
                        video_data = {
                            "url": clean_youtube_url(video_url),
                            "title": video_data_df.iloc[0]["Заголовок"],
                            "views": video_data_df.iloc[0]["Просмотры_число"] if "Просмотры_число" in video_data_df.columns else int(video_data_df.iloc[0]["Просмотры"].replace(" ", "")),
                            "publication_date": datetime.now() - timedelta(days=int(video_data_df.iloc[0]["Дней с публикации"])) if video_data_df.iloc[0]["Дней с публикации"] != "—" else datetime.now(),
                            "channel_name": "YouTube",  # Имя канала не доступно через быстрый метод
                            "channel_url": video_data_df.iloc[0]["Канал URL"] if "Канал URL" in video_data_df.columns else None
                        }
                    
                    video_data_time = end_timer(f"Получение данных о видео: {video_url}")
                    status_text.text(f"Получены данные о видео за {video_data_time:.2f}с")
                    
                    # ИЗМЕНЕНИЯ: Получаем рекомендации для всех видео, но в source_videos добавляем только соответствующие критериям
                    
                    # Получаем рекомендации для этого видео независимо от критериев
                    status_text.text(f"Получение рекомендаций для видео: {video_url}")
                    start_timer(f"Получение рекомендаций для видео: {video_url}")
                    # Используем быстрый метод вместо обычного
                    recommendations = youtube_analyzer.get_recommended_videos_fast(video_url, limit=recommendations_per_video)
                    rec_time = end_timer(f"Получение рекомендаций для видео: {video_url}")
                    status_text.text(f"Получены рекомендации ({len(recommendations)}) за {rec_time:.2f}с")
                    logger.info(f"Получено {len(recommendations)} рекомендаций для видео {video_url}")
                    
                    # Сохраняем URL рекомендаций для последующей обработки
                    recommendation_urls = []
                    for rec_info in recommendations:
                        rec_url = rec_info.get("url")
                        if rec_url:
                            # Очищаем URL от параметров
                            clean_rec_url = clean_youtube_url(rec_url)
                            recommendation_urls.append({
                                "url": clean_rec_url,
                                "source_video": clean_youtube_url(video_url)
                            })
                    
                    # Добавляем все рекомендации для этого видео в общий список
                    all_recommendations.extend(recommendation_urls)
                    logger.info(f"Добавлено {len(recommendation_urls)} рекомендаций для видео {video_url}")
                    
                    # Проверяем, соответствует ли видео с исходного канала заданным параметрам 
                    # для добавления в таблицу источников
                    if video_data and quick_filter_video(video_data):
                        video_data["source"] = f"Канал: {link}"
                        source_videos.append(video_data)
                        stats["added_videos"] += 1
                    else:
                        # Если видео не соответствует критериям, пропускаем его добавление в итоговую таблицу
                        if video_data:
                            status_text.text(f"Видео не соответствует критериям, не добавлено в таблицу: {video_url}")
                
                # Обновляем статистику принудительно после обработки всех видео с канала
                # Передаем только видео и рекомендации с текущего канала, а не общее количество
                current_source_videos = len(source_videos) - source_videos_before
                current_recommendations = len(all_recommendations) - recommendations_before
                update_stats(force=True, current_link=url, source_videos_count=current_source_videos, recommendations_count=current_recommendations)
            else:
                # Для прямой ссылки на видео
                status_text.text(f"Получение деталей видео: {url}")
                start_timer(f"Получение данных о видео: {url}")
                
                # Используем быстрый метод вместо get_video_details
                video_data_df = youtube_analyzer.test_video_parameters_fast([url])
                video_data = None
                if not video_data_df.empty:
                    # Преобразуем результат в формат словаря, совместимый с исходным
                    video_data = {
                        "url": clean_youtube_url(url),
                        "title": video_data_df.iloc[0]["Заголовок"],
                        "views": video_data_df.iloc[0]["Просмотры_число"] if "Просмотры_число" in video_data_df.columns else int(video_data_df.iloc[0]["Просмотры"].replace(" ", "")),
                        "publication_date": datetime.now() - timedelta(days=int(video_data_df.iloc[0]["Дней с публикации"])) if video_data_df.iloc[0]["Дней с публикации"] != "—" else datetime.now(),
                        "channel_name": "YouTube",  # Имя канала не доступно через быстрый метод
                        "channel_url": video_data_df.iloc[0]["Канал URL"] if "Канал URL" in video_data_df.columns else None
                    }
                
                video_data_time = end_timer(f"Получение данных о видео: {url}")
                status_text.text(f"Получены данные о видео за {video_data_time:.2f}с")
                stats["processed_videos"] += 1
                
                # ИЗМЕНЕНИЯ: Получаем рекомендации для всех видео, но в source_videos добавляем только соответствующие критериям
                
                # Получаем рекомендации для видео независимо от критериев
                status_text.text(f"Получение рекомендаций для видео: {url}")
                start_timer(f"Получение рекомендаций для видео: {url}")
                # Используем быстрый метод вместо обычного
                recommendations = youtube_analyzer.get_recommended_videos_fast(url, limit=recommendations_per_video)
                rec_time = end_timer(f"Получение рекомендаций для видео: {url}")
                status_text.text(f"Получены рекомендации ({len(recommendations)}) за {rec_time:.2f}с")
                logger.info(f"Получено {len(recommendations)} рекомендаций для видео {url}")
                
                # Сохраняем URL рекомендаций для последующей обработки
                recommendation_urls = []
                for rec_info in recommendations:
                    rec_url = rec_info.get("url")
                    if rec_url:
                        # Очищаем URL от параметров
                        clean_rec_url = clean_youtube_url(rec_url)
                        recommendation_urls.append({
                            "url": clean_rec_url,
                            "source_video": clean_youtube_url(url)
                        })
                
                # Добавляем все рекомендации для этого видео в общий список
                all_recommendations.extend(recommendation_urls)
                logger.info(f"Добавлено {len(recommendation_urls)} рекомендаций для видео {url}")
                
                # Проверяем, соответствует ли видео заданным параметрам для добавления в таблицу
                if video_data and quick_filter_video(video_data):
                    video_data["source"] = f"Прямая ссылка: {link}"
                    source_videos.append(video_data)
                    stats["added_videos"] += 1
                else:
                    # Если видео не соответствует критериям, пропускаем его добавление в итоговую таблицу
                    if video_data:
                        status_text.text(f"Видео не соответствует критериям, не добавлено в таблицу: {url}")
                
                # Временно отключаем обновление статистики для прямой ссылки
                # update_stats()
                
                # Обновляем статистику по завершению обработки видео
                # Передаем только видео и рекомендации с текущего видео, а не общее количество
                current_source_videos = len(source_videos) - source_videos_before
                current_recommendations = len(all_recommendations) - recommendations_before
                update_stats(force=True, current_link=url, source_videos_count=current_source_videos, recommendations_count=current_recommendations)
        
        # Обработка собранных рекомендаций
        status_text.text(f"Обработка {len(all_recommendations)} рекомендаций...")
        logger.info(f"Начинаем обработку {len(all_recommendations)} собранных рекомендаций")
        
        # Удаляем дубликаты из списка рекомендаций
        unique_recommendations = {}
        for rec in all_recommendations:
            rec_url = rec["url"]
            # Если такой URL уже был, обновляем только источник
            if rec_url in unique_recommendations:
                unique_recommendations[rec_url]["sources"].append(rec["source_video"])
            else:
                unique_recommendations[rec_url] = {
                    "url": rec_url,
                    "sources": [rec["source_video"]]
                }
        
        # Преобразуем словарь обратно в список
        filtered_recommendations = list(unique_recommendations.values())
        status_text.text(f"Осталось {len(filtered_recommendations)} уникальных рекомендаций после удаления дубликатов")
        logger.info(f"После удаления дубликатов осталось {len(filtered_recommendations)} уникальных рекомендаций")
        
        # Счетчики для отслеживания обработанных и добавленных рекомендаций
        processed_recommendations = 0
        added_recommendations = 0
        
        # Получаем информацию о рекомендациях пакетами для оптимизации
        batch_size = 5  # Обрабатываем по 5 рекомендаций за раз
        for i in range(0, len(filtered_recommendations), batch_size):
            batch = filtered_recommendations[i:i+batch_size]
            status_text.text(f"Обработка пакета рекомендаций {i+1}-{min(i+batch_size, len(filtered_recommendations))} из {len(filtered_recommendations)}")
            
            # Засекаем время для всего пакета
            start_timer(f"Обработка пакета рекомендаций {i+1}-{min(i+batch_size, len(filtered_recommendations))}")
            
            for rec in batch:
                rec_url = rec["url"]
                processed_recommendations += 1
                
                # Получаем детали рекомендованного видео
                start_timer(f"Получение данных о рекомендации: {rec_url}")
                
                # Используем быстрый метод вместо get_video_details
                rec_data_df = youtube_analyzer.test_video_parameters_fast([rec_url])
                rec_data = None
                if not rec_data_df.empty:
                    # Преобразуем результат в формат словаря, совместимый с исходным
                    try:
                        rec_data = {
                            "url": rec_url,  # URL уже очищен на предыдущем этапе
                            "title": rec_data_df.iloc[0]["Заголовок"],
                            "views": rec_data_df.iloc[0]["Просмотры_число"] if "Просмотры_число" in rec_data_df.columns else int(rec_data_df.iloc[0]["Просмотры"].replace(" ", "")),
                            "publication_date": datetime.now() - timedelta(days=int(rec_data_df.iloc[0]["Дней с публикации"])) if rec_data_df.iloc[0]["Дней с публикации"] != "—" else datetime.now(),
                            "channel_name": "YouTube",  # Имя канала не доступно через быстрый метод
                            "channel_url": rec_data_df.iloc[0]["Канал URL"] if "Канал URL" in rec_data_df.columns else None
                        }
                    except Exception as e:
                        logger.error(f"Ошибка при обработке данных рекомендации {rec_url}: {e}")
                        # Создаем минимальный набор данных, чтобы рекомендация не была потеряна
                        rec_data = {
                            "url": rec_url,
                            "title": "Не удалось получить заголовок",
                            "views": min_video_views,  # Гарантируем, что видео пройдет фильтрацию по просмотрам
                            "publication_date": datetime.now(),  # Гарантируем, что видео пройдет фильтрацию по дате
                            "channel_name": "YouTube",
                            "channel_url": None
                        }
                else:
                    logger.warning(f"Не удалось получить данные для рекомендации {rec_url}")
                
                video_data_time = end_timer(f"Получение данных о рекомендации: {rec_url}")
                stats["processed_videos"] += 1
                
                # Применяем фильтры к рекомендованным видео
                if rec_data and quick_filter_video(rec_data):
                    # Формируем список источников в удобном формате
                    # Убедимся, что источники тоже очищены от параметров
                    clean_sources = [clean_youtube_url(src) for src in rec["sources"]]
                    source_str = ", ".join([f"видео {src.split('watch?v=')[-1]}" for src in clean_sources])
                    rec_data["source"] = f"Рекомендация для: {source_str}"
                    results.append(rec_data)
                    stats["added_videos"] += 1
                    added_recommendations += 1
                    logger.info(f"Рекомендация {rec_url} добавлена в результаты (всего: {added_recommendations})")
                else:
                    if rec_data:
                        logger.info(f"Рекомендация {rec_url} не прошла фильтрацию")
                
                # Убираем лишнее обновление статистики для каждого видео
            
            # Фиксируем время всего пакета
            batch_time = end_timer(f"Обработка пакета рекомендаций {i+1}-{min(i+batch_size, len(filtered_recommendations))}")
            status_text.text(f"Пакет обработан за {batch_time:.2f}с")
            
            # Обновляем статистику после обработки пакета рекомендаций
            # Используем обновление только по завершении пакета, а не на каждой итерации
            # update_stats(force=False, recommendations_count=added_recommendations)
        
        # Добавляем исходные видео к результатам
        # Важно: сначала добавляем исходные видео, чтобы они не были удалены как дубликаты
        results = source_videos + results
        
        # Завершаем прогресс
        progress_bar.progress(1.0)
        status_text.text("Обработка завершена!")
        
        # Финальное обновление статистики больше не нужно, так как вся информация
        # уже отображена для каждого канала/видео
        # update_stats(force=True, source_videos_count=len(source_videos), recommendations_count=len(results) - len(source_videos))
        
    except Exception as e:
        status_text.error(f"Произошла ошибка: {e}")
        logger.error(f"Ошибка при тестировании рекомендаций: {e}")
        traceback.print_exc()
    finally:
        # Закрываем драйвер только если он не был передан извне
        if youtube_analyzer and youtube_analyzer is not existing_analyzer:
            youtube_analyzer.quit_driver()
    
    # Создаем датафрейм из результатов
    if results:
        # Формируем датафрейм с нужными колонками
        df = pd.DataFrame(results)
        
        # Очищаем все URL-адреса в датафрейме от дополнительных параметров
        if "url" in df.columns:
            df["url"] = df["url"].apply(clean_youtube_url)
        
        # Удаляем дубликаты по URL видео, сохраняя порядок добавления
        # Это гарантирует, что исходные видео (которые были добавлены первыми) сохранятся
        seen_urls = set()
        unique_df_rows = []
        
        for idx, row in df.iterrows():
            url = row["url"]
            if url not in seen_urls:
                seen_urls.add(url)
                unique_df_rows.append(row)
        
        df = pd.DataFrame(unique_df_rows)
        
        # Добавляем нумерацию, начинающуюся с 1 после удаления дубликатов
        df.index = range(1, len(df) + 1)
        
        # Выбираем и переименовываем нужные колонки
        columns_to_show = {
            "url": "Ссылка на видео",
            "title": "Заголовок видео",
            "publication_date": "Дата публикации",
            "views": "Количество просмотров",
            "source": "Источник видео",
            "channel_url": "Канал"
        }
        
        # Фильтруем только существующие колонки
        existing_columns = {k: v for k, v in columns_to_show.items() if k in df.columns}
        
        if existing_columns:
            df = df[list(existing_columns.keys())]
            df = df.rename(columns=existing_columns)
            
            # Удаляем дубликаты по URL видео
            df = df.drop_duplicates(subset=["Ссылка на видео"])
            
            # Преобразуем ссылки в активные для отображения в Streamlit
            df["Ссылка на видео"] = df["Ссылка на видео"].apply(
                lambda x: f'<a href="{x}" target="_blank">{x}</a>' if isinstance(x, str) else x
            )
            
            # Преобразуем ссылки на каналы в активные для отображения в Streamlit
            if "Канал" in df.columns:
                df["Канал"] = df["Канал"].apply(
                    lambda x: f'<a href="{x}" target="_blank">{x}</a>' if isinstance(x, str) and x else x
                )
                
                # Сохраняем URL канала, если колонка существует
                if "Канал" in df.columns and "channel_url" not in df.columns:
                    df["URL канала"] = df["Канал"]
            
            # Удаляем ненужные строки, вызывающие ошибку
            # Колонки Ссылка на канал и Название канала не существуют в этом контексте
            
            return df
        else:
            return pd.DataFrame()
    else:
        return pd.DataFrame()

def main():
    # Настройка логгера
    setup_logging()
    
    # Загружаем API ключ из secrets
    api_key = load_api_key_from_secrets()
    if api_key:
        st.session_state["youtube_api_key"] = api_key
        logger.info("YouTube API ключ загружен в сессию")
    
    st.title("YouTube Researcher 🎬")

    # Боковая панель с настройками
    with st.sidebar:
        st.header("Настройки")
        
        # Часть 1: Настройки прокси
        with st.expander("Настройки прокси", expanded=True):
            use_proxy = st.checkbox("Использовать прокси", value=False)
            
            proxy_option = st.radio(
                "Выберите источник прокси:",
                options=["Загрузить из файла", "Ввести вручную"],
                index=0,
                disabled=not use_proxy
            )
            
            proxy_list = []
            
            if proxy_option == "Загрузить из файла" and use_proxy:
                proxy_file = st.file_uploader("Загрузите файл с прокси (по одному на строку)", type=["txt"])
                
                if proxy_file:
                    proxy_content = proxy_file.read().decode("utf-8")
                    proxy_list = [line.strip() for line in proxy_content.split("\n") if line.strip()]
                    st.success(f"Загружено {len(proxy_list)} прокси из файла.")
                    
                    # Опция проверки прокси
                    check_proxies = st.checkbox("Проверить работоспособность прокси", value=True)
                    
                    if check_proxies and st.button("Проверить прокси"):
                        with st.spinner("Проверка прокси..."):
                            working_proxies = check_proxies_availability(proxy_list)
                            
                            if working_proxies:
                                st.success(f"Работающих прокси: {len(working_proxies)} из {len(proxy_list)}")
                                proxy_list = working_proxies
                            else:
                                st.error("Не найдено работающих прокси!")
                                
                                # Опция использовать все прокси без проверки
                                force_use_all = st.checkbox("Использовать все прокси без проверки")
                                if force_use_all:
                                    st.warning(f"Будут использованы все {len(proxy_list)} прокси без проверки.")
                                else:
                                    proxy_list = []
            
            elif proxy_option == "Ввести вручную" and use_proxy:
                proxy_input = st.text_area("Введите прокси (по одному на строку)", height=100)
                
                if proxy_input:
                    proxy_list = [line.strip() for line in proxy_input.split("\n") if line.strip()]
                    st.success(f"Добавлено {len(proxy_list)} прокси.")
                    
                    # Опция проверки прокси
                    check_proxies = st.checkbox("Проверить работоспособность прокси", value=True)
                    
                    if check_proxies and st.button("Проверить прокси"):
                        with st.spinner("Проверка прокси..."):
                            working_proxies = check_proxies_availability(proxy_list)
                            
                            if working_proxies:
                                st.success(f"Работающих прокси: {len(working_proxies)} из {len(proxy_list)}")
                                proxy_list = working_proxies
                            else:
                                st.error("Не найдено работающих прокси!")
                                
                                # Опция использовать все прокси без проверки
                                force_use_all = st.checkbox("Использовать все прокси без проверки")
                                if force_use_all:
                                    st.warning(f"Будут использованы все {len(proxy_list)} прокси без проверки.")
                                else:
                                    proxy_list = []
        
    # Основное содержимое
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(["Получение рекомендаций", "Релевантность", "Результаты", "Тестирование параметров", "Поиск похожих каналов", "Тест API каналов", "Тест API видео"])
    
    with tab1:
        # Стадия 1: Авторизация Google и настройка предварительного просмотра
        st.header("Стадия 1: Авторизация и предварительное обучение")
        
        # Настройки аккаунта Google
        with st.expander("Авторизация Google", expanded=True):
            use_google_account = st.checkbox("Авторизоваться в аккаунте Google", value=False)
            google_account = None
            
            if use_google_account:
                # Добавляем выбор источника учетных данных
                auth_source = st.radio(
                    "Источник учетных данных:",
                    options=["Ввести вручную", "Использовать из secrets.toml"],
                    index=1
                )
                
                if auth_source == "Ввести вручную":
                    col1, col2 = st.columns(2)
                    with col1:
                        email = st.text_input("Email аккаунта Google", key="google_email")
                    with col2:
                        password = st.text_input("Пароль", type="password", key="google_password")
                    
                    # Создаем словарь с данными аккаунта
                    if email and password:
                        google_account = {
                            "email": email,
                            "password": password
                        }
                else:
                    # Пытаемся загрузить учетные данные из secrets.toml
                    try:
                        if "google" in st.secrets and st.secrets["google"]["email"] and st.secrets["google"]["password"]:
                            google_account = {
                                "email": st.secrets["google"]["email"],
                                "password": st.secrets["google"]["password"]
                            }
                            st.success(f"✅ Учетные данные Google успешно загружены из secrets.toml ({google_account['email']})")
                        else:
                            st.error("❌ В файле secrets.toml не указаны email и/или пароль для Google аккаунта")
                    except Exception as e:
                        st.error(f"❌ Ошибка при загрузке учетных данных из secrets.toml: {str(e)}")
                        st.info("Проверьте наличие файла .streamlit/secrets.toml и корректность его содержимого")
                
                # Отдельная кнопка для авторизации
                auth_col1, auth_col2 = st.columns([1, 2])
                with auth_col1:
                    auth_button = st.button("🔑 Авторизоваться в Google")
                
                with auth_col2:
                    auth_status = st.empty()
                    if st.session_state.get("is_logged_in", False):
                        auth_status.success(f"✅ Вы авторизованы как {st.session_state.get('google_account', {}).get('email', '')}")

                if auth_button:
                    if not google_account or not google_account.get("email") or not google_account.get("password"):
                        auth_status.error("❌ Необходимо указать email и пароль от аккаунта Google")
                    else:
                        with st.spinner("Выполняется авторизация в Google..."):
                            # Создаем анализатор YouTube только для авторизации
                            auth_analyzer = YouTubeAnalyzer(
                                headless=True,  # Используем невидимый режим (headless) для скрытия браузера
                                use_proxy=use_proxy,
                                google_account=google_account
                            )
                            
                            # Инициализируем драйвер
                            auth_analyzer.setup_driver()
                            
                            if auth_analyzer.driver:
                                # Выполняем авторизацию
                                success = auth_analyzer.login_to_google()
                                
                                if success or auth_analyzer.is_logged_in:
                                    st.session_state.google_account = google_account
                                    st.session_state.is_logged_in = True
                                    st.session_state.auth_analyzer = auth_analyzer
                                    auth_status.success(f"✅ Авторизация в Google успешно выполнена! ({google_account['email']})")
                                else:
                                    auth_status.error("❌ Не удалось выполнить авторизацию в Google. Проверьте данные аккаунта.")
                                    
                                    # Закрываем драйвер в случае неудачи
                                    try:
                                        auth_analyzer.quit_driver()
                                    except:
                                        pass
                            else:
                                auth_status.error("❌ Не удалось инициализировать браузер для авторизации.")
            else:
                st.info("Включите авторизацию Google для входа в аккаунт")
                
            # Информация для пользователя
            st.info("""
            ⚠️ Обратите внимание:
            - При первом входе может потребоваться дополнительное подтверждение
            - Если включена двухфакторная аутентификация, вам потребуется ввести код подтверждения
            - Данные аккаунта хранятся только в памяти сессии и не сохраняются
            - Для сохранения учетных данных можно использовать файл .streamlit/secrets.toml
            """)
        
        # Настройки предварительного просмотра
        with st.expander("Настройки предварительного просмотра", expanded=True):
            enable_prewatch = st.checkbox("Включить предварительный просмотр видео", value=False)
            prewatch_settings = None
            
            if enable_prewatch:
                col1, col2 = st.columns(2)
                with col1:
                    total_videos = st.number_input("Количество видео для просмотра", min_value=1, max_value=100, value=20)
                    distribution = st.radio(
                        "Распределение просмотра:",
                        options=["Равномерно по всем каналам", "Только самые свежие видео"],
                        index=0
                    )
                with col2:
                    min_watch_time = st.slider("Минимальное время просмотра (сек)", min_value=5, max_value=60, value=15)
                    max_watch_time = st.slider("Максимальное время просмотра (сек)", min_value=min_watch_time, max_value=120, value=45)
                    like_probability = st.slider("Вероятность лайка (0-1)", min_value=0.0, max_value=1.0, value=0.7, step=0.1)
                    watch_percentage = st.slider("Процент просмотра видео (0-1)", min_value=0.1, max_value=1.0, value=0.3, step=0.1)
                
                # Создаем словарь с настройками предварительного просмотра
                prewatch_settings = {
                    "enabled": enable_prewatch,
                    "total_videos": total_videos,
                    "distribution": distribution,
                    "min_watch_time": min_watch_time,
                    "max_watch_time": max_watch_time,
                    "like_probability": like_probability,
                    "watch_percentage": watch_percentage
                }
                
                # Отдельная секция для запуска предварительного обучения
                st.subheader("Запуск предварительного обучения")
                
                # Проверяем статус авторизации
                if not st.session_state.get("is_logged_in", False):
                    st.warning("⚠️ Для предварительного обучения необходимо сначала авторизоваться в Google аккаунте")
                else:
                    # Поле для ввода ссылок для предварительного просмотра
                    prewatch_links = st.text_area(
                        "Введите ссылки на YouTube видео для просмотра (по одной на строку)",
                        height=100
                    )
                    
                    # Создаем два равных столбца для кнопок
                    method_col1, method_col2 = st.columns([1, 1])
                    
                    # Размещаем кнопки в столбцах
                    with method_col1:
                        auto_method = st.button("🤖 Автоматический просмотр", key="auto_method", help="Запускает автоматический просмотр видео через браузер (YouTube может блокировать этот метод)")
                    
                    with method_col2:
                        manual_method = st.button("👤 Ручной просмотр (рекомендуется)", key="manual_method", help="Создает HTML файл, который вы открываете в своем браузере для просмотра видео")
                    
                    # Область для отображения статуса и результатов
                    prewatch_status = st.empty()
                    
                    # Обработка нажатия на кнопку "Ручной просмотр"
                    if manual_method:
                        if not prewatch_links.strip():
                            prewatch_status.error("❌ Необходимо указать хотя бы одну ссылку на YouTube видео для просмотра")
                        else:
                            # Получаем список ссылок
                            video_links = [link.strip() for link in prewatch_links.split("\n") if link.strip()]
                            valid_links = [link for link in video_links if "youtube.com" in link or "youtu.be" in link]
                            
                            if not valid_links:
                                prewatch_status.error("❌ Не найдено валидных ссылок YouTube. Пожалуйста, проверьте список ссылок.")
                            else:
                                prewatch_status.info(f"⏳ Создаем HTML файл для ручного просмотра {len(valid_links)} видео...")
                                
                                try:
                                    # Создаем HTML файл для ручного просмотра
                                    html_content = create_manual_viewing_html(valid_links[:total_videos], 
                                                                        min_watch_time, max_watch_time)
                                    
                                    # Кодируем содержимое в base64 для скачивания
                                    b64 = base64.b64encode(html_content.encode()).decode()
                                    
                                    # Создаем ссылку для скачивания и выводим её
                                    download_html = f'<a href="data:text/html;base64,{b64}" download="youtube_videos_to_watch.html"><button style="background-color: #4CAF50; color: white; padding: 12px 20px; border: none; border-radius: 4px; cursor: pointer; font-size: 16px;">⬇️ Скачать HTML файл с видео</button></a>'
                                    
                                    prewatch_status.success(f"✅ HTML файл для просмотра {len(valid_links[:total_videos])} видео готов!")
                                    st.markdown(download_html, unsafe_allow_html=True)
                                    
                                    # Инструкции по использованию
                                    st.info("""
                                    ### Инструкции по использованию:
                                    1. Скачайте HTML файл по кнопке выше
                                    2. Откройте файл в браузере, где вы авторизованы в YouTube
                                    3. Нажмите кнопку "Начать просмотр" в HTML файле
                                    4. Браузер будет автоматически открывать видео одно за другим
                                    5. Каждое видео будет просматриваться указанное время
                                    6. После просмотра видео должны появиться в истории YouTube
                                    
                                    ⚠️ **Важно**: Не закрывайте HTML страницу до завершения просмотра всех видео.
                                    """)
                                except Exception as e:
                                    prewatch_status.error(f"❌ Ошибка при создании HTML файла: {str(e)}")
                    
                    # Обработка нажатия на кнопку "Автоматический просмотр"
                    if auto_method:
                        if not prewatch_links.strip():
                            prewatch_status.error("❌ Необходимо указать хотя бы одну ссылку на YouTube видео для просмотра")
                        else:
                            # Получаем список ссылок
                            video_links = [link.strip() for link in prewatch_links.split("\n") if link.strip()]
                            valid_links = [link for link in video_links if "youtube.com" in link or "youtu.be" in link]
                            
                            if not valid_links:
                                prewatch_status.error("❌ Не найдено валидных ссылок YouTube. Пожалуйста, проверьте список ссылок.")
                            else:
                                try:
                                    # Получаем существующий анализатор YouTube
                                    existing_analyzer = st.session_state.get("auth_analyzer")
                                    
                                    if existing_analyzer and existing_analyzer.driver:
                                        # Используем существующий драйвер для просмотра
                                        prewatch_status.info(f"⏳ Запуск автоматического просмотра {len(valid_links[:total_videos])} видео...")
                                        
                                        # Не меняем режим headless, используем текущее значение
                                        
                                        existing_analyzer.prewatch_videos(
                                            valid_links[:total_videos],
                                            min_watch_time=min_watch_time,
                                            max_watch_time=max_watch_time,
                                            like_probability=like_probability,
                                            watch_percentage=watch_percentage
                                        )
                                        prewatch_status.success(f"✅ Автоматический просмотр завершен! Просмотрено {len(valid_links[:total_videos])} видео.")
                                        prewatch_status.warning("⚠️ Если видео не появились в истории YouTube, используйте ручной метод просмотра.")
                                    else:
                                        prewatch_status.error("❌ Драйвер не инициализирован. Попробуйте авторизоваться заново.")
                                except Exception as e:
                                    prewatch_status.error(f"❌ Ошибка при автоматическом просмотре: {str(e)}")
        
        # Стадия 2: Сбор рекомендаций
        st.header("Стадия 2: Сбор рекомендаций")
        
        # Основные настройки сбора рекомендаций
        with st.expander("Источники данных", expanded=True):
            source_option = st.radio(
                "Выберите источник ссылок:",
                options=["Ввести вручную", "Загрузить из файла"],
                index=0
            )
            
            source_links = []
            
            if source_option == "Ввести вручную":
                source_input = st.text_area(
                    "Введите ссылки на видео или каналы YouTube (по одной на строку)",
                    height=150
                )
                
                if source_input:
                    source_links = [line.strip() for line in source_input.split("\n") if line.strip()]
            else:  # Загрузить из файла
                source_file = st.file_uploader("Загрузите файл со ссылками (по одной на строку)", type=["txt"])
                
                if source_file:
                    source_content = source_file.read().decode("utf-8")
                    source_links = [line.strip() for line in source_content.split("\n") if line.strip()]
            
            if source_links:
                st.success(f"Загружено {len(source_links)} ссылок.")
                
                # Выводим пример ссылок (не более 5)
                if len(source_links) > 0:
                    st.write("Примеры ссылок:")
                    for i, link in enumerate(source_links[:5]):
                        st.write(f"{i+1}. {link}")
                    
                    if len(source_links) > 5:
                        st.write(f"...и еще {len(source_links) - 5} ссылок")
        
        # Параметры сбора рекомендаций, перемещенные из левой колонки
        with st.expander("Параметры сбора", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                channel_videos_limit = st.number_input(
                    "Количество последних видео с канала", 
                    min_value=1, 
                    max_value=20, 
                    value=5
                )
            with col2:
                recommendations_per_video = st.number_input(
                    "Количество рекомендаций для каждого видео", 
                    min_value=1, 
                    max_value=20, 
                    value=5
                )
            
            col3, col4 = st.columns(2)
            with col3:
                max_days_since_publication = st.number_input(
                    "Время с момента публикации (дней)", 
                    min_value=1, 
                    max_value=100000,  # Увеличено до 10 лет (3650 дней)
                    value=7
                )
            with col4:
                min_video_views = st.number_input(
                    "Минимальное количество просмотров", 
                    min_value=0, 
                    max_value=1000000, 
                    value=10000,
                    step=1000
                )
        
        # Кнопка сбора рекомендаций
        if st.button("Собрать рекомендации"):
            if source_links:
                with st.spinner("Сбор рекомендаций..."):
                    # Если пользователь уже авторизовался, используем сохраненный драйвер
                    existing_analyzer = st.session_state.get("auth_analyzer")
                    
                    # Вызываем функцию сбора рекомендаций с переданным драйвером
                    results_df = test_recommendations(
                        source_links, 
                        google_account=google_account, 
                        prewatch_settings=prewatch_settings,
                        channel_videos_limit=channel_videos_limit,
                        recommendations_per_video=recommendations_per_video,
                        max_days_since_publication=max_days_since_publication,
                        min_video_views=min_video_views,
                        existing_analyzer=existing_analyzer  # Передаем существующий драйвер, если есть
                    )
                    
                    if not results_df.empty:
                        st.session_state["results_df"] = results_df
                        st.success(f"Собрано {len(results_df)} результатов.")
                        
                        # Гарантируем, что таблица будет отображаться всегда
                        display_results_tab1()
                        
                        # Автоматический переход на вкладку с результатами
                        st.info("Перейдите на вкладку 'Релевантность' для фильтрации результатов.")
                    else:
                        st.error("Не удалось собрать данные. Проверьте логи для подробностей.")
                        # Вывод диагностической информации
                        st.error("Диагностическая информация:")
                        st.write("- Проверьте соединение с интернетом")
                        st.write("- Проверьте работоспособность прокси (если используются)")
                        st.write("- Проверьте настройки драйвера и сети")
            else:
                st.error("Необходимо указать хотя бы одну ссылку на YouTube для сбора рекомендаций.")
                # Проверяем наличие данных в сессии и отображаем их, если они есть
                if "results_df" in st.session_state and not st.session_state["results_df"].empty:
                    st.success(f"Показаны предыдущие результаты ({len(st.session_state['results_df'])} записей).")
                    display_results_tab1()
    
    with tab2:
        # Стадия 3: Фильтрация по релевантности
        st.header("Стадия 3: Фильтрация по релевантности")
        
        # Перемещенные параметры для фильтрации
        with st.expander("Параметры фильтрации", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                min_views = st.number_input(
                    "Минимальное количество просмотров", 
                    min_value=0, 
                    value=1000, 
                    step=100
                )
            with col2:
                max_days = st.number_input(
                    "Максимальное количество дней после публикации", 
                    min_value=1,
                    max_value=100000,  # Добавлено максимальное значение 10 лет (3650 дней)
                    value=30, 
                    step=1
                )
        
        # Поиск по ключевым словам
        with st.expander("Поиск по ключевым словам", expanded=True):
            search_query = st.text_input("Поиск по названию видео (оставьте пустым, чтобы показать все)", key="search_query")
        
        # Кнопка для фильтрации результатов
        if st.button("Фильтровать результаты"):
            if "results_df" in st.session_state and not st.session_state["results_df"].empty:
                df = st.session_state["results_df"].copy()
                
                # Фильтрация по просмотрам
                if "views" in df.columns:
                    df = filter_by_views(df, min_views=min_views)
                
                # Фильтрация по дате публикации
                if "publication_date" in df.columns:
                    df = filter_by_date(df, max_days=max_days)
                
                # Фильтрация по поисковому запросу
                if search_query:
                    df = filter_by_search(df, search_query)
                
                # Сохраняем отфильтрованные результаты
                st.session_state["filtered_df"] = df
                
                if not df.empty:
                    st.success(f"Найдено {len(df)} результатов после фильтрации.")
                    # Используем функцию для отображения результатов
                    display_results_tab2()
                    
                    # Автоматический переход на вкладку с результатами
                    st.info("Перейдите на вкладку 'Результаты' для просмотра и экспорта.")
                else:
                    st.warning("Не найдено результатов, соответствующих критериям фильтрации.")
            else:
                st.error("Сначала выполните сбор рекомендаций на первой вкладке.")
        
        # Проверяем наличие отфильтрованных данных и отображаем их
        elif "filtered_df" in st.session_state and not st.session_state["filtered_df"].empty:
            st.success(f"Показаны предыдущие результаты фильтрации ({len(st.session_state['filtered_df'])} записей).")
            display_results_tab2()
    
    with tab3:
        # Отображение результатов
        st.header("Результаты анализа")
        
        if ("filtered_df" in st.session_state and not st.session_state["filtered_df"].empty) or \
           ("results_df" in st.session_state and not st.session_state["results_df"].empty):
            
            # Используем функцию для отображения результатов
            display_results_tab3()
        else:
            st.warning("Нет данных для отображения. Сначала соберите рекомендации на первой вкладке.")
    
    with tab4:
        # Раздел для тестирования параметров видео
        render_video_tester_section()
    
    with tab5:
        # Раздел для поиска похожих каналов
        render_similar_channels_section()
    
    with tab6:
        # Раздел для тестирования API каналов
        render_api_tester_section()
    
    with tab7:
        # Раздел для тестирования API видео
        render_video_api_tester_section()

# Функция для отображения раздела тестирования параметров видео
def render_video_tester_section():
    """
    Отображает раздел тестирования параметров видео в Streamlit приложении.
    """
    st.markdown("## Тестирование алгоритма сбора параметров видео")
    
    # Создаем разворачивающуюся секцию
    with st.expander("Развернуть раздел тестирования", expanded=False):
        st.markdown("""
        Этот инструмент позволяет проверить работу алгоритма сбора данных YouTube видео.
        Введите ссылки на видео (по одной в строке) и запустите анализ, чтобы увидеть:
        - Количество дней с момента публикации
        - Количество просмотров
        """)
        
        # Поле для ввода ссылок на видео
        video_urls = st.text_area(
            "Ссылки на YouTube видео (по одной в строке):",
            height=150,
            placeholder="https://www.youtube.com/watch?v=..."
        )
        
        # Опция быстрого анализа
        use_fast_method = st.checkbox("Использовать быстрый метод анализа (рекомендуется)", value=True)
        
        # Кнопка для запуска анализа
        start_analysis = st.button("Проанализировать видео")
        
        # Обработка нажатия кнопки
        if start_analysis and video_urls:
            # Разбиваем текст на строки и фильтруем пустые
            urls = [url.strip() for url in video_urls.strip().split('\n') if url.strip()]
            
            if not urls:
                st.error("Пожалуйста, введите хотя бы одну ссылку на YouTube видео.")
                return
            
            # Проверяем формат URL
            invalid_urls = []
            valid_urls = []
            
            for url in urls:
                if "youtube.com/watch?v=" in url or "youtu.be/" in url:
                    # Очищаем URL
                    clean_url = clean_youtube_url(url)
                    valid_urls.append(clean_url)
                else:
                    invalid_urls.append(url)
            
            if invalid_urls:
                st.error(f"Следующие URL имеют неверный формат:\n" + "\n".join(invalid_urls))
                return
            
            # Запускаем анализ с индикатором прогресса и замером времени
            start_time = time.time()
            
            with st.spinner(f"Анализ {len(valid_urls)} видео..."):
                progress_bar = st.progress(0)
                
                try:
                    # Инициализируем YouTube анализатор
                    analyzer = YouTubeAnalyzer(headless=True, use_proxy=False)
                    
                    # Получаем и обрабатываем результаты
                    if use_fast_method:
                        results_df = analyzer.test_video_parameters_fast(valid_urls)
                    else:
                        results_df = analyzer.test_video_parameters(valid_urls)
                    
                    # Обновляем прогресс-бар до 100%
                    progress_bar.progress(100)
                    
                    # Закрываем драйвер
                    analyzer.quit_driver()
                    
                    # Вычисляем время выполнения
                    elapsed_time = time.time() - start_time
                    
                    # Отображаем результаты
                    if not results_df.empty:
                        st.success(f"Анализ завершен за {elapsed_time:.2f} сек! Проанализировано {len(results_df)} видео.")
                        
                        # Преобразуем столбец просмотров в числовые значения для сортировки, если есть
                        if "Просмотры_число" in results_df.columns:
                            sorting_df = results_df.sort_values(by="Просмотры_число", ascending=False)
                            # Удаляем служебный столбец перед отображением
                            sorting_df = sorting_df.drop("Просмотры_число", axis=1)
                            # Нумерация с 1 и отображение индекса
                            sorting_df = sorting_df.reset_index(drop=True)
                            sorting_df.index = range(1, len(sorting_df) + 1)
                            st.dataframe(sorting_df)
                        else:
                            # Нумерация с 1 и отображение индекса
                            results_df = results_df.reset_index(drop=True)
                            results_df.index = range(1, len(results_df) + 1)
                            st.dataframe(results_df)
                    else:
                        st.warning("Не удалось получить данные о видео.")
                
                except Exception as e:
                    st.error(f"Произошла ошибка при анализе видео: {str(e)}")
                    # Отображаем более подробную информацию в expander
                    with st.expander("Подробности ошибки"):
                        st.exception(e)
        
        elif start_analysis:
            st.warning("Пожалуйста, введите хотя бы одну ссылку на YouTube видео.")

# После функции parse_youtube_url добавляем новую функцию

def clean_youtube_url(url: str) -> str:
    """
    Очищает URL YouTube от параметров, оставляя только базовый URL с идентификатором видео.
    
    Args:
        url (str): Исходный URL YouTube.
        
    Returns:
        str: Очищенный URL YouTube в формате https://www.youtube.com/watch?v=ID_VIDEO
    """
    if not url or not isinstance(url, str):
        return url
    
    # Проверяем, что это YouTube URL
    if "youtube.com/watch" not in url and "youtu.be/" not in url:
        return url
    
    try:
        # Обработка коротких ссылок youtu.be
        if "youtu.be/" in url:
            video_id = url.split("youtu.be/")[1].split("?")[0].split("#")[0]
            return f"https://www.youtube.com/watch?v={video_id}"
        
        # Обработка стандартных ссылок youtube.com/watch?v=
        if "youtube.com/watch" in url:
            # Находим параметр v=
            if "v=" in url:
                video_id = url.split("v=")[1].split("&")[0].split("#")[0]
                return f"https://www.youtube.com/watch?v={video_id}"
            
        # Если не удалось обработать, возвращаем исходный URL
        return url
    except Exception as e:
        logger.warning(f"Ошибка при очистке YouTube URL: {e}")
        return url

# Добавляем новую функцию для отображения результатов на вкладке 1
def display_results_tab1():
    """
    Функция для отображения таблицы с результатами и прямой ссылки на CSV на вкладке "Получение рекомендаций".
    """
    if "results_df" in st.session_state and not st.session_state["results_df"].empty:
        # Нумерация с 1 и отображение индекса с поддержкой HTML
        results_df_display = st.session_state["results_df"].copy()
        st.write(results_df_display.to_html(escape=False), unsafe_allow_html=True)
        
        # Сразу создаем ссылку для скачивания без кнопки
        export_df = st.session_state["results_df"].copy()
        if "Ссылка на видео" in export_df.columns:
            export_df["Ссылка на видео"] = export_df["Ссылка на видео"].str.replace(r'<a href="(.+?)".*?>.*?</a>', r'\1', regex=True)
        
        # Очищаем колонку "Канал" от HTML-тегов для экспорта
        if "Канал" in export_df.columns:
            export_df["Канал"] = export_df["Канал"].str.replace(r'<a href="(.+?)".*?>.*?</a>', r'\1', regex=True)
        
        csv = export_df.to_csv(index=False, sep='\t')
        b64 = base64.b64encode(csv.encode()).decode()
        href = f'<div style="text-align: right; margin: 10px 0;"><a href="data:file/csv;base64,{b64}" download="youtube_results.tsv" style="background-color: #4CAF50; color: white; padding: 8px 16px; text-decoration: none; border-radius: 4px;">📊 Скачать TSV файл</a></div>'
        st.markdown(href, unsafe_allow_html=True)

# Добавляем функцию для отображения результатов на вкладке "Релевантность"
def display_results_tab2():
    """
    Функция для отображения таблицы с отфильтрованными результатами на вкладке "Релевантность".
    """
    if "filtered_df" in st.session_state and not st.session_state["filtered_df"].empty:
        # Нумерация с 1 и отображение индекса с поддержкой HTML
        df_display = st.session_state["filtered_df"].copy()
        st.write(df_display.to_html(escape=False), unsafe_allow_html=True)
        
        # Сразу создаем ссылку для скачивания без кнопки
        export_df = st.session_state["filtered_df"].copy()
        if "Ссылка на видео" in export_df.columns:
            export_df["Ссылка на видео"] = export_df["Ссылка на видео"].str.replace(r'<a href="(.+?)".*?>.*?</a>', r'\1', regex=True)
        
        # Очищаем колонку "Канал" от HTML-тегов для экспорта
        if "Канал" in export_df.columns:
            export_df["Канал"] = export_df["Канал"].str.replace(r'<a href="(.+?)".*?>.*?</a>', r'\1', regex=True)
        
        csv = export_df.to_csv(index=False, sep='\t')
        b64 = base64.b64encode(csv.encode()).decode()
        href = f'<div style="text-align: right; margin: 10px 0;"><a href="data:file/csv;base64,{b64}" download="youtube_filtered_results.tsv" style="background-color: #4CAF50; color: white; padding: 8px 16px; text-decoration: none; border-radius: 4px;">📊 Скачать TSV файл</a></div>'
        st.markdown(href, unsafe_allow_html=True)

# Добавляем функцию для отображения результатов на вкладке "Результаты"
def display_results_tab3():
    """
    Функция для отображения таблицы с результатами на вкладке "Результаты".
    """
    # Используем отфильтрованные результаты, если они есть, иначе - все результаты
    if "filtered_df" in st.session_state and not st.session_state["filtered_df"].empty:
        display_df = st.session_state["filtered_df"].copy()
    else:
        display_df = st.session_state["results_df"].copy()
    
    # Отображаем результаты
    # Нумерация с 1 и отображение индекса с поддержкой HTML
    display_df = display_df.reset_index(drop=True)
    display_df.index = range(1, len(display_df) + 1)
    st.write(display_df.to_html(escape=False), unsafe_allow_html=True)
    
    # Сразу создаем ссылку для скачивания без кнопки
    export_df = display_df.copy()
    if "Ссылка на видео" in export_df.columns:
        export_df["Ссылка на видео"] = export_df["Ссылка на видео"].str.replace(r'<a href="(.+?)".*?>.*?</a>', r'\1', regex=True)
    
    # Очищаем колонку "Канал" от HTML-тегов для экспорта
    if "Канал" in export_df.columns:
        export_df["Канал"] = export_df["Канал"].str.replace(r'<a href="(.+?)".*?>.*?</a>', r'\1', regex=True)
    
    csv = export_df.to_csv(index=False, sep='\t')
    b64 = base64.b64encode(csv.encode()).decode()
    href = f'<div style="text-align: right; margin: 10px 0;"><a href="data:file/csv;base64,{b64}" download="youtube_final_results.tsv" style="background-color: #4CAF50; color: white; padding: 8px 16px; text-decoration: none; border-radius: 4px;">📊 Скачать TSV файл</a></div>'
    st.markdown(href, unsafe_allow_html=True)

# Функция для отображения раздела поиска похожих каналов через рекомендации YouTube.
def render_similar_channels_section():
    """
    Отображает раздел поиска похожих каналов через рекомендации YouTube.
    """
    st.markdown("## Поиск похожих каналов")
    
    with st.expander("Описание инструмента", expanded=False):
        st.markdown("""
        Этот инструмент позволяет найти похожие YouTube каналы на основе рекомендуемых видео.
        
        **Принцип работы:**
        1. Вы вводите список каналов по заданной тематике
        2. Инструмент собирает последние видео с этих каналов
        3. Для каждого видео анализируется список рекомендаций YouTube
        4. Из рекомендаций извлекаются уникальные каналы и их параметры
        5. Результаты фильтруются и сортируются по заданным критериям
        
        **Этот инструмент поможет:**
        - Найти быстрорастущие каналы в выбранной нише
        - Обнаружить новые источники контента по вашей теме
        - Определить потенциальных конкурентов или партнеров
        """)
    
    # Добавляем уведомление о возможных проблемах с доступом к данным каналов
    with st.expander("Важная информация о доступе к данным каналов", expanded=True):
        st.warning("⚠️ **Информация о блокировке доступа к каналам**")
        st.markdown("""
        YouTube может блокировать доступ к информации о каналах в следующих случаях:
        1. Требуется вход в аккаунт для просмотра контента
        2. Показывается страница "Прежде чем перейти к YouTube" с требованием принять соглашение
        3. IP-адрес обнаружен как автоматизированный запрос
        
        **Решения:**
        - YouTube API ключ используется автоматически если он настроен в файле .streamlit/secrets.toml
        - Используйте авторизацию в Google аккаунте
        - Выполняйте небольшое количество запросов за сеанс
        
        Если параметры каналов отображаются как нули или значение "Недоступно", попробуйте эти методы.
        """)
        
        # Показываем статус API ключа
        if st.session_state.get("youtube_api_key"):
            st.success("✅ YouTube API ключ загружен и готов к использованию")
        else:
            st.error("❌ YouTube API ключ не настроен. Добавьте его в файл .streamlit/secrets.toml для улучшенного поиска каналов")
            with st.expander("Как настроить API ключ"):
                st.markdown("""
                1. Создайте файл `.streamlit/secrets.toml` со следующим содержимым:
                ```toml
                [youtube]
                api_key = "ВАШ_КЛЮЧ_API_YOUTUBE"
                ```
                
                2. Получите API ключ на странице: https://console.cloud.google.com/apis/credentials
                3. Активируйте YouTube Data API v3 в Google Cloud Console
                4. Перезапустите приложение
                """)
    
    # Параметры сбора данных
    with st.expander("Параметры сбора данных", expanded=True):
        col1, col2 = st.columns(2)
        
        with col1:
            source_videos_limit = st.number_input(
                "Количество видео с исходного канала",
                min_value=1,
                max_value=50,
                value=10,
                step=1,
                help="Сколько последних видео брать с каждого канала для анализа"
            )
            
            max_channel_age = st.number_input(
                "Максимальный возраст канала (дней)",
                min_value=0,
                max_value=5000,
                value=0,
                step=100,
                help="0 = без ограничений, любой возраст канала"
            )
            
        with col2:
            recommendation_limit = st.number_input(
                "Количество рекомендаций для каждого видео",
                min_value=5,
                max_value=50,
                value=30,
                step=5,
                help="Сколько рекомендованных видео анализировать для каждого исходного видео"
            )
            
            min_channel_views = st.number_input(
                "Минимальное количество просмотров канала",
                min_value=0,
                max_value=10000000,
                value=50000,
                step=10000,
                help="Минимальное количество просмотров для отображения канала в результатах"
            )
    
    # Параметры авторизации в Google аккаунте
    with st.expander("Авторизация Google (опционально)", expanded=False):
        # Проверяем, есть ли уже существующая авторизация
        is_already_logged_in = st.session_state.get("is_logged_in", False)
        if is_already_logged_in:
            st.success(f"✅ Вы уже авторизованы как {st.session_state.get('google_account', {}).get('email', '')}")
            st.info("Поиск похожих каналов будет выполнен с использованием существующей авторизации.")
            use_google_account = True
            google_account = st.session_state.get("google_account")
        else:
            use_google_account = st.checkbox("Авторизоваться в аккаунте Google", value=False, key="similar_channels_google_auth")
            google_account = None
            
            if use_google_account:
                # Колонки для почты и пароля
                email_col, pass_col = st.columns(2)
                
                with email_col:
                    email = st.text_input("Email Google аккаунта", key="similar_channels_email")
                
                with pass_col:
                    password = st.text_input("Пароль", type="password", key="similar_channels_password")
                
                if email and password:
                    google_account = {
                        "email": email,
                        "password": password
                    }
                else:
                    st.warning("Для авторизации необходимо ввести Email и пароль")
    
    # Список исходных каналов
    st.subheader("Исходные каналы")
    channels_input = st.text_area(
        "Введите URL каналов YouTube (по одному на строку):",
        placeholder="https://www.youtube.com/@ChannelName\nhttps://www.youtube.com/channel/UCXXXXXXXXXXXXXXXXXX",
        height=150
    )
    
    # Кнопка для запуска поиска
    start_search = st.button("Найти похожие каналы", key="start_similar_search")
    
    # Обработка нажатия кнопки
    if start_search and channels_input:
        # Разбиваем текст на строки и фильтруем пустые
        channel_urls = [url.strip() for url in channels_input.strip().split('\n') if url.strip()]
        
        if not channel_urls:
            st.error("Пожалуйста, введите хотя бы один URL канала YouTube.")
            return
        
        # Создаем прогресс-бар и сообщение о статусе
        progress_bar = st.progress(0)
        status_message = st.empty()
        
        # Функция для обновления прогресса и сообщения
        def update_search_progress(progress, message):
            update_progress(progress_bar, status_message, progress, message)
        
        # Инициализируем и получаем существующий экземпляр анализатора, если он уже создан
        existing_analyzer = None
        if st.session_state.get("is_logged_in") and hasattr(st.session_state, "youtube_analyzer"):
            existing_analyzer = st.session_state.get("youtube_analyzer")
            
            # Проверяем, не закрыт ли драйвер
            if existing_analyzer and existing_analyzer.driver:
                try:
                    # Проверим, что драйвер все еще работает
                    existing_analyzer.driver.current_url
                except:
                    # Если возникает ошибка, значит драйвер закрыт
                    existing_analyzer = None
        
        if existing_analyzer:
            update_search_progress(5, "Используем существующую сессию для поиска...")
        else:
            update_search_progress(5, "Инициализация YouTube анализатора...")
        
        # Запускаем поиск с замером времени
        start_time = time.time()
        
        # Необходим try/except, чтобы гарантировать закрытие драйвера
        try:
            # Используем существующий экземпляр или создаем новый
            if existing_analyzer:
                analyzer = existing_analyzer
            else:
                # Создаем анализатор
                analyzer = YouTubeAnalyzer(
                    headless=True, 
                    use_proxy=True, 
                    google_account=google_account
                )
                
                # Если указан аккаунт Google, выполняем вход
                if google_account and use_google_account:
                    update_search_progress(10, "Выполняем вход в Google аккаунт...")
                    login_success = analyzer.login_to_google()
                    if login_success:
                        st.session_state["is_logged_in"] = True
                        st.session_state["google_account"] = google_account
                        st.session_state["youtube_analyzer"] = analyzer
                        update_search_progress(15, "Вход в Google выполнен успешно!")
                    else:
                        update_search_progress(15, "Не удалось войти в Google аккаунт, продолжаем без авторизации...")
            
            # Выполняем поиск похожих каналов
            similar_channels = find_similar_channels(
                analyzer,
                channel_urls,
                source_videos_limit=source_videos_limit,
                recommendation_limit=recommendation_limit,
                min_channel_views=min_channel_views,
                max_channel_age=max_channel_age,
                progress_callback=update_search_progress
            )
            
            # Вычисляем затраченное время
            elapsed_time = time.time() - start_time
            
            # Отображаем результаты
            if similar_channels is not None and not similar_channels.empty:
                status_message.success(f"Поиск завершен за {elapsed_time:.2f} сек! Найдено {len(similar_channels)} похожих каналов.")
                
                # Добавим информацию о параметрах найденных каналов для отладки
                debug_info = st.expander("Информация о параметрах каналов (для отладки)", expanded=False)
                with debug_info:
                    st.info("Эта информация поможет диагностировать проблемы с извлечением данных о каналах")
                    # Создаем отладочную таблицу
                    if 'URL канала' in similar_channels.columns:
                        debug_df = similar_channels[['URL канала', 'Название канала', 'Общее число просмотров', 
                                           'Количество видео', 'Возраст канала (дней)', 
                                           'Количество подписчиков', 'Страна']].copy()
                    else:
                        debug_df = similar_channels[['Ссылка на канал', 'Название канала', 'Общее число просмотров', 
                                           'Количество видео', 'Возраст канала (дней)', 
                                           'Количество подписчиков', 'Страна']].copy()
                    st.dataframe(debug_df, use_container_width=True)
                    
                    # Анализируем данные
                    missing_values = debug_df.iloc[:, 1:].isna().sum()
                    missing_views = (debug_df['Общее число просмотров'] == 0).sum()
                    missing_videos = (debug_df['Количество видео'] == 0).sum()
                    missing_age = (debug_df['Возраст канала (дней)'] == 0).sum()
                    missing_subs = (debug_df['Количество подписчиков'] == '—').sum()
                    
                    st.write(f"**Анализ данных:**")
                    st.write(f"- Каналов с отсутствующими просмотрами: {missing_views} из {len(debug_df)}")
                    st.write(f"- Каналов с отсутствующим количеством видео: {missing_videos} из {len(debug_df)}")
                    st.write(f"- Каналов с отсутствующим возрастом: {missing_age} из {len(debug_df)}")
                    st.write(f"- Каналов с отсутствующим числом подписчиков: {missing_subs} из {len(debug_df)}")
                    
                    if missing_views > 0 or missing_videos > 0 or missing_age > 0 or missing_subs > 0:
                        st.warning("Обнаружены пропущенные данные. YouTube может скрывать некоторую информацию о каналах или изменил формат страницы.")
                
                # Сохраняем результаты в session_state и глобальную переменную
                st.session_state["similar_channels_df"] = similar_channels
                global similar_channels_df
                similar_channels_df = similar_channels
                
                # Отображаем таблицу с результатами
                display_similar_channels_results()
            else:
                status_message.warning("Поиск завершен, но не найдено похожих каналов, соответствующих критериям.")
        
        except Exception as e:
            status_message.error(f"Ошибка при поиске похожих каналов: {str(e)}")
            st.exception(e)
            
            # Закрываем драйвер, если мы его создали и произошла ошибка
            if 'analyzer' in locals() and analyzer and analyzer != existing_analyzer:
                try:
                    analyzer.quit_driver()
                except:
                    pass
        
    elif start_search:
        st.error("Пожалуйста, введите хотя бы один URL канала YouTube.")
    
    # Отображаем сохраненные результаты, если они есть
    if not start_search and "similar_channels_df" in st.session_state and not st.session_state["similar_channels_df"].empty:
        st.success("Показаны предыдущие результаты поиска похожих каналов.")
        display_similar_channels_results()

# Функция для обновления индикатора прогресса
def update_progress(progress_bar, status_message, progress, message):
    """
    Обновляет индикатор прогресса и сообщение о статусе.
    
    Args:
        progress_bar: Индикатор прогресса Streamlit
        status_message: Контейнер для сообщения о статусе
        progress: Значение прогресса (0-100)
        message: Сообщение о статусе
    """
    # Преобразуем диапазон от 0-100 к 0.0-1.0
    normalized_progress = min(progress, 100) / 100.0
    progress_bar.progress(normalized_progress)
    status_message.info(message)

def subscribers_to_int(subscribers_text):
    """
    Преобразует текстовое представление числа подписчиков в целое число для сортировки.
    
    Args:
        subscribers_text (str): Текстовое представление числа подписчиков (например, "1.5M", "500K")
        
    Returns:
        int: Целое число подписчиков
    """
    if not subscribers_text or subscribers_text == "—" or subscribers_text.lower() == "скрыто":
        return 0
    
    try:
        # Удаляем пробелы и запятые
        clean_text = subscribers_text.replace(" ", "").replace(",", "")
        
        # Проверяем на K (тысячи)
        if "K" in clean_text or "тыс" in clean_text:
            value = float(clean_text.replace("K", "").replace("тыс.", "").replace("тыс", ""))
            return int(value * 1000)
        
        # Проверяем на M (миллионы)
        elif "M" in clean_text or "млн" in clean_text:
            value = float(clean_text.replace("M", "").replace("млн.", "").replace("млн", ""))
            return int(value * 1000000)
        
        # Просто число
        else:
            return int(clean_text)
    except:
        return 0

def display_similar_channels_results():
    """
    Отображает результаты поиска похожих каналов.
    
    Использует глобальный DataFrame similar_channels_df
    """
    global similar_channels_df
    
    if similar_channels_df is None or similar_channels_df.empty:
        st.warning("🔍 Результаты не найдены. Пожалуйста, выполните поиск похожих каналов.")
        return
    
    # Добавляем счетчик каналов и информацию о соответствии критериям
    not_matching_count = 0
    matching_count = 0
    
    if "Соответствует критериям" in similar_channels_df.columns:
        not_matching_count = sum(similar_channels_df["Соответствует критериям"] == "Нет")
        matching_count = sum(similar_channels_df["Соответствует критериям"] == "Да")
    
    total_count = len(similar_channels_df)
    
    # Показываем статистику
    if matching_count > 0 and not_matching_count > 0:
        st.success(f"🎯 Найдено {total_count} каналов: {matching_count} соответствуют критериям, {not_matching_count} не соответствуют.")
    elif matching_count > 0:
        st.success(f"🎯 Найдено {matching_count} каналов, соответствующих критериям.")
    elif not_matching_count > 0:
        st.warning(f"🔍 Найдено {not_matching_count} каналов, но ни один не соответствует критериям фильтрации.")
    else:
        st.success(f"🎯 Найдено {total_count} каналов.")
    
    # Добавляем фильтры
    with st.expander("Фильтры и поиск", expanded=True):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            # Добавляем фильтр по соответствию критериям, если есть такая колонка
            if "Соответствует критериям" in similar_channels_df.columns and not_matching_count > 0 and matching_count > 0:
                criteria_filter = st.radio(
                    "Показать каналы:",
                    options=["Все", "Соответствующие критериям", "Не соответствующие критериям"],
                    index=0
                )
                
                filtered_df = similar_channels_df
                if criteria_filter == "Соответствующие критериям":
                    filtered_df = similar_channels_df[similar_channels_df["Соответствует критериям"] == "Да"]
                elif criteria_filter == "Не соответствующие критериям":
                    filtered_df = similar_channels_df[similar_channels_df["Соответствует критериям"] == "Нет"]
            else:
                filtered_df = similar_channels_df
        
        with col2:
            # Фильтр по минимальному количеству просмотров
            if "Общее число просмотров" in filtered_df.columns:
                min_views = st.number_input(
                    "Минимальное количество просмотров:",
                    min_value=0,
                    max_value=int(filtered_df["Общее число просмотров"].max() if len(filtered_df) > 0 else 1000000),
                    value=0,
                    step=10000
                )
                
                if min_views > 0:
                    filtered_df = filtered_df[filtered_df["Общее число просмотров"] >= min_views]
        
        with col3:
            # Поиск по названию канала
            search_query = st.text_input("Поиск по названию канала:", "")
            
            if search_query:
                filtered_df = filter_by_search(filtered_df, search_query)
    
    # Отображаем таблицу с результатами
    if filtered_df.empty:
        st.warning("⚠️ Нет каналов, удовлетворяющих заданным фильтрам.")
        return
    
    # Определяем колонки для отображения
    display_columns = []
    
    if "Ссылка на канал" in filtered_df.columns:
        display_columns.append("Ссылка на канал")
    
    if "Название канала" in filtered_df.columns:
        display_columns.append("Название канала")
    
    if "Количество подписчиков" in filtered_df.columns:
        display_columns.append("Количество подписчиков")
    
    if "Количество видео" in filtered_df.columns:
        display_columns.append("Количество видео")
    
    if "Общее число просмотров" in filtered_df.columns:
        display_columns.append("Общее число просмотров")
    
    if "Возраст канала (дней)" in filtered_df.columns:
        display_columns.append("Возраст канала (дней)")
    
    if "Страна" in filtered_df.columns:
        display_columns.append("Страна")
    
    if "Соответствует критериям" in filtered_df.columns:
        display_columns.append("Соответствует критериям")
    
    # Выбираем только нужные колонки
    filtered_df = filtered_df[display_columns]
    
    # Добавляем ссылки на каналы
    def make_clickable(url, text=None):
        text = text or url
        return f'<a href="{url}" target="_blank">{text}</a>'
    
    if "Ссылка на канал" in filtered_df.columns and "Название канала" in filtered_df.columns:
        filtered_df["Название канала"] = filtered_df.apply(
            lambda row: make_clickable(row["Ссылка на канал"], row["Название канала"]),
            axis=1
        )
    
    # Удаляем колонку со ссылкой, так как мы добавили ее в название
    if "Ссылка на канал" in filtered_df.columns:
        filtered_df = filtered_df.drop(columns=["Ссылка на канал"])
    
    # Форматируем числовые колонки
    for col in filtered_df.columns:
        if col in ["Общее число просмотров", "Количество подписчиков", "Количество видео"]:
            filtered_df[col] = filtered_df[col].apply(lambda x: f"{x:,}".replace(",", " ") if isinstance(x, (int, float)) else x)
    
    # Добавляем стилизацию для строк с разными значениями в колонке "Соответствует критериям"
    def highlight_criteria(row):
        if "Соответствует критериям" not in row.index:
            return [""] * len(row)
        
        if row["Соответствует критериям"] == "Нет":
            return ["background-color: #ffe6e6"] * len(row)
        else:
            return ["background-color: #e6ffe6"] * len(row)
    
    # Применяем стилизацию и отображаем таблицу с HTML
    styled_df = filtered_df.style.apply(highlight_criteria, axis=1)
    
    # Преобразуем таблицу в HTML и отображаем её
    st.write(styled_df.to_html(escape=False), unsafe_allow_html=True)
    
    # Добавляем статистику по найденным каналам
    with st.expander("Статистика по найденным каналам", expanded=False):
        if "Общее число просмотров" in filtered_df.columns:
            total_views = filtered_df["Общее число просмотров"].sum()
            avg_views = filtered_df["Общее число просмотров"].mean()
            
            st.metric("Общее количество просмотров", f"{total_views:,}".replace(",", " "))
            st.metric("Среднее количество просмотров", f"{int(avg_views):,}".replace(",", " "))
        
        if "Количество подписчиков" in filtered_df.columns:
            # Преобразуем числа подписчиков в целочисленные значения
            subscribers = filtered_df["Количество подписчиков"].apply(subscribers_to_int)
            if subscribers.notna().any():
                avg_subscribers = subscribers[subscribers.notna()].mean()
                st.metric("Среднее количество подписчиков", f"{int(avg_subscribers):,}".replace(",", " "))
        
        if "Возраст канала (дней)" in filtered_df.columns:
            avg_age = filtered_df["Возраст канала (дней)"].mean()
            st.metric("Средний возраст канала", f"{int(avg_age)} дней")
            
    # Добавляем кнопку для скачивания результатов
    if len(filtered_df) > 0:
        # Восстанавливаем колонку "Ссылка на канал" для CSV
        if "Ссылка на канал" not in filtered_df.columns and "Ссылка на канал" in similar_channels_df.columns:
            filtered_df["Ссылка на канал"] = similar_channels_df.loc[filtered_df.index, "Ссылка на канал"]
        
        # Преобразуем DataFrame в CSV
        csv = filtered_df.to_csv(index=False).encode('utf-8')
        
        st.download_button(
            label="Скачать результаты как CSV",
            data=csv,
            file_name="youtube_similar_channels.csv",
            mime="text/csv",
        )

# Функция для поиска похожих каналов
def find_similar_channels(analyzer, channel_urls, source_videos_limit=30, recommendation_limit=30, 
                           min_channel_views=50000, max_channel_age=0, progress_callback=None):
    """
    Находит похожие каналы на основе предоставленных ссылок на каналы/видео.
    
    Args:
        analyzer (YouTubeAnalyzer): Экземпляр класса YouTubeAnalyzer для доступа к YouTube
        channel_urls (list): Список URL каналов или видео YouTube
        source_videos_limit (int): Максимальное количество исходных видео для анализа
        recommendation_limit (int): Максимальное количество рекомендуемых видео для каждого исходного видео
        min_channel_views (int): Минимальное количество просмотров канала для включения в результаты
        max_channel_age (int): Максимальный возраст канала в днях (0 - без ограничений)
        progress_callback (callable): Функция обратного вызова для обновления прогресса
        
    Returns:
        pd.DataFrame: DataFrame с информацией о похожих каналах
    """
    if not channel_urls or len(channel_urls) == 0:
        return pd.DataFrame()
    
    # Обновляем прогресс, если нужно
    if progress_callback:
        progress_callback(5, "Инициализация поиска похожих каналов...")
    
    # Словарь для хранения информации о каналах
    channels_info = {}
    
    # Счетчик для отслеживания доступа к каналам
    inaccessible_channels_count = 0
    total_channels_processed = 0
    
    try:
        # Шаг 1: Обрабатываем источники (каналы или видео)
        if progress_callback:
            progress_callback(10, "Обработка исходных URL...")
        
        source_channel_urls = []
        source_channel_ids = []
        
        for url in channel_urls:
            if not url.strip():
                continue
                
            # Очищаем URL
            url = clean_youtube_url(url)
            
            # Проверяем, видео это или канал
            if "/watch?v=" in url or "youtu.be/" in url:
                # Это видео - получаем канал через API
                video_details = get_video_details_fast(url)
                
                if video_details and video_details.get("channel_url"):
                    channel_url = video_details.get("channel_url")
                    source_channel_urls.append(channel_url)
                else:
                    logger.warning(f"Не удалось получить канал из видео: {url}")
            else:
                # Это URL канала
                source_channel_urls.append(url)
                
                # Извлекаем ID канала из URL
                channel_id = None
                if "/channel/" in url:
                    channel_id = url.split("/channel/")[1].split("/")[0]
                    source_channel_ids.append(channel_id)
        
        if len(source_channel_urls) == 0:
            if progress_callback:
                progress_callback(100, "Не удалось обработать исходные URL.")
            return pd.DataFrame()
            
        # Проверяем наличие API ключа для использования YouTube Data API
        use_api = False
        if hasattr(st.session_state, 'youtube_api_key') and st.session_state.youtube_api_key:
            use_api = True
            api_key = st.session_state.youtube_api_key
            
            # Если у нас есть хотя бы один ID канала и API ключ, используем API для поиска похожих каналов
            if source_channel_ids and use_api:
                if progress_callback:
                    progress_callback(15, f"Поиск похожих каналов через YouTube API...")
                
                api_found_channels = []
                total_channels = len(source_channel_ids)
                
                for idx, channel_id in enumerate(source_channel_ids):
                    if progress_callback:
                        progress_callback(15 + (65 * idx // total_channels), 
                                         f"API поиск для канала {idx+1}/{total_channels}...")
                    
                    # Используем API метод для поиска похожих каналов
                    similar_channels = analyzer.find_similar_channels_api(channel_id, api_key, 
                                                                         max_results=recommendation_limit*2)
                    
                    if similar_channels:
                        api_found_channels.extend(similar_channels)
                        
                        if progress_callback:
                            progress_callback(15 + (65 * (idx+1) // total_channels), 
                                             f"Найдено {len(similar_channels)} каналов через API для канала {idx+1}")
                
                # Если мы нашли каналы через API, преобразуем их в нужный формат и возвращаем результат
                if api_found_channels:
                    if progress_callback:
                        progress_callback(85, f"Обработка {len(api_found_channels)} найденных через API каналов...")
                    
                    # Преобразуем в DataFrame
                    channels_df = pd.DataFrame([
                        {
                            "Ссылка на канал": channel.get("url"),
                            "Название канала": channel.get("title"),
                            "Описание": channel.get("description"),
                            "Количество подписчиков": channel.get("subscriber_count"),
                            "Количество видео": channel.get("video_count"),
                            "Общее число просмотров": channel.get("view_count"),
                            "Возраст канала (дней)": channel.get("channel_age_days"),
                            "Страна": channel.get("country"),
                            "Миниатюра": channel.get("thumbnail")
                        }
                        for channel in api_found_channels
                    ])
                    
                    # Удаляем дубликаты
                    channels_df = channels_df.drop_duplicates(subset=["Ссылка на канал"])
                    
                    # Сохраняем копию всех каналов до фильтрации
                    all_channels_df = channels_df.copy()
                    
                    # Применяем фильтры
                    if min_channel_views > 0:
                        channels_df = filter_by_views(channels_df, min_channel_views)
                    
                    if max_channel_age > 0:
                        channels_df = filter_by_date(channels_df, max_channel_age)
                    
                    # Сортируем по просмотрам
                    if "Общее число просмотров" in channels_df.columns:
                        channels_df = channels_df.sort_values(by="Общее число просмотров", ascending=False)
                    
                    if len(channels_df) == 0:
                        if progress_callback:
                            progress_callback(100, f"Поиск завершен, но ни один канал не соответствует критериям. Показываем все найденные каналы.")
                        # Возвращаем все каналы, но добавляем колонку с пометкой, что они не соответствуют критериям
                        all_channels_df["Соответствует критериям"] = "Нет"
                        # Сортируем по просмотрам
                        if "Общее число просмотров" in all_channels_df.columns:
                            all_channels_df = all_channels_df.sort_values(by="Общее число просмотров", ascending=False)
                        return all_channels_df
                    else:
                        if progress_callback:
                            progress_callback(100, f"Поиск завершен. Найдено {len(channels_df)} похожих каналов.")
                        # Добавляем колонку с отметкой, что каналы соответствуют критериям
                        channels_df["Соответствует критериям"] = "Да"
                        return channels_df
            
        # Если API не доступен или не нашел результатов, используем стандартный поиск через Selenium

        # Шаг 2: Получаем видео с каждого исходного канала
        if progress_callback:
            progress_callback(20, f"Получение видео с {len(source_channel_urls)} исходных каналов...")
        
        all_source_videos = []
        
        for source_channel in source_channel_urls:
            try:
                # Используем быстрый метод без Selenium
                # Извлекаем ID канала из URL
                channel_id = None
                if "/channel/" in source_channel:
                    channel_id = source_channel.split("/channel/")[1].split("/")[0]
                
                # Если есть ID, используем API
                if channel_id and hasattr(st.session_state, 'youtube_api_key') and st.session_state.youtube_api_key:
                    # Получаем через API
                    api_key = st.session_state.youtube_api_key
                    videos = analyzer._get_channel_videos_api(channel_id, limit=source_videos_limit)
                    if videos:
                        all_source_videos.extend(videos)
                        logger.info(f"Получено {len(videos)} видео с канала {source_channel} через API")
                    else:
                        # Если API не сработал, пробуем через Selenium
                        videos = analyzer.get_last_videos_from_channel(source_channel, limit=source_videos_limit)
                        if videos:
                            all_source_videos.extend(videos)
                            logger.info(f"Получено {len(videos)} видео с канала {source_channel} через Selenium")
                else:
                    # Используем Selenium
                    videos = analyzer.get_last_videos_from_channel(source_channel, limit=source_videos_limit)
                    if videos:
                        all_source_videos.extend(videos)
                        logger.info(f"Получено {len(videos)} видео с канала {source_channel} через Selenium")
            except Exception as e:
                logger.error(f"Ошибка при получении видео с канала {source_channel}: {str(e)}")
        
        if len(all_source_videos) == 0:
            if progress_callback:
                progress_callback(100, "Не удалось получить видео с исходных каналов.")
            return pd.DataFrame()
        
        # Ограничиваем количество исходных видео
        if len(all_source_videos) > source_videos_limit:
            all_source_videos = all_source_videos[:source_videos_limit]
        
        # Шаг 3: Получаем рекомендации для каждого исходного видео
        if progress_callback:
            progress_callback(30, f"Получение рекомендаций для {len(all_source_videos)} видео...")
        
        unique_channels = set()
        
        progress_per_video = 50 / max(1, len(all_source_videos))
        for idx, video in enumerate(all_source_videos):
            try:
                # Получаем рекомендации для видео
                recommended_videos = analyzer.get_recommended_videos_fast(video['url'], limit=recommendation_limit)
                
                if not recommended_videos:
                    continue
                
                # Извлекаем уникальные каналы из рекомендаций
                for rec_video in recommended_videos:
                    channel_url = rec_video.get('channel_url')
                    
                    if not channel_url or channel_url in unique_channels:
                        continue
                    
                    unique_channels.add(channel_url)
                
                # Обновляем прогресс
                if progress_callback:
                    current_progress = 30 + progress_per_video * (idx + 1)
                    progress_callback(min(80, current_progress), f"Обработано {idx+1}/{len(all_source_videos)} видео, найдено {len(unique_channels)} уникальных каналов...")
            
            except Exception as e:
                logger.error(f"Ошибка при получении рекомендаций для видео {video.get('url', 'Unknown')}: {str(e)}")
        
        # Если нет уникальных каналов, возвращаем пустой DataFrame
        if len(unique_channels) == 0:
            if progress_callback:
                progress_callback(100, "Не найдено уникальных каналов в рекомендациях.")
            return pd.DataFrame()
        
        # Шаг 4: Получаем информацию о каждом уникальном канале
        if progress_callback:
            progress_callback(80, f"Получение информации о {len(unique_channels)} каналах...")
        
        # Создаем список для хранения данных каналов
        channels_data = []
        
        # Если мы дошли сюда - значит нашли что-то, отмечаем флаг
        found_any = len(unique_channels) > 0
        
        # Получаем информацию о каждом уникальном канале
        progress_per_channel = 20 / max(1, len(unique_channels))
        
        for idx, channel_url in enumerate(unique_channels):
            try:
                # Пропускаем пустые URL
                if not channel_url:
                    continue
                
                # Если это новый канал - получаем информацию о нем
                if channel_url not in channels_info:
                    # Получаем информацию о канале быстрым методом
                    channel_info_data = get_channel_info_fast(channel_url)
                    
                    # Увеличиваем счетчик обработанных каналов
                    total_channels_processed += 1
                    
                    # Проверяем доступность данных канала
                    if not channel_info_data:
                        logger.warning(f"Не удалось получить информацию о канале {channel_url}")
                        inaccessible_channels_count += 1
                        continue
                    
                    # Проверяем, не является ли это ошибкой доступа
                    if channel_info_data.get("Название канала", "").startswith("⚠️"):
                        logger.warning(f"Канал недоступен: {channel_url} - {channel_info_data.get('Название канала')}")
                        inaccessible_channels_count += 1
                        continue
                    
                    # Отладочная информация о полученных данных канала
                    logger.info(f"Получена информация о канале: {channel_url}")
                    logger.info(f"  - Название канала: {channel_info_data.get('Название канала', 'Неизвестно')}")
                    logger.info(f"  - Количество видео: {channel_info_data.get('Количество видео', 0)}")
                    logger.info(f"  - Общее число просмотров: {channel_info_data.get('Общее число просмотров', 0)}")
                    logger.info(f"  - Возраст канала (дней): {channel_info_data.get('Возраст канала (дней)', 0)}")
                    logger.info(f"  - Количество подписчиков: {channel_info_data.get('Количество подписчиков', '-')}")
                    logger.info(f"  - Страна: {channel_info_data.get('Страна', 'Неизвестно')}")
                    
                    # Подготавливаем информацию о канале
                    channel_info = {
                        "Ссылка на канал": channel_url,
                        "Название канала": channel_info_data.get("Название канала", "Неизвестно"),
                        "Общее число просмотров": channel_info_data.get("Общее число просмотров", 0),
                        "Количество видео": channel_info_data.get("Количество видео", 0),
                        "Возраст канала (дней)": channel_info_data.get("Возраст канала (дней)", 0),
                        "Дата создания": channel_info_data.get("Дата создания", "Неизвестно"),
                        "Количество подписчиков": channel_info_data.get("Количество подписчиков", "—"),
                        "Страна": channel_info_data.get("Страна", "Неизвестно")
                    }
                    
                    # Сохраняем информацию о канале
                    channels_info[channel_url] = channel_info
                
                # Получаем информацию о канале из словаря
                channel_info = channels_info[channel_url]
                
                # Добавляем информацию о канале в список
                channels_data.append(channel_info)
                
                # Обновляем прогресс
                if progress_callback:
                    current_progress = 80 + progress_per_channel * (idx + 1)
                    progress_callback(min(95, current_progress), f"Обработано {idx+1}/{len(unique_channels)} каналов...")
            
            except Exception as e:
                logger.error(f"Ошибка при получении информации о канале {channel_url}: {str(e)}")
        
        # Проверяем, не слишком ли много недоступных каналов
        if total_channels_processed > 0 and inaccessible_channels_count / total_channels_processed > 0.5:
            logger.warning(f"Высокий процент недоступных каналов: {inaccessible_channels_count}/{total_channels_processed}")
            if progress_callback:
                progress_callback(95, f"Предупреждение: {inaccessible_channels_count} из {total_channels_processed} каналов недоступны. Возможно, YouTube блокирует запросы.")
        
        # Если нет данных о каналах, возвращаем пустой DataFrame
        if len(channels_data) == 0:
            if progress_callback:
                progress_callback(100, "Не удалось получить информацию о каналах.")
            return pd.DataFrame()
        
        # Шаг 5: Создаем DataFrame и применяем фильтры
        unfiltered_channels_df = pd.DataFrame(channels_data)
        
        # Копируем исходный DataFrame для фильтрации
        channels_df = unfiltered_channels_df.copy()
        
        # Преобразуем строковые колонки с числами в числовые значения
        if "Общее число просмотров" in channels_df.columns:
            channels_df["Общее число просмотров"] = pd.to_numeric(channels_df["Общее число просмотров"], errors="coerce").fillna(0)
        
        if "Количество видео" in channels_df.columns:
            channels_df["Количество видео"] = pd.to_numeric(channels_df["Количество видео"], errors="coerce").fillna(0)
        
        if "Возраст канала (дней)" in channels_df.columns:
            channels_df["Возраст канала (дней)"] = pd.to_numeric(channels_df["Возраст канала (дней)"], errors="coerce").fillna(0)
        
        # Логируем количество каналов до фильтрации
        logger.info(f"Найдено {len(channels_df)} каналов до фильтрации")
        
        # Отфильтровываем каналы по минимальному количеству просмотров
        if min_channel_views > 0:
            logger.info(f"Применяем фильтр по минимальному числу просмотров: {min_channel_views}")
            channels_df = channels_df[channels_df["Общее число просмотров"] >= min_channel_views]
            logger.info(f"После фильтрации по просмотрам осталось {len(channels_df)} каналов")
        
        # Отфильтровываем каналы по максимальному возрасту
        if max_channel_age > 0:
            logger.info(f"Применяем фильтр по максимальному возрасту канала: {max_channel_age} дней")
            channels_df = channels_df[channels_df["Возраст канала (дней)"] <= max_channel_age]
            logger.info(f"После фильтрации по возрасту осталось {len(channels_df)} каналов")
        
        # Если после фильтрации не осталось каналов, но были найдены каналы до фильтрации,
        # возвращаем все найденные каналы
        if channels_df.empty and found_any:
            logger.warning("После фильтрации не осталось каналов. Возвращаем все найденные каналы без фильтрации.")
            channels_df = unfiltered_channels_df
            # Добавляем флаг, что каналы не соответствуют критериям
            channels_df["Соответствует критериям"] = "Нет"
            
            # Сортируем по просмотрам для улучшения отображения
            if "Общее число просмотров" in channels_df.columns:
                channels_df = channels_df.sort_values(by="Общее число просмотров", ascending=False)
                
            if progress_callback:
                progress_callback(100, f"Поиск завершен. Найдено {len(channels_df)} похожих каналов, но ни один не соответствует заданным критериям. Показываем все найденные каналы.")
        elif not channels_df.empty:
            # Если есть каналы после фильтрации, добавляем флаг
            channels_df["Соответствует критериям"] = "Да"
            
            # Сортируем по просмотрам для улучшения отображения
            if "Общее число просмотров" in channels_df.columns:
                channels_df = channels_df.sort_values(by="Общее число просмотров", ascending=False)
                
            if progress_callback:
                progress_callback(100, f"Поиск завершен. Найдено {len(channels_df)} похожих каналов.")
        else:
            # Если вообще не найдено каналов
            if progress_callback:
                progress_callback(100, f"Поиск завершен, но не найдено похожих каналов.")
        
        return channels_df
    
    except Exception as e:
        logger.error(f"Критическая ошибка при поиске похожих каналов: {str(e)}")
        if progress_callback:
            progress_callback(100, f"Ошибка при поиске похожих каналов: {str(e)}")
        return pd.DataFrame()

def get_channel_info_fast(channel_url):
    """
    Быстрое получение информации о канале без использования Selenium.
    
    Args:
        channel_url (str): URL канала YouTube
        
    Returns:
        dict: Словарь с информацией о канале или None в случае ошибки
    """
    # Проверяем кэш
    if channel_url in channel_info_cache:
        return channel_info_cache[channel_url]
    
    try:
        # Нормализуем URL канала
        if not (channel_url.startswith("http://") or channel_url.startswith("https://")):
            channel_url = f"https://www.youtube.com{channel_url}"
        
        # Убедимся, что мы используем основной URL канала, а не вкладку (например, /videos)
        channel_base_url = channel_url
        for tab in ["/videos", "/playlists", "/community", "/channels", "/about"]:
            if tab in channel_base_url:
                channel_base_url = channel_base_url.split(tab)[0]
                break
        
        # Пробуем использовать прокси, если настроены
        proxies = None
        try:
            all_proxies = check_proxies()
            if all_proxies and len(all_proxies) > 0:
                proxy = random.choice(all_proxies)
                proxies = {
                    "http": proxy["http"],
                    "https": proxy["https"]
                }
                logger.info(f"Используем прокси {proxy['server']} для запроса к каналу")
        except Exception as e:
            logger.warning(f"Не удалось получить прокси: {str(e)}")
        
        # Делаем запрос к странице "about" канала, где есть больше информации
        about_url = f"{channel_base_url}/about" if not channel_base_url.endswith("/") else f"{channel_base_url}about"
        
        logger.info(f"Запрашиваем информацию о канале: {about_url}")
        
        # Настраиваем заголовки для обхода страницы согласия
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cookie": "CONSENT=YES+cb.20210418-17-p0.en+FX+116; SOCS=CAESEwgDEgk1MjY5MzQ5MjcaAmVuIAEaBgiA_LyaBg"
        }
        
        # Пробуем с прокси, если доступен
        try:
            if proxies:
                response = requests.get(about_url, headers=headers, proxies=proxies, timeout=15)
            else:
                response = requests.get(about_url, headers=headers, timeout=15)
        except Exception as e:
            logger.error(f"Ошибка при запросе к {about_url}: {str(e)}")
            # Пробуем без прокси, если была ошибка с прокси
            if proxies:
                try:
                    logger.info("Пробуем запрос без прокси после ошибки")
                    response = requests.get(about_url, headers=headers, timeout=15)
                except Exception as e2:
                    logger.error(f"Повторная ошибка без прокси: {str(e2)}")
                    # Возвращаем базовую информацию в случае ошибки
                    default_info = {
                        "Ссылка на канал": channel_url,
                        "Название канала": "⚠️ Ошибка доступа",
                        "Общее число просмотров": 0,
                        "Количество видео": 0,
                        "Возраст канала (дней)": 0,
                        "Дата создания": "Неизвестно",
                        "Количество подписчиков": "—",
                        "Страна": "Неизвестно"
                    }
                    channel_info_cache[channel_url] = default_info
                    return default_info
        
        if response.status_code == 200:
            html = response.text
            
            # Проверяем, не вернулась ли страница согласия/предупреждения вместо контента канала
            if "Прежде чем перейти к YouTube" in html or "consent.youtube.com" in html or "consent.google.com" in html:
                logger.error(f"Получена страница согласия/предупреждения вместо страницы канала: {about_url}")
                
                # Сохраняем HTML страницы для диагностики (только в режиме отладки)
                debug_dir = "debug_data"
                os.makedirs(debug_dir, exist_ok=True)
                channel_id = channel_url.split("/")[-1]
                file_path = os.path.join(debug_dir, f"channel_{channel_id}_consent_page.html")
                try:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(html)
                    logger.info(f"Сохранена HTML-страница согласия для отладки: {file_path}")
                except Exception as e:
                    logger.error(f"Не удалось сохранить HTML-страницу для отладки: {str(e)}")
                
                # Возвращаем базовую структуру с предупреждением
                default_info = {
                    "Ссылка на канал": channel_url,
                    "Название канала": "⚠️ YouTube блокирует доступ",
                    "Общее число просмотров": 0,
                    "Количество видео": 0,
                    "Возраст канала (дней)": 0,
                    "Дата создания": "Неизвестно",
                    "Количество подписчиков": "—",
                    "Страна": "Неизвестно"
                }
                
                # Сохраняем в кэш для предотвращения повторных запросов
                channel_info_cache[channel_url] = default_info
                return default_info
            
            # 1. Извлекаем название канала
            channel_name = None
            name_patterns = [
                r'<meta property="og:title" content="([^"]+)"',
                r'<meta name="title" content="([^"]+)"',
                r'"name":"([^"]+)"',
                r'<title>([^<]+)</title>',
                r'<link itemprop="name" content="([^"]+)">'
            ]
            
            for pattern in name_patterns:
                match = re.search(pattern, html)
                if match:
                    channel_name = match.group(1)
                    # Убираем " - YouTube" из названия
                    if " - YouTube" in channel_name:
                        channel_name = channel_name.replace(" - YouTube", "")
                    break
            
            # 2. Извлекаем информацию из метаданных канала
            
            # Сначала попробуем извлечь данные из JSON, которые обычно более точные
            channel_json_data = None
            initial_data_match = re.search(r'var ytInitialData = (.+?);</script>', html)
            if initial_data_match:
                try:
                    channel_json_data = json.loads(initial_data_match.group(1))
                except:
                    logger.warning(f"Не удалось разобрать JSON данные канала: {about_url}")
            
            # 2.1 Извлекаем общее число просмотров
            total_views = 0
            
            # Метод 1: Из JSON данных
            if channel_json_data:
                try:
                    # Пытаемся найти блок с количеством просмотров
                    header_renderer = channel_json_data.get('header', {}).get('c4TabbedHeaderRenderer', {})
                    if not header_renderer:
                        # Альтернативный путь для новой структуры данных
                        header_renderer = channel_json_data.get('metadata', {}).get('channelMetadataRenderer', {})
                    
                    if header_renderer:
                        # Проверяем разные варианты пути к данным о просмотрах
                        if 'viewCountText' in header_renderer:
                            views_text = header_renderer.get('viewCountText', {}).get('simpleText', '0')
                            views_digits = re.findall(r'\d+', views_text.replace(',', '').replace(' ', ''))
                            if views_digits:
                                total_views = int(''.join(views_digits))
                                # Отладочная информация
                                logger.info(f"Найдено количество просмотров в JSON данных: {total_views} из текста: '{views_text}'")
                        
                        # Запасной вариант - поиск просмотров в общих метаданных
                        if total_views == 0:
                            metadata_renderer = channel_json_data.get('metadata', {}).get('channelMetadataRenderer', {})
                            if metadata_renderer:
                                view_count_str = metadata_renderer.get('viewCountText', '')
                                if view_count_str:
                                    views_digits = re.findall(r'\d+', view_count_str.replace(',', '').replace(' ', ''))
                                    if views_digits:
                                        total_views = int(''.join(views_digits))
                                        logger.info(f"Найдено количество просмотров в metadata: {total_views}")
                except Exception as e:
                    logger.error(f"Ошибка при извлечении просмотров из JSON: {str(e)}")
            
            # Метод 2: Из HTML с помощью регулярных выражений
            if total_views == 0:
                try:
                    # Сохраняем найденные совпадения для отладки
                    views_debug = []
                    
                    views_patterns = [
                        r'"viewCountText":\s*{\s*"simpleText":\s*"([^"]+)"',
                        r'([0-9,\s]+) просмотров',
                        r'([0-9,\s]+) views',
                        r'"viewCount":\s*"([0-9]+)"',
                        r'<meta itemprop="interactionCount" content="([0-9]+)"'
                    ]
                    
                    for pattern in views_patterns:
                        matches = re.findall(pattern, html)
                        if matches:
                            views_debug.append(f"Pattern '{pattern}' found: {matches}")
                            for match in matches:
                                try:
                                    views_digits = re.findall(r'\d+', match.replace(',', '').replace(' ', ''))
                                    if views_digits:
                                        total_views = int(''.join(views_digits))
                                        logger.info(f"Найдено количество просмотров через regex: {total_views} из '{match}'")
                                        break
                                except Exception as e:
                                    logger.error(f"Ошибка при обработке match '{match}': {str(e)}")
                        
                        if total_views > 0:
                            break
                    
                    # Если не нашли просмотры, записываем все совпадения для отладки
                    if total_views == 0 and views_debug:
                        logger.warning(f"Не удалось извлечь количество просмотров, хотя найдены совпадения: {views_debug}")
                except Exception as e:
                    logger.error(f"Ошибка при поиске просмотров через regex: {str(e)}")
                
            # Добавляем отладочную информацию
            if total_views == 0:
                logger.warning(f"Не удалось извлечь количество просмотров для канала {channel_url}")
                
            # 2.2 Извлекаем количество видео
            video_count = 0
            
            # Метод 1: Из JSON данных
            if channel_json_data:
                try:
                    # Проверяем разные пути к данным о количестве видео
                    header_renderer = channel_json_data.get('header', {}).get('c4TabbedHeaderRenderer', {})
                    if header_renderer:
                        if 'videoCountText' in header_renderer:
                            videos_text = header_renderer.get('videoCountText', {}).get('runs', [{}])[0].get('text', '0')
                            videos_digits = re.findall(r'\d+', videos_text.replace(',', '').replace(' ', ''))
                            if videos_digits:
                                video_count = int(''.join(videos_digits))
                except:
                    pass
            
            # Метод 2: Из HTML с помощью регулярных выражений
            if not video_count:
                videos_patterns = [
                    r'"videoCountText":\s*{\s*"runs":\s*\[\s*{\s*"text":\s*"([^"]+)"',
                    r'([0-9,\s]+) videos',
                    r'([0-9,\s]+) видео',
                    r'"videoCount":\s*([0-9]+)'
                ]
                
                for pattern in videos_patterns:
                    match = re.search(pattern, html)
                    if match:
                        videos_text = match.group(1)
                        try:
                            videos_digits = re.findall(r'\d+', videos_text.replace(',', '').replace(' ', ''))
                            if videos_digits:
                                video_count = int(''.join(videos_digits))
                                break
                        except:
                            continue
            
            # 2.3 Извлекаем дату создания канала
            channel_created = None
            
            # Метод 1: Из JSON данных
            if channel_json_data:
                try:
                    # Проверяем разные пути к данным о дате регистрации
                    about_tab = None
                    for tab in channel_json_data.get('contents', {}).get('twoColumnBrowseResultsRenderer', {}).get('tabs', []):
                        if tab.get('tabRenderer', {}).get('title') == 'About':
                            about_tab = tab
                            break
                    
                    if about_tab:
                        join_date_text = None
                        # Ищем блок с информацией о регистрации
                        content_blocks = about_tab.get('tabRenderer', {}).get('content', {}).get('sectionListRenderer', {}).get('contents', [])
                        for block in content_blocks:
                            items = block.get('itemSectionRenderer', {}).get('contents', [])
                            for item in items:
                                metadata = item.get('channelAboutFullMetadataRenderer', {})
                                if metadata and 'joinedDateText' in metadata:
                                    join_date_text = metadata.get('joinedDateText', {}).get('runs', [{}])[0].get('text', '')
                        
                        if join_date_text:
                            # Преобразуем текст даты в формат datetime
                            # Пример: "Joined Dec 15, 2015"
                            join_date_match = re.search(r'([A-Za-z]+\s+\d+,\s+\d{4})', join_date_text)
                            if join_date_match:
                                try:
                                    date_text = join_date_match.group(1)
                                    channel_created = datetime.strptime(date_text, "%b %d, %Y")
                                except:
                                    try:
                                        channel_created = datetime.strptime(date_text, "%B %d, %Y")
                                    except:
                                        pass
                except:
                    pass
            
            # Метод 2: Из HTML с помощью регулярных выражений
            if not channel_created:
                date_patterns = [
                    r'"joinedDateText":\s*{\s*"runs":\s*\[\s*{\s*"text":\s*"[^"]*([0-9]{1,2}\s+[а-яА-Я]+\s+[0-9]{4})',
                    r'Joined\s+([A-Za-z]+\s+[0-9]{1,2},\s+[0-9]{4})',
                    r'"joinedDateText":\s*{\s*"simpleText":\s*"Joined\s+([^"]+)"',
                    r'Дата регистрации:\s+([0-9]{1,2}\s+[а-яА-Я]+\s+[0-9]{4})'
                ]
                
                for pattern in date_patterns:
                    match = re.search(pattern, html)
                    if match:
                        date_text = match.group(1)
                        try:
                            # Попытка преобразовать русскую дату
                            if re.search(r'[а-яА-Я]', date_text):
                                ru_month_to_number = {
                                    'янв': 1, 'фев': 2, 'мар': 3, 'апр': 4, 'май': 5, 'июн': 6,
                                    'июл': 7, 'авг': 8, 'сен': 9, 'окт': 10, 'ноя': 11, 'дек': 12
                                }
                                
                                date_parts = date_text.split()
                                day = int(date_parts[0])
                                month_text = date_parts[1].lower()[:3]  # Берем первые 3 буквы
                                month = ru_month_to_number.get(month_text, 1)  # По умолчанию январь
                                year = int(date_parts[2])
                                
                                channel_created = datetime(year, month, day)
                            else:
                                # Попытка преобразовать английскую дату
                                try:
                                    channel_created = datetime.strptime(date_text, "%b %d, %Y")
                                except:
                                    try:
                                        channel_created = datetime.strptime(date_text, "%B %d, %Y")
                                    except:
                                        pass
                            break
                        except:
                            continue
            
            # Вычисляем возраст канала в днях
            channel_age = 0
            if channel_created:
                channel_age = (datetime.now() - channel_created).days
            
            # 2.4 Извлекаем количество подписчиков
            subscribers_count = "—"  # По умолчанию неизвестно
            
            # Метод 1: Из JSON данных
            if channel_json_data:
                try:
                    header_renderer = channel_json_data.get('header', {}).get('c4TabbedHeaderRenderer', {})
                    if header_renderer:
                        subscribers_text = header_renderer.get('subscriberCountText', {}).get('simpleText', '0')
                        # Если указано "скрыто", то оставляем прочерк
                        if not subscribers_text or "скрыто" in subscribers_text.lower() or "hidden" in subscribers_text.lower():
                            subscribers_count = "—"
                        else:
                            # Очищаем текст и извлекаем число
                            clean_text = subscribers_text.replace('subscribers', '').replace('подписчиков', '').strip()
                            if "K" in clean_text or "тыс." in clean_text:
                                # Преобразуем тысячи (K) в числа
                                value = float(clean_text.replace("K", "").replace("тыс.", "").strip().replace(",", "."))
                                subscribers_count = f"{int(value * 1000):,}".replace(",", " ")
                            elif "M" in clean_text or "млн" in clean_text:
                                # Преобразуем миллионы (M) в числа
                                value = float(clean_text.replace("M", "").replace("млн", "").strip().replace(",", "."))
                                subscribers_count = f"{int(value * 1000000):,}".replace(",", " ")
                            else:
                                # Просто удаляем нецифровые символы
                                subscribers_digits = re.findall(r'\d+', clean_text.replace(',', '').replace(' ', ''))
                                if subscribers_digits:
                                    subscribers_count = f"{int(''.join(subscribers_digits)):,}".replace(",", " ")
                except:
                    pass
            
            # Метод 2: Из HTML с помощью регулярных выражений
            if subscribers_count == "—":
                subscribers_patterns = [
                    r'"subscriberCountText":\s*{\s*"simpleText":\s*"([^"]+)"',
                    r'(\d+[,\s]*\d*\s*[KkMmтыс.млн]*) subscribers',
                    r'(\d+[,\s]*\d*\s*[KkMmтыс.млн]*) подписчиков'
                ]
                
                for pattern in subscribers_patterns:
                    match = re.search(pattern, html)
                    if match:
                        subscribers_text = match.group(1)
                        
                        # Если указано "скрыто", то оставляем прочерк
                        if "скрыто" in subscribers_text.lower() or "hidden" in subscribers_text.lower():
                            subscribers_count = "—"
                        else:
                            # Форматируем число подписчиков
                            try:
                                if "K" in subscribers_text or "тыс." in subscribers_text:
                                    # Преобразуем тысячи (K) в числа
                                    value = float(subscribers_text.replace("K", "").replace("тыс.", "").strip().replace(",", "."))
                                    subscribers_count = f"{int(value * 1000):,}".replace(",", " ")
                                elif "M" in subscribers_text or "млн" in subscribers_text:
                                    # Преобразуем миллионы (M) в числа
                                    value = float(subscribers_text.replace("M", "").replace("млн", "").strip().replace(",", "."))
                                    subscribers_count = f"{int(value * 1000000):,}".replace(",", " ")
                                else:
                                    # Просто удаляем нецифровые символы
                                    subscribers_digits = re.findall(r'\d+', subscribers_text.replace(',', '').replace(' ', ''))
                                    if subscribers_digits:
                                        subscribers_count = f"{int(''.join(subscribers_digits)):,}".replace(",", " ")
                            except:
                                subscribers_count = "—"
                        break
            
            # 2.5 Извлекаем страну
            country = "Неизвестно"
            
            # Метод 1: Из JSON данных
            if channel_json_data:
                try:
                    # Проверяем разные пути к данным о стране
                    about_tab = None
                    for tab in channel_json_data.get('contents', {}).get('twoColumnBrowseResultsRenderer', {}).get('tabs', []):
                        if tab.get('tabRenderer', {}).get('title') == 'About':
                            about_tab = tab
                            break
                    
                    if about_tab:
                        # Ищем блок с информацией о стране
                        content_blocks = about_tab.get('tabRenderer', {}).get('content', {}).get('sectionListRenderer', {}).get('contents', [])
                        for block in content_blocks:
                            items = block.get('itemSectionRenderer', {}).get('contents', [])
                            for item in items:
                                metadata = item.get('channelAboutFullMetadataRenderer', {})
                                if metadata and 'country' in metadata:
                                    country_text = metadata.get('country', {}).get('simpleText', 'Неизвестно')
                                    if country_text and country_text != 'Неизвестно':
                                        country = country_text
                except:
                    pass
            
            # Метод 2: Из HTML с помощью регулярных выражений
            if country == "Неизвестно":
                country_patterns = [
                    r'"country":\s*{\s*"simpleText":\s*"([^"]+)"',
                    r'Страна:\s+([^<]+)<',
                    r'<div class="country">([^<]+)<'
                ]
                
                for pattern in country_patterns:
                    match = re.search(pattern, html)
                    if match:
                        country_text = match.group(1).strip()
                        if country_text:
                            country = country_text
                            break
            
            # Собираем результат
            result = {
                "Ссылка на канал": channel_url,
                "Название канала": channel_name or "Неизвестно",
                "Общее число просмотров": total_views,
                "Количество видео": video_count,
                "Возраст канала (дней)": channel_age,
                "Дата создания": channel_created.strftime("%Y-%m-%d") if channel_created else "Неизвестно",
                "Количество подписчиков": subscribers_count,
                "Страна": country
            }
            
            logger.info(f"Получена информация о канале {channel_url}: {result}")
            
            # Сохраняем в кэш
            channel_info_cache[channel_url] = result
            return result
            
    except Exception as e:
        logger.error(f"Ошибка при получении информации о канале {channel_url}: {e}")
    
    # В случае ошибки возвращаем базовую информацию
    default_info = {
        "Ссылка на канал": channel_url,
        "Название канала": "Неизвестно",
        "Общее число просмотров": 0,
        "Количество видео": 0,
        "Возраст канала (дней)": 0,
        "Дата создания": "Неизвестно",
        "Количество подписчиков": "—",
        "Страна": "Неизвестно"
    }
    
    # Сохраняем в кэш даже дефолтные данные, чтобы не запрашивать повторно
    channel_info_cache[channel_url] = default_info
    return default_info

def fetch_channel_data(channel_id, api_key):
    """
    Получает информацию о канале через YouTube Data API
    
    Args:
        channel_id (str): ID канала YouTube
        api_key (str): Ключ API YouTube
        
    Returns:
        dict: Словарь с информацией о канале или None в случае ошибки
    """
    logger.info(f"Запрос данных канала {channel_id} через API")
    
    try:
        # Извлекаем channel_id из URL, если передан полный URL
        if "youtube.com" in channel_id:
            if "/channel/" in channel_id:
                channel_id = channel_id.split("/channel/")[1].split("/")[0]
            elif "/@" in channel_id:
                # Для пользовательских URL требуется дополнительный запрос
                custom_url = channel_id.split("/@")[1].split("/")[0]
                search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={custom_url}&type=channel&key={api_key}"
                search_response = requests.get(search_url)
                if search_response.status_code == 200:
                    search_data = search_response.json()
                    if search_data.get('items'):
                        channel_id = search_data['items'][0]['id']['channelId']
                    else:
                        logger.warning(f"Не удалось найти channel_id для {channel_id}")
                        return None
                else:
                    logger.warning(f"Ошибка API при поиске канала: {search_response.status_code}")
                    return None
        
        # Формируем запрос к API
        base_url = "https://www.googleapis.com/youtube/v3/channels"
        params = {
            'part': 'snippet,statistics,contentDetails',
            'id': channel_id,
            'key': api_key
        }
        
        # Отправляем запрос
        response = requests.get(base_url, params=params)
        
        if response.status_code != 200:
            logger.warning(f"Ошибка API при получении данных канала: {response.status_code}")
            logger.warning(f"Ответ API: {response.text}")
            return None
        
        data = response.json()
        
        # Проверяем, есть ли результаты
        if not data.get('items'):
            logger.warning(f"API не вернул данные для канала {channel_id}")
            return None
        
        channel_info = data['items'][0]
        
        # Извлекаем нужные данные
        snippet = channel_info.get('snippet', {})
        statistics = channel_info.get('statistics', {})
        
        # Дата создания канала
        published_at = snippet.get('publishedAt')
        if published_at:
            published_date = datetime.strptime(published_at, "%Y-%m-%dT%H:%M:%SZ")
            channel_age = (datetime.now() - published_date).days
        else:
            channel_age = 0
        
        # Создаем словарь с информацией
        result = {
            "Ссылка на канал": f"https://www.youtube.com/channel/{channel_id}",
            "Название канала": snippet.get('title', 'Неизвестно'),
            "Описание": snippet.get('description', ''),
            "Дата создания": published_at,
            "Возраст канала (дней)": channel_age,
            "Количество подписчиков": int(statistics.get('subscriberCount', 0)),
            "Количество видео": int(statistics.get('videoCount', 0)),
            "Общее число просмотров": int(statistics.get('viewCount', 0)),
            "Страна": snippet.get('country', 'Неизвестно'),
            "Миниатюра": snippet.get('thumbnails', {}).get('high', {}).get('url', '')
        }
        
        logger.info(f"Успешно получены данные канала {channel_id} через API")
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при получении данных канала через API: {str(e)}")
        return None

def get_video_details_fast(video_url):
    """
    Быстрое получение деталей видео через HTTP запрос.
    
    Args:
        video_url (str): URL видео на YouTube
        
    Returns:
        dict: Словарь с информацией о видео или None в случае ошибки
    """
    if video_url in video_cache:
        return video_cache[video_url]
        
    try:
        # Извлекаем ID видео
        video_id = None
        if "youtube.com/watch?v=" in video_url:
            video_id = video_url.split("watch?v=")[1].split("&")[0]
        elif "youtu.be/" in video_url:
            video_id = video_url.split("youtu.be/")[1].split("?")[0]
            
        if not video_id:
            return None
            
        # Делаем HTTP запрос к странице видео
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
        }
        
        response = requests.get(video_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            html = response.text
            
            # Проверяем на страницу с ограничениями
            if "consent.youtube.com" in html or "consent.google.com" in html:
                logger.error(f"Получена страница согласия/предупреждения вместо страницы видео: {video_url}")
                
                # Сохраняем HTML страницы для диагностики
                debug_dir = "debug_data"
                os.makedirs(debug_dir, exist_ok=True)
                file_path = os.path.join(debug_dir, f"video_{video_id}_consent_page.html")
                try:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(html)
                    logger.info(f"Сохранена HTML-страница согласия видео для отладки: {file_path}")
                except Exception as e:
                    logger.error(f"Не удалось сохранить HTML-страницу видео для отладки: {str(e)}")
                
                # Возвращаем базовую структуру с предупреждением
                default_info = {
                    "url": video_url,
                    "title": f"⚠️ YouTube блокирует доступ ({video_id})",
                    "views": 0,
                    "publication_date": "01.01.2000",
                    "channel_name": "⚠️ Доступ ограничен",
                    "channel_url": None,
                    "error": "YouTube требует подтверждение согласия"
                }
                video_cache[video_url] = default_info
                return default_info
            
            # Извлекаем название видео
            title = None
            
            # Здесь должен быть код для извлечения различных параметров видео
            # Предполагаю, что отсутствует блок кода, который должен был быть здесь
            # Например, строки для извлечения views, publication_date, channel_url и channel_name
            views = 0
            publication_date = None
            channel_url = None
            channel_name = None
            
            # Создаем словарь с результатами
            result = {
                "title": title or f"Видео {video_id}",
                "views": views or 0,
                "publication_date": publication_date,
                "channel_url": channel_url,
                "channel_name": channel_name
            }
            
            logger.info(f"Извлечены данные видео {video_url}: {result}")
            
            # Сохраняем в кэш
            video_cache[video_url] = result
            return result
            
    except Exception as e:
        logger.error(f"Ошибка при быстром получении информации о видео {video_url}: {e}")
    
    return None

# Инициализируем кэш для видео и каналов
video_cache = {}
channel_info_cache = {}

# Функция для отображения раздела тестирования API каналов YouTube
def render_api_tester_section():
    """
    Отображает раздел тестирования API каналов YouTube.
    Позволяет получать информацию о каналах напрямую через API.
    """
    st.markdown("## Тестирование API каналов YouTube")
    
    with st.expander("Описание инструмента", expanded=False):
        st.markdown("""
        Этот инструмент позволяет тестировать сбор данных о YouTube каналах через YouTube Data API v3.
        
        **Принцип работы:**
        1. Вы вводите список URL-адресов YouTube каналов (по одному на строку)
        2. Инструмент собирает данные о каждом канале через официальный API YouTube
        3. Результаты отображаются в таблице
        
        **Собираемые данные:**
        - Название канала
        - Количество видео
        - Общее число просмотров
        - Возраст канала (дней)
        - Число подписчиков
        - Страна
        """)
    
    # Проверяем наличие API ключа
    api_key = st.session_state.get("youtube_api_key")
    if not api_key:
        api_key = load_api_key_from_secrets()
        if api_key:
            st.session_state["youtube_api_key"] = api_key
    
    # Показываем статус API ключа
    if api_key:
        st.success("✅ YouTube API ключ загружен и готов к использованию")
    else:
        st.error("❌ YouTube API ключ не настроен. Добавьте его в файл .streamlit/secrets.toml")
        with st.expander("Как настроить API ключ"):
            st.markdown("""
            1. Создайте файл `.streamlit/secrets.toml` со следующим содержимым:
            ```toml
            [youtube]
            api_key = "ВАШ_КЛЮЧ_API_YOUTUBE"
            ```
            
            2. Получите API ключ на странице: https://console.cloud.google.com/apis/credentials
            3. Активируйте YouTube Data API v3 в Google Cloud Console
            4. Перезапустите приложение
            """)
        return
    
    # Список каналов для тестирования
    st.subheader("Список каналов для тестирования")
    channels_input = st.text_area(
        "Введите URL каналов YouTube (по одному на строку):",
        placeholder="https://www.youtube.com/@ChannelName\nhttps://www.youtube.com/channel/UCXXXXXXXXXXXXXXXXXX",
        height=150,
        key="api_tester_channels_input"
    )
    
    # Глобальная переменная для хранения результатов
    if "api_test_results" not in st.session_state:
        st.session_state.api_test_results = None
    
    # Кнопка для запуска тестирования
    start_test = st.button("Собрать данные о каналах", key="start_api_test")
    
    # Обработка нажатия кнопки
    if start_test and channels_input:
        # Разбиваем текст на строки и фильтруем пустые
        channel_urls = [url.strip() for url in channels_input.strip().split('\n') if url.strip()]
        
        if not channel_urls:
            st.error("Пожалуйста, введите хотя бы один URL канала YouTube.")
            return
        
        # Создаем прогресс-бар и сообщение о статусе
        progress_bar = st.progress(0)
        status_message = st.empty()
        
        status_message.info(f"Подготовка к сбору данных о {len(channel_urls)} каналах...")
        progress_bar.progress(10)
        
        # Создаем экземпляр анализатора YouTube только для работы с API
        api_analyzer = YouTubeAnalyzer(headless=True, use_proxy=False)
        
        # Запускаем сбор данных
        channels_data = []
        total_channels = len(channel_urls)
        
        for idx, url in enumerate(channel_urls):
            try:
                # Обновляем прогресс
                progress = int(10 + (idx / total_channels) * 80)
                progress_bar.progress(progress)
                status_message.info(f"Обработка канала {idx+1}/{total_channels}: {url}")
                
                # Извлекаем ID канала из URL
                channel_id = api_analyzer._extract_channel_id(url)
                
                if not channel_id:
                    # Пытаемся определить ID канала через API по имени канала
                    if "/@" in url or "/c/" in url or "/user/" in url:
                        # Извлекаем имя канала из URL для поиска
                        channel_name = None
                        if "/@" in url:
                            channel_name = url.split("/@")[1].split("/")[0]
                        elif "/c/" in url:
                            channel_name = url.split("/c/")[1].split("/")[0]
                        elif "/user/" in url:
                            channel_name = url.split("/user/")[1].split("/")[0]
                        
                        if channel_name:
                            # Поиск канала через API
                            search_url = "https://www.googleapis.com/youtube/v3/search"
                            search_params = {
                                'part': 'snippet',
                                'q': channel_name,
                                'type': 'channel',
                                'maxResults': 1,
                                'key': api_key
                            }
                            
                            search_response = requests.get(search_url, params=search_params)
                            if search_response.status_code == 200:
                                search_data = search_response.json()
                                if search_data.get('items') and len(search_data['items']) > 0:
                                    channel_id = search_data['items'][0]['id']['channelId']
                
                if not channel_id:
                    status_message.warning(f"Не удалось определить ID канала для URL: {url}. Пропускаю...")
                    channels_data.append({
                        "URL канала": url,
                        "Название канала": "❌ Не удалось определить ID канала",
                        "Количество видео": 0,
                        "Общее число просмотров": 0,
                        "Возраст канала (дней)": 0,
                        "Количество подписчиков": 0,
                        "Страна": "Неизвестно"
                    })
                    continue
                
                # Получаем данные о канале через API
                channel_details = api_analyzer._get_channel_details_api(channel_id, api_key)
                
                if not channel_details:
                    status_message.warning(f"Не удалось получить данные о канале: {url}. Пропускаю...")
                    channels_data.append({
                        "URL канала": url,
                        "Название канала": "❌ Не удалось получить данные",
                        "ID канала": channel_id,
                        "Количество видео": 0,
                        "Общее число просмотров": 0,
                        "Возраст канала (дней)": 0,
                        "Количество подписчиков": 0,
                        "Страна": "Неизвестно"
                    })
                    continue
                
                # Формируем запись с данными канала
                channel_data = {
                    "URL канала": url,
                    "ID канала": channel_id,
                    "Название канала": channel_details.get("title", "Неизвестно"),
                    "Количество видео": channel_details.get("video_count", 0),
                    "Общее число просмотров": channel_details.get("view_count", 0),
                    "Возраст канала (дней)": channel_details.get("channel_age_days", 0),
                    "Количество подписчиков": channel_details.get("subscriber_count", 0),
                    "Страна": channel_details.get("country", "Неизвестно")
                }
                
                channels_data.append(channel_data)
                status_message.success(f"Успешно получены данные о канале: {channel_details.get('title', 'Неизвестно')}")
                
            except Exception as e:
                status_message.error(f"Ошибка при обработке канала {url}: {str(e)}")
                channels_data.append({
                    "URL канала": url,
                    "Название канала": "❌ Ошибка при обработке",
                    "Количество видео": 0,
                    "Общее число просмотров": 0,
                    "Возраст канала (дней)": 0,
                    "Количество подписчиков": 0,
                    "Страна": "Неизвестно",
                    "Ошибка": str(e)
                })
        
        # Завершаем прогресс
        progress_bar.progress(100)
        
        if channels_data:
            # Преобразуем в DataFrame
            channels_df = pd.DataFrame(channels_data)
            st.session_state.api_test_results = channels_df
            status_message.success(f"Сбор данных завершен. Получена информация о {len(channels_data)} каналах.")
        else:
            status_message.error("Не удалось собрать данные ни об одном канале.")
    
    # Отображаем результаты, если они есть
    if st.session_state.api_test_results is not None and not st.session_state.api_test_results.empty:
        st.subheader("Результаты тестирования API")
        
        results_df = st.session_state.api_test_results
        
        # Форматируем числовые колонки
        if "Общее число просмотров" in results_df.columns:
            results_df["Общее число просмотров"] = results_df["Общее число просмотров"].apply(
                lambda x: f"{int(x):,}".replace(",", " ") if isinstance(x, (int, float)) else x
            )
        
        if "Количество подписчиков" in results_df.columns:
            results_df["Количество подписчиков"] = results_df["Количество подписчиков"].apply(
                lambda x: f"{int(x):,}".replace(",", " ") if isinstance(x, (int, float)) else x
            )
        
        if "Количество видео" in results_df.columns:
            results_df["Количество видео"] = results_df["Количество видео"].apply(
                lambda x: f"{int(x):,}".replace(",", " ") if isinstance(x, (int, float)) else x
            )
        
        # Добавляем ссылки на каналы
        def make_clickable(url, text=None):
            text = text or url
            return f'<a href="{url}" target="_blank">{text}</a>'
        
        if "URL канала" in results_df.columns and "Название канала" in results_df.columns:
            results_df["Название канала"] = results_df.apply(
                lambda row: make_clickable(row["URL канала"], row["Название канала"]) 
                if not row["Название канала"].startswith("❌") else row["Название канала"],
                axis=1
            )
        
        # Исключаем некоторые колонки для отображения
        display_columns = [col for col in results_df.columns if col not in ["ID канала", "URL канала", "Ошибка"]]
        
        # Отображаем таблицу
        st.write(results_df[display_columns].to_html(escape=False), unsafe_allow_html=True)
        
        # Создаем копию dataframe для экспорта без форматирования
        export_df = results_df.copy()
        
        # Для экспорта подготавливаем данные без форматирования
        if "Общее число просмотров" in export_df.columns:
            export_df["Общее число просмотров"] = pd.to_numeric(export_df["Общее число просмотров"].str.replace(" ", ""), errors="coerce")
        
        if "Количество подписчиков" in export_df.columns:
            export_df["Количество подписчиков"] = pd.to_numeric(export_df["Количество подписчиков"].str.replace(" ", ""), errors="coerce")
        
        if "Количество видео" in export_df.columns:
            export_df["Количество видео"] = pd.to_numeric(export_df["Количество видео"].str.replace(" ", ""), errors="coerce")
            
        # Обработка стран - перевод на английский для более универсального формата
        country_mapping = {
            "Неизвестно": "Unknown",
            "Россия": "Russia",
            "США": "United States",
            "Украина": "Ukraine",
            "Германия": "Germany",
            "Великобритания": "United Kingdom",
            "Франция": "France",
            "Канада": "Canada",
            "Австралия": "Australia",
            "Испания": "Spain",
            "Италия": "Italy",
            "Китай": "China",
            "Япония": "Japan",
            "Индия": "India",
            "Бразилия": "Brazil"
        }
        
        if "Страна" in export_df.columns:
            export_df["Страна"] = export_df["Страна"].map(lambda x: country_mapping.get(x, x))
        
        # Восстанавливаем колонку "Ссылка на канал" для экспорта
        if "URL канала" in export_df.columns:
            export_df["Ссылка на канал"] = export_df["URL канала"]
            
        # Добавляем кнопки для скачивания результатов в разных форматах
        col1, col2 = st.columns(2)
        
        with col1:
            # Кнопка для скачивания CSV
            csv = export_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📄 Скачать CSV файл",
                data=csv,
                file_name="youtube_channels_api_test.csv",
                mime="text/csv",
            )
            
        with col2:
            # Кнопка для скачивания TSV
            tsv = export_df.to_csv(index=False, sep='\t').encode('utf-8')
            st.download_button(
                label="📊 Скачать TSV файл",
                data=tsv,
                file_name="youtube_channels_api_test.tsv",
                mime="text/tab-separated-values",
            )

# Функция для отображения раздела тестирования API видео YouTube
def render_video_api_tester_section():
    """
    Отображает раздел тестирования API видео YouTube.
    Позволяет получать информацию о видео напрямую через API.
    """
    st.markdown("## Тестирование API видео YouTube")
    
    with st.expander("Описание инструмента", expanded=False):
        st.markdown("""
        Этот инструмент позволяет тестировать сбор данных о YouTube видео через YouTube Data API v3.
        
        **Принцип работы:**
        1. Вы вводите список URL-адресов YouTube видео (по одному на строку)
        2. Инструмент собирает данные о каждом видео через официальный API YouTube
        3. Результаты отображаются в таблице
        
        **Собираемые данные:**
        - URL видео (без параметров)
        - Заголовок видео
        - Превью видео
        - Дата и время публикации
        - Количество просмотров
        - Категория видео
        - Язык видео
        - Транскрипция
        """)
    
    # Проверяем наличие API ключа
    api_key = st.session_state.get("youtube_api_key")
    if not api_key:
        api_key = load_api_key_from_secrets()
        if api_key:
            st.session_state["youtube_api_key"] = api_key
    
    # Показываем статус API ключа
    if api_key:
        st.success("✅ YouTube API ключ загружен и готов к использованию")
    else:
        st.error("❌ YouTube API ключ не настроен. Добавьте его в файл .streamlit/secrets.toml")
        with st.expander("Как настроить API ключ"):
            st.markdown("""
            1. Создайте файл `.streamlit/secrets.toml` со следующим содержимым:
            ```toml
            [youtube]
            api_key = "ВАШ_КЛЮЧ_API_YOUTUBE"
            ```
            
            2. Получите API ключ на странице: https://console.cloud.google.com/apis/credentials
            3. Активируйте YouTube Data API v3 в Google Cloud Console
            4. Перезапустите приложение
            """)
        return
    
    # Список видео для тестирования
    st.subheader("Список видео для тестирования")
    videos_input = st.text_area(
        "Введите URL видео YouTube (по одному на строку):",
        placeholder="https://www.youtube.com/watch?v=video_id1\nhttps://youtu.be/video_id2",
        height=150,
        key="api_tester_videos_input"
    )
    
    # Глобальная переменная для хранения результатов
    if "video_api_test_results" not in st.session_state:
        st.session_state.video_api_test_results = None
    
    # Кнопка для запуска тестирования
    start_test = st.button("Собрать данные о видео", key="start_video_api_test")
    
    # Обработка нажатия кнопки
    if start_test and videos_input:
        # Разбиваем текст на строки и фильтруем пустые
        video_urls = [url.strip() for url in videos_input.strip().split('\n') if url.strip()]
        
        if not video_urls:
            st.error("Пожалуйста, введите хотя бы один URL видео YouTube.")
            return
        
        # Создаем прогресс-бар и сообщение о статусе
        progress_bar = st.progress(0)
        status_message = st.empty()
        
        status_message.info(f"Подготовка к сбору данных о {len(video_urls)} видео...")
        progress_bar.progress(10)
        
        # Создаем экземпляр анализатора YouTube только для работы с API
        api_analyzer = YouTubeAnalyzer(headless=True, use_proxy=False)
        
        # Запускаем сбор данных
        videos_data = []
        total_videos = len(video_urls)
        
        for idx, url in enumerate(video_urls):
            try:
                # Обновляем прогресс
                progress = int(10 + (idx / total_videos) * 80)
                progress_bar.progress(progress)
                status_message.info(f"Обработка видео {idx+1}/{total_videos}: {url}")
                
                # Очищаем URL от параметров
                clean_url = clean_youtube_url(url)
                
                # Извлекаем ID видео из URL
                video_id = None
                if "youtube.com/watch?v=" in url:
                    video_id = url.split("watch?v=")[1].split("&")[0]
                elif "youtu.be/" in url:
                    video_id = url.split("youtu.be/")[1].split("?")[0]
                
                if not video_id:
                    status_message.warning(f"Не удалось определить ID видео для URL: {url}. Пропускаю...")
                    videos_data.append({
                        "URL видео": url,
                        "Заголовок видео": "❌ Не удалось определить ID видео",
                        "Превью": "",
                        "Дата публикации": "",
                        "Количество просмотров": 0,
                        "Категория": "Неизвестно",
                        "Язык": "Неизвестно",
                        "Транскрипция": "Недоступно"
                    })
                    continue
                
                # Получаем данные о видео через API
                video_details = api_analyzer._get_video_details_api(video_id, api_key)
                
                if not video_details:
                    status_message.warning(f"Не удалось получить данные о видео: {url}. Пропускаю...")
                    videos_data.append({
                        "URL видео": clean_url,
                        "Заголовок видео": "❌ Не удалось получить данные",
                        "ID видео": video_id,
                        "Превью": "",
                        "Дата публикации": "",
                        "Количество просмотров": 0,
                        "Категория": "Неизвестно",
                        "Язык": "Неизвестно",
                        "Транскрипция": "Недоступно"
                    })
                    continue
                
                # Формируем запись с данными видео
                video_data = {
                    "URL видео": clean_url,
                    "ID видео": video_id,
                    "Заголовок видео": video_details.get("title", "Неизвестно"),
                    "Превью": video_details.get("thumbnail_url", ""),
                    "Дата публикации": video_details.get("publication_date", ""),
                    "Количество просмотров": video_details.get("view_count", 0),
                    "Категория": video_details.get("category", "Неизвестно"),
                    "Язык": video_details.get("language", "Неизвестно"),
                    "Транскрипция": video_details.get("transcript", "Недоступно")
                }
                
                videos_data.append(video_data)
                status_message.success(f"Успешно получены данные о видео: {video_details.get('title', 'Неизвестно')}")
                
            except Exception as e:
                status_message.error(f"Ошибка при обработке видео {url}: {str(e)}")
                videos_data.append({
                    "URL видео": url,
                    "Заголовок видео": "❌ Ошибка при обработке",
                    "Превью": "",
                    "Дата публикации": "",
                    "Количество просмотров": 0,
                    "Категория": "Неизвестно",
                    "Язык": "Неизвестно",
                    "Транскрипция": "Недоступно",
                    "Ошибка": str(e)
                })
        
        # Завершаем прогресс
        progress_bar.progress(100)
        
        if videos_data:
            # Преобразуем в DataFrame
            videos_df = pd.DataFrame(videos_data)
            st.session_state.video_api_test_results = videos_df
            status_message.success(f"Сбор данных завершен. Получена информация о {len(videos_data)} видео.")
        else:
            status_message.error("Не удалось собрать данные ни об одном видео.")
    
    # Отображаем результаты, если они есть
    if st.session_state.video_api_test_results is not None and not st.session_state.video_api_test_results.empty:
        st.subheader("Результаты тестирования API")
        
        results_df = st.session_state.video_api_test_results
        
        # Сохраняем оригинальные заголовки (без HTML) для экспорта
        original_titles = results_df["Заголовок видео"].copy()
        
        # Форматируем числовую колонку просмотров
        if "Количество просмотров" in results_df.columns:
            results_df["Количество просмотров"] = results_df["Количество просмотров"].apply(
                lambda x: f"{int(x):,}".replace(",", " ") if isinstance(x, (int, float)) else x
            )
        
        # Создаем колонку с превью
        if "Превью" in results_df.columns:
            results_df["Превью миниатюра"] = results_df["Превью"].apply(
                lambda url: f'<a href="{url}" target="_blank"><img src="{url}" width="120" /></a>' if url else ""
            )
        
        # Добавляем ссылки на видео
        def make_clickable(url, text=None):
            text = text or url
            return f'<a href="{url}" target="_blank">{text}</a>'
        
        if "URL видео" in results_df.columns and "Заголовок видео" in results_df.columns:
            results_df["Заголовок видео"] = results_df.apply(
                lambda row: make_clickable(row["URL видео"], row["Заголовок видео"]) 
                if not row["Заголовок видео"].startswith("❌") else row["Заголовок видео"],
                axis=1
            )
        
        # Исключаем некоторые колонки для отображения
        display_columns = [
            "Заголовок видео", "Превью миниатюра", "Дата публикации", 
            "Количество просмотров", "Категория", "Язык", "Транскрипция"
        ]
        
        # Отображаем таблицу
        st.write(results_df[display_columns].to_html(escape=False), unsafe_allow_html=True)
        
        # Создаем копию dataframe для экспорта без форматирования
        export_df = results_df.copy()
        
        # Для экспорта подготавливаем данные без форматирования
        if "Количество просмотров" in export_df.columns:
            export_df["Количество просмотров"] = pd.to_numeric(export_df["Количество просмотров"].str.replace(" ", ""), errors="coerce")
        
        # Добавляем колонку "Ссылка на превью" для экспорта
        if "Превью" in export_df.columns:
            export_df["Ссылка на превью"] = export_df["Превью"]
        
        # Восстанавливаем оригинальные заголовки для экспорта
        if "Заголовок видео" in export_df.columns:
            export_df["Заголовок видео"] = original_titles
            
        # Добавляем кнопки для скачивания результатов в разных форматах
        col1, col2 = st.columns(2)
        
        with col1:
            # Кнопка для скачивания CSV
            csv = export_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📄 Скачать CSV файл",
                data=csv,
                file_name="youtube_videos_api_test.csv",
                mime="text/csv",
            )
            
        with col2:
            # Кнопка для скачивания TSV
            tsv = export_df.to_csv(index=False, sep='\t').encode('utf-8')
            st.download_button(
                label="📊 Скачать TSV файл",
                data=tsv,
                file_name="youtube_videos_api_test.tsv",
                mime="text/tab-separated-values",
            )

if __name__ == "__main__":
    main() 