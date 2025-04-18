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

from youtube_scraper import YouTubeAnalyzer
from utils import parse_youtube_url

# Настройка логирования
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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

# Добавляем функцию для отображения результатов на вкладке
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
                    video_url = video_info.get("url") if isinstance(video_info, dict) else video_info
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
                        rec_url = rec_info.get("url") if isinstance(rec_info, dict) else rec_info
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
                    rec_url = rec_info.get("url") if isinstance(rec_info, dict) else rec_info
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
                
                # Обновляем статистику по завершению обработки видео
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
            
            # Фиксируем время всего пакета
            batch_time = end_timer(f"Обработка пакета рекомендаций {i+1}-{min(i+batch_size, len(filtered_recommendations))}")
            status_text.text(f"Пакет обработан за {batch_time:.2f}с")
        
        # Добавляем исходные видео к результатам
        # Важно: сначала добавляем исходные видео, чтобы они не были удалены как дубликаты
        results = source_videos + results
        
        # Завершаем прогресс
        progress_bar.progress(1.0)
        status_text.text("Обработка завершена!")
        
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
            
            return df
        else:
            return pd.DataFrame()
    else:
        return pd.DataFrame()

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
            results_df["Превью"] = results_df["Превью"].apply(
                lambda x: f'<img src="{x}" width="120">' if isinstance(x, str) and x else ""
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
        
        # Добавим сокращение длинных текстов транскрипции
        if "Транскрипция" in results_df.columns:
            results_df["Транскрипция"] = results_df["Транскрипция"].apply(
                lambda x: x[:150] + "..." if isinstance(x, str) and len(x) > 150 else x
            )
        
        # Исключаем некоторые колонки для отображения
        display_columns = [col for col in results_df.columns if col not in ["ID видео", "Ошибка"]]
        
        # Отображаем таблицу
        st.write(results_df[display_columns].to_html(escape=False), unsafe_allow_html=True)
        
        # Создаем копию dataframe для экспорта без форматирования
        export_df = results_df.copy()
        export_df["Заголовок видео"] = original_titles  # Восстанавливаем оригинальные заголовки без HTML
        
        # Для экспорта подготавливаем данные без форматирования
        if "Количество просмотров" in export_df.columns:
            export_df["Количество просмотров"] = pd.to_numeric(export_df["Количество просмотров"].str.replace(" ", ""), errors="coerce")
        
        # Удаляем HTML из превью
        if "Превью" in export_df.columns:
            export_df["URL превью"] = results_df["Превью"].str.extract(r'src="([^"]+)"', expand=False)
            export_df = export_df.drop("Превью", axis=1)
        
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

def main():
    # Настройка логгера
    setup_logging()
    
    # Загружаем API ключ из secrets
    api_key = load_api_key_from_secrets()
    if api_key:
        st.session_state["youtube_api_key"] = api_key
        logger.info("YouTube API ключ загружен в сессию")
    
    st.title("YouTube Researcher 🎬")

    # Основное содержимое
    tab1, tab2, tab3 = st.tabs(["Получение рекомендаций", "Тест API каналов", "Тест API видео"])
    
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
                                use_proxy=False,
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
                    max_value=100000,
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
                        existing_analyzer=existing_analyzer
                    )
                    
                    if not results_df.empty:
                        st.session_state["results_df"] = results_df
                        st.success(f"Собрано {len(results_df)} результатов.")
                        
                        # Отображаем результаты
                        display_results_tab1()
                    else:
                        st.error("Не удалось собрать данные. Проверьте логи для подробностей.")
                        # Вывод диагностической информации
                        st.error("Диагностическая информация:")
                        st.write("- Проверьте соединение с интернетом")
                        st.write("- Проверьте настройки драйвера и сети")
            else:
                st.error("Необходимо указать хотя бы одну ссылку на YouTube для сбора рекомендаций.")
                # Проверяем наличие данных в сессии и отображаем их, если они есть
                if "results_df" in st.session_state and not st.session_state["results_df"].empty:
                    st.success(f"Показаны предыдущие результаты ({len(st.session_state['results_df'])} записей).")
                    display_results_tab1()
    
    with tab2:
        # Раздел для тестирования API каналов
        render_api_tester_section()
    
    with tab3:
        # Раздел для тестирования API видео
        render_video_api_tester_section()

if __name__ == "__main__":
    # Настройка страницы Streamlit (должно быть первой командой)
    st.set_page_config(
        page_title="YouTube Researcher",
        page_icon="🎥",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    main()