import streamlit as st
import logging
import pandas as pd
import requests
import base64
from typing import List, Dict, Any, Optional
from youtube_scraper import YouTubeAnalyzer
from module_recommendations import clean_youtube_url

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
    
    # Проверяем, не исчерпана ли квота API
    api_quota_exceeded = False
    if "api_quota_exceeded" in st.session_state:
        api_quota_exceeded = st.session_state["api_quota_exceeded"]
    
    if api_quota_exceeded:
        st.error("""
        ⚠️ **Квота YouTube API исчерпана**
        
        YouTube API имеет лимит на количество запросов в день. 
        На данный момент квота исчерпана. Попробуйте следующее:
        
        1. Подождите до следующего дня, когда квота будет сброшена (в полночь по UTC)
        2. Используйте другой API ключ
        3. Увеличьте квоту в Google Cloud Console (может потребоваться оплата)
        """)
    
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
    start_test = st.button("Собрать данные о видео", key="start_video_api_test", disabled=api_quota_exceeded)
    
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
        quota_exceeded = False
        
        for idx, url in enumerate(video_urls):
            try:
                # Если квота превышена, прекращаем обработку
                if quota_exceeded:
                    break
                
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
                
                # Проверяем, не превышена ли квота API
                if video_details is None and hasattr(api_analyzer, 'last_api_error') and 'quotaExceeded' in str(api_analyzer.last_api_error):
                    quota_exceeded = True
                    st.session_state["api_quota_exceeded"] = True
                    status_message.error("⚠️ Квота YouTube API исчерпана. Дальнейшие запросы невозможны.")
                    break
                
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
                # Проверяем, не является ли ошибка связанной с квотой API
                if "quota" in str(e).lower():
                    quota_exceeded = True
                    st.session_state["api_quota_exceeded"] = True
                    status_message.error("⚠️ Квота YouTube API исчерпана. Дальнейшие запросы невозможны.")
                    break
                
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
        
        if quota_exceeded:
            status_message.error("""
            ⚠️ **Квота YouTube API исчерпана**
            
            Некоторые данные могли быть получены до достижения лимита.
            YouTube ограничивает количество запросов API в день.
            Попробуйте снова завтра или используйте другой API ключ.
            """)
            
            # Если нет данных вообще, возвращаемся
            if not videos_data:
                return
        
        if videos_data:
            # Преобразуем в DataFrame
            videos_df = pd.DataFrame(videos_data)
            st.session_state.video_api_test_results = videos_df
            
            success_message = f"Сбор данных завершен. Получена информация о {len(videos_data)} видео."
            if quota_exceeded:
                success_message += " (частично, из-за превышения квоты API)"
                
            status_message.success(success_message)
        else:
            status_message.error("Не удалось собрать данные ни об одном видео.")
    
    # Отображаем результаты, если они есть
    if st.session_state.get("video_api_test_results") is not None and not st.session_state.get("video_api_test_results").empty:
        st.subheader("Результаты тестирования API")
        
        results_df = st.session_state.video_api_test_results.copy()
        
        # Форматируем числовую колонку просмотров
        if "Количество просмотров" in results_df.columns:
            results_df["Количество просмотров"] = results_df["Количество просмотров"].apply(
                lambda x: f"{int(x):,}".replace(",", " ") if isinstance(x, (int, float)) else x
            )
        
        # Создаем колонку с кликабельными превью для отображения
        if "Превью" in results_df.columns:
            results_df["Превью (изображение)"] = results_df["Превью"].apply(
                lambda x: f'<a href="{x}" target="_blank"><img src="{x}" width="120" /></a>' if x else ""
            )
        
        # Отображаем таблицу с данными (с поддержкой HTML)
        st.write(results_df.to_html(escape=False), unsafe_allow_html=True)
        
        # Создаем ссылку для скачивания CSV
        export_df = results_df.copy()
        if "Превью (изображение)" in export_df.columns:
            export_df = export_df.drop(columns=["Превью (изображение)"])
        
        csv = export_df.to_csv(index=False, sep='\t')
        b64 = base64.b64encode(csv.encode()).decode()
        href = f'<a href="data:file/csv;base64,{b64}" download="youtube_videos_api_data.csv" target="_blank">📊 Скачать данные о видео (CSV)</a>'
        st.markdown(href, unsafe_allow_html=True)

# Функция для создания кликабельной ссылки
def make_clickable(url, text=None):
    """
    Создает HTML-код для кликабельной ссылки.
    
    Args:
        url (str): URL ссылки.
        text (str, optional): Текст ссылки. Если не указан, используется URL.
        
    Returns:
        str: HTML-код кликабельной ссылки.
    """
    if not url:
        return ""
    
    text = text or url
    return f'<a href="{url}" target="_blank">{text}</a>' 