# YouTube Researcher

Приложение для анализа YouTube видео с использованием Streamlit и Selenium. Позволяет находить и анализировать релевантные видео на YouTube на основе списка каналов или видео и эталонных тем.

## Возможности приложения

- Анализ YouTube каналов и видео с использованием Selenium
- Сбор рекомендованных видео из правой колонки YouTube
- Фильтрация видео по дате публикации и количеству просмотров
- Проверка релевантности видео по отношению к эталонным темам с использованием LLM (OpenAI или Claude)
- Извлечение текста из миниатюр видео (thumbnails) с использованием LLM
- Выгрузка результатов в CSV формате

## Новые возможности

### Тестовый режим получения рекомендаций

Добавлен специальный режим для быстрого тестирования функционала получения рекомендаций. 
С помощью кнопки "Тестировать получение рекомендаций из списка исходных ссылок" можно проверить 
работоспособность основных функций без полного запуска анализа.

Подробнее о тестовом режиме читайте в [SETUP.md](SETUP.md).

### Запуск из командной строки

Для тестирования без веб-интерфейса можно использовать:

```bash
# Проверка YouTube функционала
python test_youtube.py --urls "https://www.youtube.com/@MrBeast" "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Запуск с видимым браузером
python test_youtube.py --no-headless

# Проверка прокси-серверов
python check_proxies.py --test-youtube
```

## Требования

- Python 3.8 или выше
- Chrome или Chromium браузер
- API ключи для OpenAI и/или Claude
- Прокси-сервера для обхода ограничений YouTube

## Установка и настройка

### 1. Клонирование репозитория

```bash
git clone <your-repository-url>
cd youtube-researcher
```

### 2. Создание виртуального окружения

```bash
python -m venv virtual_environment
```

Активация виртуального окружения:

**Windows:**
```bash
virtual_environment\Scripts\activate
```

**Linux/Mac:**
```bash
source virtual_environment/bin/activate
```

### 3. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 4. Настройка API ключей и прокси

Создайте файл `.streamlit/secrets.toml` со следующим содержимым:

```toml
# API ключи для доступа к LLM моделям
OPENAI_API_KEY = "your-openai-api-key"
ANTHROPIC_API_KEY = "your-anthropic-api-key"

# Список прокси-серверов для работы с YouTube
[proxies]
servers = [
  "ip:port:username:password",
  "ip:port:username:password",
  "ip:port:username:password"
]
```

Замените значения на свои API ключи и данные прокси серверов.

## Запуск приложения

```bash
streamlit run app.py
```

## Публикация на Streamlit.io

1. Создайте аккаунт на [streamlit.io](https://streamlit.io/)
2. Загрузите код в GitHub репозиторий
3. На [share.streamlit.io](https://share.streamlit.io/) подключите ваш репозиторий
4. Добавьте API ключи и прокси в секреты в настройках приложения

## Примечания по использованию Selenium

Для корректной работы Selenium необходимо:

1. **Установить Chrome или Chromium браузер** соответствующей версии (приложение использует ChromeDriverManager для автоматической установки совместимого WebDriver)

2. **На Windows** убедитесь, что Chrome установлен в стандартном месте:
   ```
   C:\Program Files\Google\Chrome\Application\chrome.exe
   ```
   или 
   ```
   C:\Program Files (x86)\Google\Chrome\Application\chrome.exe
   ```

3. **На Linux** может потребоваться установка дополнительных зависимостей:
   ```bash
   sudo apt-get update
   sudo apt-get install -y chromium-browser xvfb
   ```

4. **На macOS** стандартной установки Chrome должно быть достаточно.

5. Для запуска в Docker-контейнере понадобятся дополнительные настройки, которые не включены в текущую версию.

## Решение проблем

- **Selenium не запускается**: Убедитесь, что Chrome/Chromium установлен и доступен в системе
- **Ошибки прокси**: Проверьте правильность формата данных прокси в секретах
- **API ключи не работают**: Проверьте актуальность и права доступа ваших API ключей
- **Блокировка YouTube**: Увеличьте задержки в коде или используйте больше разных прокси

## Лицензия

MIT 