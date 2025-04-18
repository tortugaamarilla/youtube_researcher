import os
import time
import logging
import tempfile
import concurrent.futures
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
import base64
import random
import json
import hashlib
import uuid
from io import BytesIO
import re
import traceback

from youtube_scraper import YouTubeAnalyzer
from utils import parse_youtube_url

# Настройка логирования
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
                    
                    try:
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
                    except Exception as e:
                        logger.error(f"Ошибка при получении данных о видео: {e}")
                        video_data = None
                    
                    video_data_time = end_timer(f"Получение данных о видео: {video_url}")
                    status_text.text(f"Получены данные о видео за {video_data_time:.2f}с")
                    
                    # Получаем рекомендации для этого видео независимо от критериев
                    status_text.text(f"Получение рекомендаций для видео: {video_url}")
                    start_timer(f"Получение рекомендаций для видео: {video_url}")
                    
                    try:
                        # Используем быстрый метод вместо обычного
                        recommendations = youtube_analyzer.get_recommended_videos_fast(video_url, limit=recommendations_per_video)
                    except Exception as e:
                        logger.error(f"Ошибка при получении рекомендаций: {e}")
                        recommendations = []
                    
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
                
                # Получаем детали видео
                status_text.text(f"Получение деталей видео: {url}")
                start_timer(f"Получение данных о видео: {url}")
                
                try:
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
                except Exception as e:
                    logger.error(f"Ошибка при получении данных о видео: {e}")
                    video_data = None
                
                video_data_time = end_timer(f"Получение данных о видео: {url}")
                status_text.text(f"Получены данные о видео за {video_data_time:.2f}с")
                stats["processed_videos"] += 1
                
                # Получаем рекомендации для видео независимо от критериев
                status_text.text(f"Получение рекомендаций для видео: {url}")
                start_timer(f"Получение рекомендаций для видео: {url}")
                
                try:
                    recommendations = youtube_analyzer.get_recommended_videos_fast(url, limit=recommendations_per_video)
                except Exception as e:
                    logger.error(f"Ошибка при получении рекомендаций: {e}")
                    recommendations = []
                
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

        # Добавляем исходные видео к результатам
        # Важно: сначала добавляем исходные видео, чтобы они не были удалены как дубликаты
        results = source_videos + results
        
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

        # Завершаем прогресс
        progress_bar.progress(1.0)
        status_text.text("Обработка завершена!")

        # Создаем датафрейм из результатов
        if results:
            # Формируем датафрейм с нужными колонками
            results_df = pd.DataFrame(results)
            
            # Очищаем все URL-адреса в датафрейме от дополнительных параметров
            if "url" in results_df.columns:
                results_df["url"] = results_df["url"].apply(clean_youtube_url)
            
            # Удаляем дубликаты по URL видео, сохраняя порядок добавления
            # Это гарантирует, что исходные видео (которые были добавлены первыми) сохранятся
            seen_urls = set()
            unique_df_rows = []
            
            for idx, row in results_df.iterrows():
                url = row["url"]
                if url not in seen_urls:
                    seen_urls.add(url)
                    unique_df_rows.append(row)
            
            results_df = pd.DataFrame(unique_df_rows)
            
            # Добавляем нумерацию, начинающуюся с 1 после удаления дубликатов
            results_df.index = range(1, len(results_df) + 1)
            
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
            existing_columns = {k: v for k, v in columns_to_show.items() if k in results_df.columns}
            
            if existing_columns:
                results_df = results_df[list(existing_columns.keys())]
                results_df = results_df.rename(columns=existing_columns)
                
                # Удаляем дубликаты по URL видео
                results_df = results_df.drop_duplicates(subset=["Ссылка на видео"])
                
                # Преобразуем ссылки в активные для отображения в Streamlit
                results_df["Ссылка на видео"] = results_df["Ссылка на видео"].apply(
                    lambda x: f'<a href="{x}" target="_blank">{x}</a>' if isinstance(x, str) else x
                )
                
                # Преобразуем ссылки на каналы в активные для отображения в Streamlit
                if "Канал" in results_df.columns:
                    results_df["Канал"] = results_df["Канал"].apply(
                        lambda x: f'<a href="{x}" target="_blank">{x}</a>' if isinstance(x, str) and x else x
                    )
                    
                    # Сохраняем URL канала, если колонка существует
                    if "Канал" in results_df.columns and "channel_url" not in results_df.columns:
                        results_df["URL канала"] = results_df["Канал"]
                
                return results_df
            else:
                return pd.DataFrame()
        else:
            return pd.DataFrame()
    except Exception as e:
        status_text.error(f"Произошла ошибка: {e}")
        logger.error(f"Ошибка при тестировании рекомендаций: {e}")
        traceback.print_exc()
        return pd.DataFrame()
    finally:
        # Закрываем драйвер только если он не был передан извне
        if youtube_analyzer and youtube_analyzer is not existing_analyzer:
            youtube_analyzer.quit_driver()

def render_recommendations_section():
    """
    Отображает раздел получения рекомендаций.
    """
    st.header("Получение рекомендаций YouTube")
    
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
                max_value=200, 
                value=5
            )
        with col2:
            recommendations_per_video = st.number_input(
                "Количество рекомендаций для каждого видео", 
                min_value=1, 
                max_value=500, 
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
                
                # Получаем данные аккаунта из сессии
                google_account = st.session_state.get("google_account")
                
                # Вызываем функцию сбора рекомендаций с переданным драйвером
                results_df = test_recommendations(
                    source_links, 
                    google_account=google_account, 
                    prewatch_settings=None,  # Убираем предварительный просмотр
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