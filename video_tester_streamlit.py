import streamlit as st
import pandas as pd
from youtube_scraper import YouTubeAnalyzer

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
                    valid_urls.append(url)
                else:
                    invalid_urls.append(url)
            
            if invalid_urls:
                st.error(f"Следующие URL имеют неверный формат:\n" + "\n".join(invalid_urls))
                return
            
            # Запускаем анализ с индикатором прогресса
            with st.spinner("Анализ видео..."):
                try:
                    # Инициализируем YouTube анализатор
                    analyzer = YouTubeAnalyzer(headless=True, use_proxy=False)
                    
                    # Получаем и обрабатываем результаты
                    results_df = analyzer.test_video_parameters(valid_urls)
                    
                    # Закрываем драйвер
                    analyzer.quit_driver()
                    
                    # Отображаем результаты
                    if not results_df.empty:
                        st.success(f"Анализ завершен! Проанализировано {len(results_df)} видео.")
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

# Если этот файл запускается напрямую, показываем тестовый интерфейс
if __name__ == "__main__":
    st.set_page_config(
        page_title="YouTube Researcher - Тестирование параметров",
        page_icon="🧪",
        layout="wide"
    )
    
    st.title("YouTube Researcher")
    st.markdown("### Инструмент для тестирования сбора параметров YouTube видео")
    
    render_video_tester_section() 