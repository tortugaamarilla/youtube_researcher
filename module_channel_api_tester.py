import streamlit as st
import logging
import pandas as pd
import requests
import base64
from typing import List, Dict, Any, Optional
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
    start_test = st.button("Собрать данные о каналах", key="start_api_test", disabled=api_quota_exceeded)
    
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
        quota_exceeded = False
        
        for idx, url in enumerate(channel_urls):
            try:
                # Если квота превышена, прекращаем обработку
                if quota_exceeded:
                    break
                
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
                            
                            try:
                                search_response = requests.get(search_url, params=search_params)
                                
                                # Проверяем, не превышена ли квота API
                                if search_response.status_code == 403 and "quota" in search_response.text.lower():
                                    quota_exceeded = True
                                    st.session_state["api_quota_exceeded"] = True
                                    status_message.error("⚠️ Квота YouTube API исчерпана. Дальнейшие запросы невозможны.")
                                    break
                                
                                if search_response.status_code == 200:
                                    search_data = search_response.json()
                                    if search_data.get('items') and len(search_data['items']) > 0:
                                        channel_id = search_data['items'][0]['id']['channelId']
                            except Exception as e:
                                if "quota" in str(e).lower():
                                    quota_exceeded = True
                                    st.session_state["api_quota_exceeded"] = True
                                    status_message.error("⚠️ Квота YouTube API исчерпана. Дальнейшие запросы невозможны.")
                                    break
                                logger.error(f"Ошибка при поиске канала по имени: {e}")
                
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
                
                # Проверяем, не превышена ли квота API
                if channel_details is None and hasattr(api_analyzer, 'last_api_error') and 'quotaExceeded' in str(api_analyzer.last_api_error):
                    quota_exceeded = True
                    st.session_state["api_quota_exceeded"] = True
                    status_message.error("⚠️ Квота YouTube API исчерпана. Дальнейшие запросы невозможны.")
                    break
                
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
                # Проверяем, не является ли ошибка связанной с квотой API
                if "quota" in str(e).lower():
                    quota_exceeded = True
                    st.session_state["api_quota_exceeded"] = True
                    status_message.error("⚠️ Квота YouTube API исчерпана. Дальнейшие запросы невозможны.")
                    break
                
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
        
        if quota_exceeded:
            status_message.error("""
            ⚠️ **Квота YouTube API исчерпана**
            
            Некоторые данные могли быть получены до достижения лимита.
            YouTube ограничивает количество запросов API в день.
            Попробуйте снова завтра или используйте другой API ключ.
            """)
            
            # Если нет данных вообще, возвращаемся
            if not channels_data:
                return
        
        if channels_data:
            # Преобразуем в DataFrame
            channels_df = pd.DataFrame(channels_data)
            st.session_state.api_test_results = channels_df
            
            success_message = f"Сбор данных завершен. Получена информация о {len(channels_data)} каналах."
            if quota_exceeded:
                success_message += " (частично, из-за превышения квоты API)"
                
            status_message.success(success_message)
        else:
            status_message.error("Не удалось собрать данные ни об одном канале.")
    
    # Отображаем результаты, если они есть
    if st.session_state.get("api_test_results") is not None and not st.session_state.get("api_test_results").empty:
        st.subheader("Результаты тестирования API")
        
        results_df = st.session_state.api_test_results.copy()
        
        # Форматируем числовые колонки
        numeric_columns = ["Количество видео", "Общее число просмотров", "Возраст канала (дней)", "Количество подписчиков"]
        for col in numeric_columns:
            if col in results_df.columns:
                results_df[col] = results_df[col].apply(
                    lambda x: f"{int(x):,}".replace(",", " ") if isinstance(x, (int, float)) else x
                )
        
        # Отображаем таблицу с данными
        st.dataframe(results_df)
        
        # Создаем ссылку для скачивания CSV
        csv = results_df.to_csv(index=False, sep='\t')
        b64 = base64.b64encode(csv.encode()).decode()
        href = f'<a href="data:file/csv;base64,{b64}" download="youtube_channels_api_data.csv" target="_blank">📊 Скачать данные о каналах (CSV)</a>'
        st.markdown(href, unsafe_allow_html=True) 