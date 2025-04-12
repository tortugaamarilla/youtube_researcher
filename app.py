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

from youtube_scraper import YouTubeAnalyzer, check_proxy
from llm_analyzer import LLMAnalyzer
from utils import parse_youtube_url, get_proxy_list

# Настройка логирования
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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

# Настройка страницы Streamlit
st.set_page_config(
    page_title="YouTube Researcher",
    page_icon="🎬",
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
def filter_by_date(video: Dict[str, Any], days_limit: int) -> bool:
    """
    Фильтрует видео по дате публикации.
    
    Args:
        video (Dict[str, Any]): Информация о видео.
        days_limit (int): Ограничение по дням.
        
    Returns:
        bool: True, если видео опубликовано в пределах указанного количества дней, иначе False.
    """
    # Если не указано ограничение по дням, пропускаем все видео
    if days_limit <= 0:
        return True
        
    pub_date = video.get("publication_date")
    
    # Если дата отсутствует, но все остальные данные есть,
    # принимаем решение в зависимости от строгости фильтрации
    if not pub_date:
        # Если видео имеет заголовок и URL, считаем его валидным
        return bool(video.get("title") and video.get("url"))
        
    # Проверяем, что дата - объект datetime
    if not isinstance(pub_date, datetime):
        # Если дата не в правильном формате, но видео имеет заголовок и URL,
        # считаем его валидным
        return bool(video.get("title") and video.get("url"))
        
    # Проверяем, попадает ли дата в указанный интервал
    days_diff = (datetime.now() - pub_date).days
    
    return days_diff <= days_limit

# Функция для фильтрации видео по просмотрам
def filter_by_views(video: Dict[str, Any], min_views: int) -> bool:
    """
    Фильтрует видео по количеству просмотров.
    
    Args:
        video (Dict[str, Any]): Информация о видео.
        min_views (int): Минимальное количество просмотров.
        
    Returns:
        bool: True, если у видео достаточно просмотров, иначе False.
    """
    # Если не указано минимальное количество просмотров, пропускаем все видео
    if min_views <= 0:
        return True
        
    views = video.get("views", 0)
    
    # Проверяем корректность значения просмотров
    if not isinstance(views, (int, float)):
        try:
            views = int(views)
        except (ValueError, TypeError):
            # Если количество просмотров невозможно преобразовать в число,
            # но видео имеет заголовок и URL, считаем его валидным
            return bool(video.get("title") and video.get("url"))
    
    return views >= min_views

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
    
    # Проверяем кэш
    if cached_data and url in cached_data:
        logger.info(f"Использование кэшированных данных для {url}")
        return cached_data[url]
    
    # Получаем данные с повторными попытками
    for attempt in range(max_retries):
        try:
            logger.info(f"Попытка {attempt+1}/{max_retries} получения данных видео: {url}")
            video_data = _youtube_analyzer.get_video_details(url)
            
            if video_data and video_data.get("title") and video_data["title"] != "Недоступно":
                logger.info(f"Успешно получены данные для {url}")
                return video_data
            else:
                logger.warning(f"Попытка {attempt+1}: Не удалось получить полные данные для {url}")
                time.sleep(1)  # Короткая пауза перед повторной попыткой
        except Exception as e:
            logger.error(f"Ошибка при получении данных для {url} (попытка {attempt+1}): {e}")
            time.sleep(1)
    
    # Возвращаем базовую информацию, если все попытки не удались
    logger.warning(f"Все попытки получить данные для {url} не удались. Возвращаем базовую информацию.")
    return {
        "url": url,
        "title": f"Недоступно ({url.split('/')[-1]})",
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
                                        video_info = yt.get_video_details(video_url)
                                        if video_info and 'publish_date' in video_info:
                                            all_channel_videos.append((video_url, video_info['publish_date']))
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
                # Обновляем прогресс
                current_progress = (i / total_links)
                progress_text = f"Обработка ссылки {i+1}/{total_links}: {link[:50]}..."
                
                if progress_bar:
                    progress_bar.progress(current_progress, text=progress_text)
                
                # Если это прямая ссылка на видео
                if "youtube.com/watch" in link or "youtu.be/" in link:
                    if msg_container:
                        msg_container.info(f"Получение рекомендаций для видео: {link}")
                        
                    # Получаем рекомендации первого уровня
                    rec1 = yt.get_recommended_videos(link, limit=20)
                    
                    if rec1:
                        first_level_recommendations.extend(rec1)
                        if msg_container:
                            msg_container.success(f"Получено {len(rec1)} рекомендаций первого уровня")
                    else:
                        if msg_container:
                            msg_container.warning(f"Не удалось получить рекомендации для видео: {link}")
                            
                # Иначе, это канал
                else:
                    if msg_container:
                        msg_container.info(f"Обработка канала: {link}")
                        
                    # Получаем последние видео с канала
                    videos = yt.get_last_videos_from_channel(link, limit=5)
                    
                    if videos:
                        if msg_container:
                            msg_container.success(f"Получено {len(videos)} видео с канала")
                        
                        # Получаем рекомендации для каждого видео с канала
                        for j, video_url in enumerate(videos):
                            rec1 = yt.get_recommended_videos(video_url, limit=20)
                            
                            if rec1:
                                first_level_recommendations.extend(rec1)
                                if msg_container:
                                    msg_container.success(f"Получено {len(rec1)} рекомендаций из видео {j+1}/{len(videos)}")
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
                    
                    rec2 = yt.get_recommended_videos(rec_url, limit=10)
                    
                    if rec2:
                        second_level_recommendations.extend(rec2)
                        if msg_container:
                            msg_container.success(f"Получено {len(rec2)} рекомендаций второго уровня из видео {j+1}/{sample_size}")
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
        if progress_bar:
            progress_bar.progress(1.0, text="Завершено")
        
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
                         existing_analyzer: YouTubeAnalyzer = None) -> pd.DataFrame:
    """
    Функция для сбора рекомендаций из списка исходных ссылок.
    
    Args:
        source_links (List[str]): Список ссылок на видео/каналы YouTube
        google_account (Dict[str, str], optional): Аккаунт Google для авторизации
        prewatch_settings (Dict[str, Any], optional): Настройки предварительного просмотра
        channel_videos_limit (int): Количество последних видео с канала
        recommendations_per_video (int): Количество рекомендаций для каждого видео
        existing_analyzer (YouTubeAnalyzer, optional): Существующий экземпляр анализатора
        
    Returns:
        pd.DataFrame: Датафрейм с результатами
    """
    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
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
            # Извлекаем настройки предварительного просмотра
            total_videos = prewatch_settings.get("total_videos", 20)
            distribution = prewatch_settings.get("distribution", "Равномерно по всем каналам")
            min_watch_time = prewatch_settings.get("min_watch_time", 15)
            max_watch_time = prewatch_settings.get("max_watch_time", 45)
            like_probability = prewatch_settings.get("like_probability", 0.7)
            watch_percentage = prewatch_settings.get("watch_percentage", 0.3)
            
            # Выбираем видео для предварительного просмотра
            videos_to_watch = []
            channel_counts = {}  # Для подсчета количества видео с каждого канала
            
            status_text.text("Подготовка к предварительному просмотру видео...")
            
            # Сначала получаем все доступные видео с каналов
            all_channel_videos = []
            
            # Проходим по каждой ссылке и собираем видео для просмотра
            for link in valid_links:
                url, is_channel = parse_youtube_url(link)
                
                if is_channel:
                    # Для канала получаем видео
                    channel_videos = youtube_analyzer.get_last_videos_from_channel(url, limit=10)  # Получаем больше видео для выбора
                    if channel_videos:
                        # Добавляем канал и его видео
                        all_channel_videos.append({
                            "channel_url": url,
                            "videos": channel_videos
                        })
                else:
                    # Для прямой ссылки на видео добавляем в список для просмотра
                    videos_to_watch.append(url)
            
            # Выбираем видео в зависимости от стратегии
            if distribution == "Равномерно по всем каналам" and all_channel_videos:
                # Вычисляем, сколько видео нужно взять с каждого канала
                videos_per_channel = total_videos // len(all_channel_videos)
                remaining_videos = total_videos - (videos_per_channel * len(all_channel_videos))
                
                status_text.text(f"Равномерный просмотр: по {videos_per_channel} видео с каждого канала ({len(all_channel_videos)} каналов)")
                
                # Берем одинаковое количество видео с каждого канала
                for channel_data in all_channel_videos:
                    channel_videos = channel_data["videos"]
                    # Берем не более videos_per_channel видео с этого канала
                    for i, video in enumerate(channel_videos):
                        if i < videos_per_channel:
                            videos_to_watch.append(video.get("url"))
                    
                    # Если остались "лишние" видео, распределяем их по одному на канал
                    if remaining_videos > 0:
                        for i, channel_data in enumerate(all_channel_videos):
                            if i >= remaining_videos:
                                break
                            # Берем еще одно видео с канала, если оно есть
                            channel_videos = channel_data["videos"]
                            if len(channel_videos) > videos_per_channel:
                                videos_to_watch.append(channel_videos[videos_per_channel].get("url"))
            else:  # "Только самые свежие видео"
                # Собираем все видео в один список
                all_videos = []
                for channel_data in all_channel_videos:
                    all_videos.extend(channel_data["videos"])
                
                # Берем total_videos самых свежих видео
                for i, video in enumerate(all_videos):
                    if i < total_videos:
                        videos_to_watch.append(video.get("url"))
            
            # Если есть видео для просмотра, выполняем предварительный просмотр
            if videos_to_watch:
                status_text.text(f"Выполняется предварительный просмотр {len(videos_to_watch)} видео...")
                
                # Очищаем список от None и дубликатов
                videos_to_watch = [url for url in videos_to_watch if url]
                videos_to_watch = list(dict.fromkeys(videos_to_watch))  # Удаляем дубликаты, сохраняя порядок
                
                # Вызываем улучшенную функцию предварительного просмотра с настройками
                youtube_analyzer.prewatch_videos(
                    videos_to_watch[:total_videos],  # Ограничиваем количество видео
                    min_watch_time=min_watch_time,
                    max_watch_time=max_watch_time,
                    like_probability=like_probability,
                    watch_percentage=watch_percentage
                )
                status_text.text("Предварительный просмотр завершен. Начинаем сбор рекомендаций...")
            else:
                status_text.warning("Не удалось найти видео для предварительного просмотра")
        
        status_text.text(f"Начинаем обработку {len(valid_links)} ссылок...")
        
        for i, link in enumerate(valid_links):
            # Обновляем прогресс
            progress_value = float(i) / len(valid_links)
            progress_bar.progress(progress_value)
            status_text.text(f"Обрабатываем ссылку {i+1} из {len(valid_links)}: {link}")
            
            # Проверяем тип ссылки (канал или видео)
            url, is_channel = parse_youtube_url(link)
            
            if is_channel:
                # Для канала получаем последние видео (используем channel_videos_limit)
                status_text.text(f"Получение последних видео с канала: {url}")
                channel_videos = youtube_analyzer.get_last_videos_from_channel(url, limit=channel_videos_limit)
                
                if not channel_videos:
                    status_text.warning(f"Не удалось получить видео с канала {url}")
                    continue
                
                # Обрабатываем каждое видео с канала
                for video_info in channel_videos:
                    video_url = video_info.get("url")
                    if not video_url:
                        continue
                    
                    # Получаем детали видео
                    status_text.text(f"Получение деталей видео: {video_url}")
                    video_data = youtube_analyzer.get_video_details(video_url)
                    
                    if video_data:
                        video_data["source"] = f"Канал: {link}"
                        results.append(video_data)
                    
                    # Получаем рекомендации для этого видео (используем recommendations_per_video)
                    status_text.text(f"Получение рекомендаций для видео: {video_url}")
                    recommendations = youtube_analyzer.get_recommended_videos(video_url, limit=recommendations_per_video)
                    
                    for rec_info in recommendations:
                        rec_url = rec_info.get("url")
                        if not rec_url:
                            continue
                        
                        # Получаем детали рекомендованного видео
                        rec_data = youtube_analyzer.get_video_details(rec_url)
                        
                        if rec_data:
                            rec_data["source"] = f"Рекомендация для: {video_url}"
                            results.append(rec_data)
            else:
                # Для прямой ссылки на видео
                status_text.text(f"Получение деталей видео: {url}")
                video_data = youtube_analyzer.get_video_details(url)
                
                if video_data:
                    video_data["source"] = f"Прямая ссылка: {link}"
                    results.append(video_data)
                
                # Получаем рекомендации (используем recommendations_per_video)
                status_text.text(f"Получение рекомендаций для видео: {url}")
                recommendations = youtube_analyzer.get_recommended_videos(url, limit=recommendations_per_video)
                
                for rec_info in recommendations:
                    rec_url = rec_info.get("url")
                    if not rec_url:
                        continue
                    
                    # Получаем детали рекомендованного видео
                    rec_data = youtube_analyzer.get_video_details(rec_url)
                    
                    if rec_data:
                        rec_data["source"] = f"Рекомендация для: {url}"
                        results.append(rec_data)
            
        # Завершаем прогресс
        progress_bar.progress(1.0)
        status_text.text("Обработка завершена!")
        
    except Exception as e:
        status_text.error(f"Произошла ошибка: {e}")
        logger.error(f"Ошибка при тестировании рекомендаций: {e}")
        traceback.print_exc()
    finally:
        # Закрываем драйвер
        if youtube_analyzer:
            youtube_analyzer.quit_driver()
    
    # Создаем датафрейм из результатов
    if results:
        # Формируем датафрейм с нужными колонками
        df = pd.DataFrame(results)
        
        # Выбираем и переименовываем нужные колонки
        columns_to_show = {
            "url": "Ссылка на видео",
            "title": "Заголовок видео",
            "publication_date": "Дата публикации",
            "views": "Количество просмотров",
            "source": "Источник видео"
        }
        
        # Фильтруем только существующие колонки
        existing_columns = {k: v for k, v in columns_to_show.items() if k in df.columns}
        
        if existing_columns:
            df = df[list(existing_columns.keys())]
            df = df.rename(columns=existing_columns)
            return df
        else:
            return pd.DataFrame()
    else:
        return pd.DataFrame()

def main():
    # Настройка логгера
    setup_logging()
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
    tab1, tab2, tab3 = st.tabs(["Получение рекомендаций", "Релевантность", "Результаты"])
    
    with tab1:
        # Стадия 1: Авторизация Google и настройка предварительного просмотра
        st.header("Стадия 1: Авторизация и предварительное обучение")
        
        # Настройки аккаунта Google
        with st.expander("Авторизация Google", expanded=True):
            use_google_account = st.checkbox("Авторизоваться в аккаунте Google", value=False)
            google_account = None
            
            if use_google_account:
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
                
                # Отдельная кнопка для авторизации
                auth_col1, auth_col2 = st.columns([1, 2])
                with auth_col1:
                    auth_button = st.button("🔑 Авторизоваться в Google")
                
                with auth_col2:
                    auth_status = st.empty()
                    if st.session_state.get("is_logged_in", False):
                        auth_status.success(f"✅ Вы авторизованы как {st.session_state.get('google_account', {}).get('email', '')}")

                if auth_button:
                    with st.spinner("Выполняется авторизация в Google..."):
                        # Создаем анализатор YouTube только для авторизации
                        auth_analyzer = YouTubeAnalyzer(
                            headless=False,  # Используем видимый режим для удобства пользователя
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
                                auth_status.success(f"✅ Авторизация в Google успешно выполнена! ({email})")
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
                st.info("Введите email и пароль от аккаунта Google для авторизации")
                
            # Информация для пользователя
            st.info("""
            ⚠️ Обратите внимание:
            - При первом входе может потребоваться дополнительное подтверждение
            - Если включена двухфакторная аутентификация, вам потребуется ввести код подтверждения
            - Данные аккаунта хранятся только в памяти сессии и не сохраняются
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
                                        prewatch_status.info(f"⏳ Запуск браузера в видимом режиме для просмотра {len(valid_links[:total_videos])} видео...")
                                        
                                        # Принудительно устанавливаем видимый режим
                                        existing_analyzer.headless = False
                                        
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
                        existing_analyzer=existing_analyzer  # Передаем существующий драйвер, если есть
                    )
                    
                    if not results_df.empty:
                        st.session_state["results_df"] = results_df
                        st.success(f"Собрано {len(results_df)} результатов.")
                        st.dataframe(results_df)
                        
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
                    st.dataframe(df)
                    
                    # Автоматический переход на вкладку с результатами
                    st.info("Перейдите на вкладку 'Результаты' для просмотра и экспорта.")
                else:
                    st.warning("Не найдено результатов, соответствующих критериям фильтрации.")
            else:
                st.error("Сначала выполните сбор рекомендаций на первой вкладке.")
    
    with tab3:
        # Отображение результатов
        st.header("Результаты анализа")
        
        if ("filtered_df" in st.session_state and not st.session_state["filtered_df"].empty) or \
           ("results_df" in st.session_state and not st.session_state["results_df"].empty):
            
            # Используем отфильтрованные результаты, если они есть, иначе - все результаты
            if "filtered_df" in st.session_state and not st.session_state["filtered_df"].empty:
                display_df = st.session_state["filtered_df"]
                st.success(f"Отображаются отфильтрованные результаты: {len(display_df)} видео.")
            else:
                display_df = st.session_state["results_df"]
                st.success(f"Отображаются все результаты: {len(display_df)} видео.")
            
            # Выбор формата отображения
            display_format = st.radio(
                "Формат отображения:",
                options=["Таблица", "JSON", "Карточки"],
                index=0
            )
            
            if display_format == "Таблица":
                st.dataframe(display_df)
            elif display_format == "JSON":
                st.json(display_df.to_dict(orient="records"))
            else:  # Карточки
                # Отображаем результаты в виде карточек
                for i, row in display_df.iterrows():
                    with st.expander(f"{row['Заголовок видео'] if 'Заголовок видео' in row else 'Видео ' + str(i+1)}", expanded=False):
                        col1, col2 = st.columns([1, 2])
                        
                        with col1:
                            # Если есть миниатюра, отображаем ее
                            if "thumbnail" in row:
                                st.image(row["thumbnail"], use_column_width=True)
                            
                        with col2:
                            # Выводим детали видео
                            st.write(f"**Ссылка:** [{row['Ссылка на видео'] if 'Ссылка на видео' in row else ''}]({row['Ссылка на видео'] if 'Ссылка на видео' in row else ''})")
                            
                            if "Дата публикации" in row:
                                st.write(f"**Дата публикации:** {row['Дата публикации']}")
                            
                            if "Количество просмотров" in row:
                                st.write(f"**Просмотры:** {row['Количество просмотров']}")
                            
                            if "Источник видео" in row:
                                st.write(f"**Источник:** {row['Источник видео']}")
            
            # Экспорт результатов
            st.subheader("Экспорт результатов")
            
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("Скачать CSV"):
                    csv = display_df.to_csv(index=False)
                    
                    # Кодируем CSV в base64
                    b64 = base64.b64encode(csv.encode()).decode()
                    
                    # Формируем ссылку для скачивания
                    href = f'<a href="data:file/csv;base64,{b64}" download="youtube_results.csv">Скачать CSV файл</a>'
                    st.markdown(href, unsafe_allow_html=True)
            
            with col2:
                if st.button("Скачать JSON"):
                    json_data = display_df.to_json(orient="records", force_ascii=False)
                    
                    # Кодируем JSON в base64
                    b64 = base64.b64encode(json_data.encode("utf-8")).decode()
                    
                    # Формируем ссылку для скачивания
                    href = f'<a href="data:file/json;base64,{b64}" download="youtube_results.json">Скачать JSON файл</a>'
                    st.markdown(href, unsafe_allow_html=True)
        else:
            st.warning("Нет данных для отображения. Пожалуйста, соберите рекомендации на первой вкладке.")

# Добавляем функцию для создания HTML файла с ручным просмотром
def create_manual_viewing_html(video_urls: List[str], min_watch_time: int = 15, max_watch_time: int = 45) -> str:
    """
    Создает HTML файл для ручного просмотра видео YouTube.
    
    Args:
        video_urls: Список URL видео для просмотра
        min_watch_time: Минимальное время просмотра каждого видео в секундах
        max_watch_time: Максимальное время просмотра каждого видео в секундах
        
    Returns:
        str: HTML содержимое файла
    """
    # Очистка и валидация ссылок
    valid_urls = []
    for url in video_urls:
        url = url.strip()
        # Проверяем, является ли это ссылкой на видео
        if "youtube.com/watch" in url or "youtu.be/" in url:
            valid_urls.append(url)
            logger.info(f"Добавлена прямая ссылка на видео: {url}")
        # Если это канал, пытаемся получить видео с него
        elif "youtube.com/channel/" in url or "youtube.com/c/" in url or "youtube.com/user/" in url or "youtube.com/@" in url:
            # Сначала преобразуем ссылку на канал в ссылку на страницу видео канала
            channel_videos_url = url
            if not channel_videos_url.endswith("/videos"):
                channel_videos_url = channel_videos_url.rstrip("/") + "/videos"
            
            # Добавляем ссылку на страницу видео канала
            valid_urls.append(channel_videos_url)
            logger.info(f"Добавлена ссылка на страницу видео канала: {channel_videos_url}")
            
            try:
                # Создаем временный анализатор YouTube без авторизации
                temp_analyzer = YouTubeAnalyzer(headless=True, use_proxy=False)
                try:
                    # Получаем последние 5 видео с канала
                    channel_videos = temp_analyzer.get_last_videos_from_channel(url, limit=5)
                    
                    if channel_videos:
                        for video in channel_videos:
                            if isinstance(video, dict) and 'url' in video:
                                valid_urls.append(video['url'])
                                logger.info(f"Добавлено видео с канала: {video['url']}")
                            elif isinstance(video, str):
                                valid_urls.append(video)
                                logger.info(f"Добавлено видео с канала: {video}")
                        
                        # Логируем информацию
                        logger.info(f"Получено {len(channel_videos)} видео с канала {url}")
                finally:
                    # Закрываем драйвер
                    if temp_analyzer and hasattr(temp_analyzer, 'driver') and temp_analyzer.driver:
                        temp_analyzer.quit_driver()
            except Exception as e:
                logger.error(f"Ошибка при получении видео с канала {url}: {str(e)}")
        else:
            logger.warning(f"Пропущена некорректная ссылка: {url} - не распознана как видео или канал YouTube")
    
    # Удаляем дубликаты
    valid_urls = list(dict.fromkeys(valid_urls))
    
    # Проверка на наличие валидных ссылок
    if not valid_urls:
        # Возвращаем HTML с предупреждением, если нет ссылок
        return """
        <!DOCTYPE html>
        <html lang="ru">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Ошибка - Нет валидных видео</title>
            <style>
                body { font-family: Arial; background: #f0f0f0; padding: 20px; }
                .container { max-width: 800px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0, 0, 0, 0.1); }
                h1 { color: #cc0000; text-align: center; }
                .error { background-color: #fff3cd; color: #856404; padding: 15px; border-radius: 5px; margin: 20px 0; border-left: 5px solid #ffeeba; }
                .info { background-color: #d1ecf1; color: #0c5460; padding: 15px; border-radius: 5px; margin: 20px 0; border-left: 5px solid #bee5eb; }
                .manual-step { background-color: #e8f5e9; color: #1b5e20; padding: 15px; border-radius: 5px; margin: 20px 0; border-left: 5px solid #a5d6a7; }
                .input-section { background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin-top: 20px; }
                textarea { width: 100%; height: 100px; padding: 10px; margin-bottom: 10px; border: 1px solid #ddd; border-radius: 4px; }
                button { background-color: #cc0000; color: white; border: none; padding: 10px 15px; border-radius: 4px; cursor: pointer; font-weight: bold; }
                button:hover { background-color: #aa0000; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Ошибка: Нет валидных видео</h1>
                <div class="error">
                    <strong>Не найдено видео для просмотра.</strong> Пожалуйста, добавьте корректные ссылки на видео YouTube.
                </div>
                <div class="info">
                    <p><strong>Допустимые форматы ссылок:</strong></p>
                    <ul>
                        <li>Прямые ссылки на видео: https://www.youtube.com/watch?v=XXXXXXXXXXX</li>
                        <li>Короткие ссылки: https://youtu.be/XXXXXXXXXXX</li>
                    </ul>
                    <p>Из-за ограничений YouTube API, автоматическое получение видео с каналов недоступно. 
                    Пожалуйста, используйте прямые ссылки на конкретные видео.</p>
                </div>
                
                <div class="manual-step">
                    <h3>Как найти ссылки на видео вручную:</h3>
                    <ol>
                        <li>Откройте YouTube и найдите интересующий вас канал или видео</li>
                        <li>Для канала: перейдите во вкладку "Видео"</li>
                        <li>Нажмите на видео, которое хотите добавить</li>
                        <li>Скопируйте URL из адресной строки браузера</li>
                        <li>Вставьте скопированные ссылки в текстовое поле ниже (по одной ссылке на строку)</li>
                    </ol>
                </div>
                
                <div class="input-section">
                    <h3>Добавьте ссылки на YouTube видео:</h3>
                    <form id="videoForm">
                        <textarea id="videoUrls" placeholder="Вставьте ссылки на YouTube видео (по одной ссылке на строку)"></textarea>
                        <button type="button" onclick="createWatchPage()">Создать страницу просмотра</button>
                    </form>
                </div>
            </div>
            
            <script>
                function createWatchPage() {
                    const urlsText = document.getElementById('videoUrls').value;
                    const urlsList = urlsText.split('\\n').filter(url => url.trim() !== '');
                    
                    if (urlsList.length === 0) {
                        alert('Пожалуйста, добавьте хотя бы одну ссылку на видео YouTube');
                        return;
                    }
                    
                    // Проверяем форматы ссылок
                    const validUrls = urlsList.filter(url => 
                        url.includes('youtube.com/watch') || 
                        url.includes('youtu.be/')
                    );
                    
                    if (validUrls.length === 0) {
                        alert('Не найдено валидных ссылок на видео YouTube. Пожалуйста, проверьте формат ссылок.');
                        return;
                    }
                    
                    // Создаем массив с данными о видео
                    const videos = validUrls.map(url => {
                        const watchTime = Math.floor(Math.random() * (45 - 15 + 1)) + 15;
                        return { url, watchTime };
                    });
                    
                    // Создаем HTML для списка видео
                    let videosListHtml = '';
                    videos.forEach((video, i) => {
                        videosListHtml += `
                        <tr id="video-row-${i}" class="video-row">
                            <td>${i+1}</td>
                            <td><a href="${video.url}" target="_blank">${video.url}</a></td>
                            <td>${video.watchTime} сек</td>
                            <td class="status">Ожидает</td>
                        </tr>
                        `;
                    });
                    
                    // Создаем HTML страницу для просмотра
                    const htmlContent = `
                    <!DOCTYPE html>
                    <html lang="ru">
                    <head>
                        <meta charset="UTF-8">
                        <meta name="viewport" content="width=device-width, initial-scale=1.0">
                        <title>Просмотр видео YouTube для обучения</title>
                        <style>
                            body {
                                font-family: Arial, sans-serif;
                                line-height: 1.6;
                                margin: 0;
                                padding: 20px;
                                background-color: #f0f0f0;
                            }
                            
                            .container {
                                max-width: 1000px;
                                margin: 0 auto;
                                background: white;
                                padding: 20px;
                                border-radius: 8px;
                                box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
                            }
                            
                            h1 {
                                color: #cc0000;
                                text-align: center;
                            }
                            
                            .warning {
                                background-color: #fff3cd;
                                color: #856404;
                                padding: 10px;
                                border-radius: 5px;
                                margin-bottom: 20px;
                                border-left: 5px solid #ffeeba;
                            }
                            
                            .info {
                                background-color: #d1ecf1;
                                color: #0c5460;
                                padding: 10px;
                                border-radius: 5px;
                                margin-bottom: 20px;
                                border-left: 5px solid #bee5eb;
                            }
                            
                            .player-wrapper {
                                display: flex;
                                flex-direction: column;
                                margin-bottom: 20px;
                                background: #000;
                                padding: 10px;
                                border-radius: 5px;
                            }
                            
                            #player {
                                width: 100%;
                                height: 500px;
                                margin-bottom: 10px;
                            }
                            
                            .controls {
                                display: flex;
                                justify-content: space-between;
                                align-items: center;
                                background: #333;
                                color: white;
                                padding: 10px;
                                border-radius: 5px;
                            }
                            
                            .progress {
                                flex-grow: 1;
                                margin: 0 15px;
                                height: 20px;
                                background: #444;
                                border-radius: 10px;
                                overflow: hidden;
                                position: relative;
                            }
                            
                            .progress-bar {
                                height: 100%;
                                width: 0;
                                background: #cc0000;
                                transition: width 0.5s;
                            }
                            
                            .time-display {
                                font-family: monospace;
                                font-size: 16px;
                                margin-right: 10px;
                            }
                            
                            button {
                                background-color: #cc0000;
                                color: white;
                                border: none;
                                padding: 10px 15px;
                                cursor: pointer;
                                border-radius: 4px;
                                font-weight: bold;
                            }
                            
                            button:hover {
                                background-color: #aa0000;
                            }
                            
                            button:disabled {
                                background-color: #cccccc;
                                cursor: not-allowed;
                            }
                            
                            table {
                                width: 100%;
                                border-collapse: collapse;
                                margin-top: 20px;
                            }
                            
                            th, td {
                                padding: 12px;
                                text-align: left;
                                border-bottom: 1px solid #ddd;
                            }
                            
                            th {
                                background-color: #f2f2f2;
                                font-weight: bold;
                            }
                            
                            tr.completed {
                                background-color: #e8f5e9;
                            }
                            
                            tr.playing {
                                background-color: #fff8e1;
                            }
                            
                            td.status {
                                font-weight: bold;
                            }
                            
                            .status-playing {
                                color: #ff9800;
                            }
                            
                            .status-completed {
                                color: #4caf50;
                            }
                            
                            .video-info {
                                background: #f5f5f5;
                                padding: 10px;
                                border-radius: 5px;
                                margin-top: 10px;
                                font-weight: bold;
                            }
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <h1>Просмотр видео YouTube</h1>
                            
                            <div class="warning">
                                <strong>Важно:</strong> Перед началом просмотра убедитесь, что вы авторизованы в YouTube в текущем браузере.
                                Не закрывайте эту страницу до завершения просмотра всех видео.
                            </div>
                            
                            <div class="info">
                                <p><strong>Этот инструмент поможет вам:</strong></p>
                                <ul>
                                    <li>Автоматически просмотреть список видео YouTube</li>
                                    <li>Добавить видео в историю просмотров вашего аккаунта</li>
                                    <li>Улучшить рекомендации YouTube на основе ваших просмотров</li>
                                </ul>
                            </div>
                            
                            <div class="player-wrapper">
                                <div id="player"></div>
                                <div class="controls">
                                    <button id="startButton">▶️ Начать просмотр</button>
                                    <div class="progress">
                                        <div class="progress-bar" id="progressBar"></div>
                                    </div>
                                    <div class="time-display" id="timeDisplay">00:00 / 00:00</div>
                                    <button id="skipButton" disabled>⏩ Пропустить</button>
                                </div>
                            </div>
                            
                            <div class="video-info" id="videoInfo">
                                Нажмите кнопку "Начать просмотр" для просмотра ${videos.length} видео
                            </div>
                            
                            <table>
                                <thead>
                                    <tr>
                                        <th>№</th>
                                        <th>Ссылка на видео</th>
                                        <th>Время просмотра</th>
                                        <th>Статус</th>
                                    </tr>
                                </thead>
                                <tbody id="videosTable">
                                    ${videosListHtml}
                                </tbody>
                            </table>
                        </div>
                        
                        <script>
                            // Загружаем YouTube API
                            var tag = document.createElement('script');
                            tag.src = "https://www.youtube.com/iframe_api";
                            var firstScriptTag = document.getElementsByTagName('script')[0];
                            firstScriptTag.parentNode.insertBefore(tag, firstScriptTag);
                            
                            // Данные о видео
                            const videos = [
                                {videos_json}
                            ];
                            
                            // Проверка наличия видео
                            if (videos.length === 0) {{
                                document.getElementById('videoInfo').textContent = "Не найдено видео для просмотра";
                                document.getElementById('startButton').disabled = true;
                                alert("Не найдено ни одного видео для просмотра. Добавьте корректные YouTube-ссылки.");
                            }}
                            
                            // Получение элементов
                            const startButton = document.getElementById('startButton');
                            const skipButton = document.getElementById('skipButton');
                            const progressBar = document.getElementById('progressBar');
                            const timeDisplay = document.getElementById('timeDisplay');
                            const videoInfo = document.getElementById('videoInfo');
                            const videosTable = document.getElementById('videosTable');
                            
                            // Переменные состояния
                            let currentVideoIndex = 0;
                            let watching = false;
                            let timer = null;
                            let secondsWatched = 0;
                            let totalWatched = 0;
                            let player;
                            
                            // Получение ID видео из URL YouTube
                            function getYouTubeVideoId(url) {{
                                const regExp = /^.*((youtu.be\\/)|(v\\/)|(\\/u\\/\\w\\/)|(embed\\/)|(watch\\?))\\??v?=?([^#&?]*).*/;
                                const match = url.match(regExp);
                                return (match && match[7].length === 11) ? match[7] : false;
                            }}
                            
                            // Инициализация YouTube плеера
                            function onYouTubeIframeAPIReady() {{
                                player = new YT.Player('player', {{
                                    height: '500',
                                    width: '100%',
                                    videoId: '',
                                    playerVars: {{
                                        'autoplay': 0,
                                        'controls': 1,
                                        'showinfo': 1,
                                        'rel': 0,
                                        'fs': 1,
                                        'modestbranding': 1
                                    }},
                                    events: {{
                                        'onStateChange': onPlayerStateChange
                                    }}
                                }});
                            }}
                            
                            // Обработка состояний плеера
                            function onPlayerStateChange(event) {{
                                // Если видео закончилось само
                                if (event.data === YT.PlayerState.ENDED) {{
                                    // Ведем себя как при достижении времени просмотра
                                    clearInterval(timer);
                                    updateVideoStatus(currentVideoIndex, 'Завершено');
                                    currentVideoIndex++;
                                    setTimeout(playCurrentVideo, 1500);
                                }}
                            }}
                            
                            // Форматирование времени (секунды в MM:SS)
                            function formatTime(seconds) {{
                                const mins = Math.floor(seconds / 60);
                                const secs = Math.floor(seconds % 60);
                                return `${{String(mins).padStart(2, '0')}}:${{String(secs).padStart(2, '0')}}`;
                            }}
                            
                            // Обновление прогресса видео
                            function updateProgress() {{
                                const currentVideo = videos[currentVideoIndex];
                                const percent = (secondsWatched / currentVideo.watchTime) * 100;
                                progressBar.style.width = `${{percent}}%`;
                                
                                timeDisplay.textContent = `${{formatTime(secondsWatched)}} / ${{formatTime(currentVideo.watchTime)}}`;
                            }}
                            
                            // Обновление статуса видео в таблице
                            function updateVideoStatus(index, status) {{
                                const row = document.getElementById(`video-row-${{index}}`);
                                const statusCell = row.querySelector('.status');
                                
                                if (status === 'Просмотр') {{
                                    row.className = 'video-row playing';
                                    statusCell.className = 'status status-playing';
                                    statusCell.textContent = 'Просмотр';
                                }} else if (status === 'Завершено') {{
                                    row.className = 'video-row completed';
                                    statusCell.className = 'status status-completed';
                                    statusCell.textContent = 'Завершено';
                                    totalWatched++;
                                }}
                            }}
                            
                            // Загрузка и воспроизведение текущего видео
                            function playCurrentVideo() {{
                                // Проверка на завершение всех видео
                                if (currentVideoIndex >= videos.length) {{
                                    stopWatching();
                                    videoInfo.textContent = `Просмотр завершен! Просмотрено ${{totalWatched}} из ${{videos.length}} видео.`;
                                    alert('Просмотр всех видео завершен!');
                                    return;
                                }}
                                
                                const currentVideo = videos[currentVideoIndex];
                                const videoId = getYouTubeVideoId(currentVideo.url);
                                
                                if (!videoId) {{
                                    console.error('Не удалось получить ID видео для:', currentVideo.url);
                                    currentVideoIndex++;
                                    playCurrentVideo();
                                    return;
                                }}
                                
                                // Обновляем информацию
                                videoInfo.textContent = `Просмотр видео ${{currentVideoIndex + 1}} из ${{videos.length}}: ${{currentVideo.url}}`;
                                
                                // Обновляем статус
                                updateVideoStatus(currentVideoIndex, 'Просмотр');
                                
                                // Сбрасываем счетчик
                                secondsWatched = 0;
                                updateProgress();
                                
                                // Загружаем и запускаем видео с помощью API
                                if (player && player.loadVideoById) {{
                                    // Загружаем видео и запускаем его
                                    player.loadVideoById({{
                                        'videoId': videoId,
                                        'startSeconds': 0,
                                        'suggestedQuality': 'large'
                                    }});
                                    player.playVideo();
                                    
                                    // Устанавливаем громкость на среднее значение
                                    setTimeout(function() {{
                                        player.setVolume(50);
                                        // Дополнительно пробуем запустить воспроизведение через 1 секунду
                                        player.playVideo();
                                    }}, 1000);
                                }}
                                
                                // Запускаем таймер
                                if (timer) {{
                                    clearInterval(timer);
                                }}
                                
                                timer = setInterval(() => {{
                                    secondsWatched++;
                                    updateProgress();
                                    
                                    // Если достигнуто нужное время просмотра
                                    if (secondsWatched >= currentVideo.watchTime) {{
                                        // Отмечаем как просмотренное
                                        updateVideoStatus(currentVideoIndex, 'Завершено');
                                        
                                        // Переходим к следующему
                                        currentVideoIndex++;
                                        
                                        // Останавливаем таймер
                                        clearInterval(timer);
                                        
                                        // Небольшая пауза перед следующим видео
                                        setTimeout(playCurrentVideo, 1500);
                                    }}
                                }}, 1000);
                                
                                // Открываем видео в новой вкладке для надежности
                                if (secondsWatched === 0) {{
                                    // При первом запуске просмотра для каждого видео открываем его в новой вкладке
                                    // для гарантированного добавления в историю просмотров
                                    const newTab = window.open(currentVideo.url, '_blank');
                                    
                                    // Показываем инструкцию пользователю
                                    videoInfo.innerHTML = '<div class="warning">' +
                                        '<strong style="color: #ff9800;">⚠️ Внимание!</strong> Открыта новая вкладка с видео ' + (currentVideoIndex + 1) + '/' + videos.length + '.<br>' +
                                        'Пожалуйста, перейдите в открытую вкладку и запустите воспроизведение кликом.<br>' +
                                        'Эта вкладка не закроется автоматически. Закройте её вручную после начала воспроизведения.<br>' +
                                        '<span style="color: #4caf50;">✓ Видео будет считаться просмотренным в любом случае через ' + currentVideo.watchTime + ' секунд.</span>' +
                                        '</div>';
                                    
                                    // Не закрываем вкладку автоматически, поскольку это может помешать воспроизведению
                                    // Пользователь должен будет сам закрыть вкладку после начала воспроизведения
                                }}
                                
                                // Включаем кнопку пропуска
                                skipButton.disabled = false;
                            }}
                            
                            // Остановка просмотра
                            function stopWatching() {{
                                if (timer) {{
                                    clearInterval(timer);
                                    timer = null;
                                }}
                                
                                if (player && player.pauseVideo) {{
                                    player.pauseVideo();
                                }}
                                
                                watching = false;
                                startButton.textContent = '▶️ Продолжить просмотр';
                                skipButton.disabled = true;
                            }}
                            
                            // Обработчики событий
                            startButton.addEventListener('click', () => {{
                                if (watching) {{
                                    stopWatching();
                                }} else {{
                                    watching = true;
                                    startButton.textContent = '⏸️ Пауза';
                                    playCurrentVideo();
                                }}
                            }});
                            
                            skipButton.addEventListener('click', () => {{
                                if (watching) {{
                                    clearInterval(timer);
                                    
                                    // Отмечаем текущее видео как просмотренное
                                    updateVideoStatus(currentVideoIndex, 'Завершено');
                                    
                                    // Переходим к следующему
                                    currentVideoIndex++;
                                    
                                    // Воспроизводим следующее
                                    playCurrentVideo();
                                }}
                            }});
                            
                            // Предупреждение при попытке закрыть страницу
                            window.addEventListener('beforeunload', (e) => {{
                                if (watching) {{
                                    e.preventDefault();
                                    e.returnValue = 'Просмотр видео не завершен. Закрытие страницы прервет процесс просмотра.';
                                    return e.returnValue;
                                }}
                            }});
                        </script>
                    </body>
                    </html>
                    `;
                    
                    // Создаем и скачиваем файл
                    const blob = new Blob([htmlContent], { type: 'text/html' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'youtube_videos_to_watch.html';
                    a.click();
                    URL.revokeObjectURL(url);
                }
            </script>
        </body>
        </html>
        """
    
    # Генерируем случайное время просмотра для каждого видео
    watch_times = []
    for _ in range(len(valid_urls)):
        watch_time = random.randint(min_watch_time, max_watch_time)
        watch_times.append(watch_time)
    
    # Создаем HTML с упрощенным интерфейсом
    videos_list_html = ""
    for i, (url, time) in enumerate(zip(valid_urls, watch_times)):
        videos_list_html += f"""
        <tr id="video-row-{i}" class="video-row">
            <td>{i+1}</td>
            <td><a href="{url}" target="_blank">{url}</a></td>
            <td>{time} сек</td>
            <td class="status">Ожидает</td>
        </tr>
        """
    
    # Подготавливаем JavaScript массив данных о видео
    videos_json_items = []
    for url, time in zip(valid_urls, watch_times):
        # Заменяем двойные кавычки на экранированные
        safe_url = url.replace('"', '\\"')
        videos_json_items.append(f'{{ url: "{safe_url}", watchTime: {time} }}')
    
    videos_json = ",\n                ".join(videos_json_items)
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Просмотр видео YouTube для обучения</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                line-height: 1.6;
                margin: 0;
                padding: 20px;
                background-color: #f0f0f0;
            }}
            
            .container {{
                max-width: 1000px;
                margin: 0 auto;
                background: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
            }}
            
            h1 {{
                color: #cc0000;
                text-align: center;
            }}
            
            .warning {{
                background-color: #fff3cd;
                color: #856404;
                padding: 10px;
                border-radius: 5px;
                margin-bottom: 20px;
                border-left: 5px solid #ffeeba;
            }}
            
            .info {{
                background-color: #d1ecf1;
                color: #0c5460;
                padding: 10px;
                border-radius: 5px;
                margin-bottom: 20px;
                border-left: 5px solid #bee5eb;
            }}
            
            .success {{
                background-color: #d4edda;
                color: #155724;
                padding: 10px;
                border-radius: 5px;
                margin-bottom: 20px;
                border-left: 5px solid #c3e6cb;
            }}
            
            .manual-mode {{
                background-color: #ffe0b2;
                color: #e65100;
                padding: 15px;
                border-radius: 5px;
                margin: 20px 0;
                border-left: 5px solid #ffb74d;
            }}
            
            .player-wrapper {{
                display: flex;
                flex-direction: column;
                margin-bottom: 20px;
                background: #000;
                padding: 10px;
                border-radius: 5px;
            }}
            
            #player {{
                width: 100%;
                height: 500px;
                margin-bottom: 10px;
            }}
            
            .controls {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                background: #333;
                color: white;
                padding: 10px;
                border-radius: 5px;
            }}
            
            .progress {{
                flex-grow: 1;
                margin: 0 15px;
                height: 20px;
                background: #444;
                border-radius: 10px;
                overflow: hidden;
                position: relative;
            }}
            
            .progress-bar {{
                height: 100%;
                width: 0;
                background: #cc0000;
                transition: width 0.5s;
            }}
            
            .time-display {{
                font-family: monospace;
                font-size: 16px;
                margin-right: 10px;
            }}
            
            button {{
                background-color: #cc0000;
                color: white;
                border: none;
                padding: 10px 15px;
                cursor: pointer;
                border-radius: 4px;
                font-weight: bold;
            }}
            
            button:hover {{
                background-color: #aa0000;
            }}
            
            button:disabled {{
                background-color: #cccccc;
                cursor: not-allowed;
            }}
            
            .button-alt {{
                background-color: #4CAF50;
                margin-left: 10px;
            }}
            
            .button-alt:hover {{
                background-color: #388E3C;
            }}
            
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }}
            
            th, td {{
                padding: 12px;
                text-align: left;
                border-bottom: 1px solid #ddd;
            }}
            
            th {{
                background-color: #f2f2f2;
                font-weight: bold;
            }}
            
            tr.completed {{
                background-color: #e8f5e9;
            }}
            
            tr.playing {{
                background-color: #fff8e1;
            }}
            
            td.status {{
                font-weight: bold;
            }}
            
            .status-playing {{
                color: #ff9800;
            }}
            
            .status-completed {{
                color: #4caf50;
            }}
            
            .video-info {{
                background: #f5f5f5;
                padding: 10px;
                border-radius: 5px;
                margin-top: 10px;
                font-weight: bold;
            }}
            
            .action-cell {{
                text-align: center;
            }}
            
            .open-button {{
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 5px 10px;
                border-radius: 3px;
                cursor: pointer;
                font-size: 12px;
            }}
            
            .open-button:hover {{
                background-color: #0b7dda;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Просмотр видео YouTube</h1>
            
            <div class="warning">
                <strong>Важно:</strong> Перед началом просмотра убедитесь, что вы авторизованы в YouTube в текущем браузере.
                Не закрывайте эту страницу до завершения просмотра всех видео.
            </div>
            
            <div class="info">
                <p><strong>Этот инструмент поможет вам:</strong></p>
                <ul>
                    <li>Автоматически просмотреть список видео YouTube</li>
                    <li>Добавить видео в историю просмотров вашего аккаунта</li>
                    <li>Улучшить рекомендации YouTube на основе ваших просмотров</li>
                </ul>
            </div>
            
            <div class="manual-mode">
                <h3>🔄 Инструкция по использованию:</h3>
                <ol>
                    <li>Нажмите кнопку "Начать просмотр" для запуска процесса</li>
                    <li>Для каждого видео будет открыта новая вкладка</li>
                    <li>Перейдите в открытую вкладку и вручную запустите воспроизведение видео</li>
                    <li>После начала воспроизведения, вы можете закрыть вкладку и вернуться на эту страницу</li>
                    <li>Процесс продолжится автоматически и перейдет к следующему видео через указанное время</li>
                    <li>Вы также можете нажать кнопку "Пропустить" чтобы сразу перейти к следующему видео</li>
                </ol>
                <p>⚠️ <strong>Примечание:</strong> Современные браузеры блокируют автоматическое воспроизведение, поэтому требуется ручной запуск каждого видео.</p>
            </div>
            
            <div class="player-wrapper">
                <div id="player"></div>
                <div class="controls">
                    <button id="startButton">▶️ Начать просмотр</button>
                    <div class="progress">
                        <div class="progress-bar" id="progressBar"></div>
                    </div>
                    <div class="time-display" id="timeDisplay">00:00 / 00:00</div>
                    <button id="skipButton" disabled>⏩ Пропустить</button>
                    <button id="manualButton" class="button-alt" disabled>🔗 Открыть текущее видео</button>
                </div>
            </div>
            
            <div class="video-info" id="videoInfo">
                Нажмите кнопку "Начать просмотр" для просмотра {len(valid_urls)} видео
            </div>
            
            <table>
                <thead>
                    <tr>
                        <th>№</th>
                        <th>Ссылка на видео</th>
                        <th>Время просмотра</th>
                        <th>Статус</th>
                        <th>Действие</th>
                    </tr>
                </thead>
                <tbody id="videosTable">
                    {videos_list_html.replace('</tr>', '<td class="action-cell"><button class="open-button" onclick="openVideoLink(this)">Открыть</button></td></tr>')}
                </tbody>
            </table>
        </div>
        
        <script>
            // Загружаем YouTube API
            var tag = document.createElement('script');
            tag.src = "https://www.youtube.com/iframe_api";
            var firstScriptTag = document.getElementsByTagName('script')[0];
            firstScriptTag.parentNode.insertBefore(tag, firstScriptTag);
            
            // Данные о видео
            const videos = [
                {videos_json}
            ];
            
            // Проверка наличия видео
            if (videos.length === 0) {{
                document.getElementById('videoInfo').textContent = "Не найдено видео для просмотра";
                document.getElementById('startButton').disabled = true;
                alert("Не найдено ни одного видео для просмотра. Добавьте корректные YouTube-ссылки.");
            }}
            
            // Получение элементов
            const startButton = document.getElementById('startButton');
            const skipButton = document.getElementById('skipButton');
            const manualButton = document.getElementById('manualButton');
            const progressBar = document.getElementById('progressBar');
            const timeDisplay = document.getElementById('timeDisplay');
            const videoInfo = document.getElementById('videoInfo');
            const videosTable = document.getElementById('videosTable');
            
            // Переменные состояния
            let currentVideoIndex = 0;
            let watching = false;
            let timer = null;
            let secondsWatched = 0;
            let totalWatched = 0;
            let player;
            
            // Открытие видео в новой вкладке из таблицы
            function openVideoLink(buttonElement) {{
                const row = buttonElement.closest('tr');
                const rowIndex = parseInt(row.id.replace('video-row-', ''));
                const video = videos[rowIndex];
                
                // Открываем видео в новой вкладке
                window.open(video.url, '_blank');
                
                // Отмечаем ячейку другим цветом чтобы показать, что ссылка была открыта
                buttonElement.style.backgroundColor = '#4CAF50';
                buttonElement.textContent = 'Открыто';
            }}
            
            // Получение ID видео из URL YouTube
            function getYouTubeVideoId(url) {{
                const regExp = /^.*((youtu.be\\/)|(v\\/)|(\\/u\\/\\w\\/)|(embed\\/)|(watch\\?))\\??v?=?([^#&?]*).*/;
                const match = url.match(regExp);
                return (match && match[7].length === 11) ? match[7] : false;
            }}
            
            // Инициализация YouTube плеера
            function onYouTubeIframeAPIReady() {{
                player = new YT.Player('player', {{
                    height: '500',
                    width: '100%',
                    videoId: '',
                    playerVars: {{
                        'autoplay': 0,
                        'controls': 1,
                        'showinfo': 1,
                        'rel': 0,
                        'fs': 1,
                        'modestbranding': 1
                    }},
                    events: {{
                        'onStateChange': onPlayerStateChange
                    }}
                }});
            }}
            
            // Обработка состояний плеера
            function onPlayerStateChange(event) {{
                // Если видео закончилось само
                if (event.data === YT.PlayerState.ENDED) {{
                    // Ведем себя как при достижении времени просмотра
                    clearInterval(timer);
                    updateVideoStatus(currentVideoIndex, 'Завершено');
                    currentVideoIndex++;
                    setTimeout(playCurrentVideo, 1500);
                }}
            }}
            
            // Форматирование времени (секунды в MM:SS)
            function formatTime(seconds) {{
                const mins = Math.floor(seconds / 60);
                const secs = Math.floor(seconds % 60);
                return `${{String(mins).padStart(2, '0')}}:${{String(secs).padStart(2, '0')}}`;
            }}
            
            // Обновление прогресса видео
            function updateProgress() {{
                if (currentVideoIndex >= videos.length) return;
                
                const currentVideo = videos[currentVideoIndex];
                const percent = (secondsWatched / currentVideo.watchTime) * 100;
                progressBar.style.width = `${{percent}}%`;
                
                timeDisplay.textContent = `${{formatTime(secondsWatched)}} / ${{formatTime(currentVideo.watchTime)}}`;
            }}
            
            // Обновление статуса видео в таблице
            function updateVideoStatus(index, status) {{
                const row = document.getElementById(`video-row-${{index}}`);
                if (!row) return;
                
                const statusCell = row.querySelector('.status');
                
                if (status === 'Просмотр') {{
                    row.className = 'video-row playing';
                    statusCell.className = 'status status-playing';
                    statusCell.textContent = 'Просмотр';
                }} else if (status === 'Завершено') {{
                    row.className = 'video-row completed';
                    statusCell.className = 'status status-completed';
                    statusCell.textContent = 'Завершено';
                    totalWatched++;
                }}
            }}
            
            // Загрузка и воспроизведение текущего видео
            function playCurrentVideo() {{
                // Проверка на завершение всех видео
                if (currentVideoIndex >= videos.length) {{
                    stopWatching();
                    videoInfo.innerHTML = `
                        <div class="success">
                            <strong>✅ Просмотр завершен!</strong> Просмотрено ${{totalWatched}} из ${{videos.length}} видео.<br>
                            Теперь все эти видео должны отображаться в вашей истории просмотров YouTube.
                        </div>
                    `;
                    alert('Просмотр всех видео завершен!');
                    return;
                }}
                
                const currentVideo = videos[currentVideoIndex];
                const videoId = getYouTubeVideoId(currentVideo.url);
                
                if (!videoId) {{
                    console.error('Не удалось получить ID видео для:', currentVideo.url);
                    currentVideoIndex++;
                    playCurrentVideo();
                    return;
                }}
                
                // Обновляем информацию
                videoInfo.innerHTML = `
                    <strong>Просмотр видео ${{currentVideoIndex + 1}} из ${{videos.length}}:</strong><br>
                    <a href="${{currentVideo.url}}" target="_blank">${{currentVideo.url}}</a><br>
                    <span style="color: #4caf50;">Нажмите на кнопку "Открыть текущее видео" и запустите воспроизведение вручную.</span>
                `;
                
                // Обновляем статус
                updateVideoStatus(currentVideoIndex, 'Просмотр');
                
                // Сбрасываем счетчик
                secondsWatched = 0;
                updateProgress();
                
                // Загружаем и запускаем видео с помощью API
                if (player && player.loadVideoById) {{
                    // Загружаем видео и запускаем его
                    player.loadVideoById({{
                        'videoId': videoId,
                        'startSeconds': 0,
                        'suggestedQuality': 'large'
                    }});
                    player.playVideo();
                    
                    // Устанавливаем громкость на среднее значение
                    setTimeout(function() {{
                        player.setVolume(50);
                        // Дополнительно пробуем запустить воспроизведение через 1 секунду
                        player.playVideo();
                    }}, 1000);
                }}
                
                // Запускаем таймер
                if (timer) {{
                    clearInterval(timer);
                }}
                
                timer = setInterval(() => {{
                    secondsWatched++;
                    updateProgress();
                    
                    // Если достигнуто нужное время просмотра
                    if (secondsWatched >= currentVideo.watchTime) {{
                        // Отмечаем как просмотренное
                        updateVideoStatus(currentVideoIndex, 'Завершено');
                        
                        // Переходим к следующему
                        currentVideoIndex++;
                        
                        // Останавливаем таймер
                        clearInterval(timer);
                        
                        // Небольшая пауза перед следующим видео
                        setTimeout(playCurrentVideo, 1500);
                    }}
                }}, 1000);
                
                // Открываем видео в новой вкладке для надежности
                if (secondsWatched === 0) {{
                    // При первом запуске просмотра для каждого видео открываем его в новой вкладке
                    // для гарантированного добавления в историю просмотров
                    const newTab = window.open(currentVideo.url, '_blank');
                    
                    // Показываем инструкцию пользователю
                    videoInfo.innerHTML = '<div class="warning">' +
                        '<strong style="color: #ff9800;">⚠️ Внимание!</strong> Открыта новая вкладка с видео ' + (currentVideoIndex + 1) + '/' + videos.length + '.<br>' +
                        'Пожалуйста, перейдите в открытую вкладку и запустите воспроизведение кликом.<br>' +
                        'Эта вкладка не закроется автоматически. Закройте её вручную после начала воспроизведения.<br>' +
                        '<span style="color: #4caf50;">✓ Видео будет считаться просмотренным в любом случае через ' + currentVideo.watchTime + ' секунд.</span>' +
                        '</div>';
                }}
                
                // Включаем кнопку пропуска и кнопку ручного открытия
                skipButton.disabled = false;
                manualButton.disabled = false;
            }}
            
            // Остановка просмотра
            function stopWatching() {{
                if (timer) {{
                    clearInterval(timer);
                    timer = null;
                }}
                
                if (player && player.pauseVideo) {{
                    player.pauseVideo();
                }}
                
                watching = false;
                startButton.textContent = '▶️ Продолжить просмотр';
                skipButton.disabled = true;
                manualButton.disabled = true;
            }}
            
            // Обработчики событий
            startButton.addEventListener('click', () => {{
                if (watching) {{
                    stopWatching();
                }} else {{
                    watching = true;
                    startButton.textContent = '⏸️ Пауза';
                    playCurrentVideo();
                }}
            }});
            
            skipButton.addEventListener('click', () => {{
                if (watching) {{
                    clearInterval(timer);
                    
                    // Отмечаем текущее видео как просмотренное
                    updateVideoStatus(currentVideoIndex, 'Завершено');
                    
                    // Переходим к следующему
                    currentVideoIndex++;
                    
                    // Воспроизводим следующее
                    playCurrentVideo();
                }}
            }});
            
            manualButton.addEventListener('click', () => {{
                if (watching && currentVideoIndex < videos.length) {{
                    const currentVideo = videos[currentVideoIndex];
                    window.open(currentVideo.url, '_blank');
                }}
            }});
            
            // Предупреждение при попытке закрыть страницу
            window.addEventListener('beforeunload', (e) => {{
                if (watching) {{
                    e.preventDefault();
                    e.returnValue = 'Просмотр видео не завершен. Закрытие страницы прервет процесс просмотра.';
                    return e.returnValue;
                }}
            }});
        </script>
    </body>
    </html>
    """
    
    return html_content

if __name__ == "__main__":
    main() 