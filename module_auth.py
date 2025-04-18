import streamlit as st
import logging
from youtube_scraper import YouTubeAnalyzer

# Настройка логирования
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def render_auth_section():
    """
    Отображает раздел авторизации в Google.
    
    Returns:
        dict: Словарь с данными авторизации или None, если авторизация не выполнена
    """
    st.header("Авторизация в Google")
    
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
    
    return google_account 