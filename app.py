import os
import logging
import streamlit as st

# Импортируем модули
from module_auth import render_auth_section
from module_recommendations import render_recommendations_section
from module_channel_api_tester import render_api_tester_section, load_api_key_from_secrets
from module_video_api_tester import render_video_api_tester_section

# Настройка логирования
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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

def main():
    # Настройка логгера
    setup_logging()
    
    # Загружаем API ключ из secrets
    api_key = load_api_key_from_secrets()
    if api_key:
        st.session_state["youtube_api_key"] = api_key
        logger.info("YouTube API ключ загружен в сессию")
    
    st.title("YouTube Researcher 🎬")

    # Создаем вкладки
    tab0, tab1, tab2, tab3 = st.tabs(["Авторизация в Google", "Получение рекомендаций", "Тест API каналов", "Тест API видео"])
    
    with tab0:
        # Раздел авторизации в Google
        google_account = render_auth_section()
    
    with tab1:
        # Раздел получения рекомендаций
        render_recommendations_section()
    
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