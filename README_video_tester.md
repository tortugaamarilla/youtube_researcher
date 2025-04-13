# Тестирование алгоритма сбора параметров видео

## Описание

Этот инструмент позволяет тестировать работу алгоритма сбора данных о YouTube видео, таких как:
- Количество дней с момента публикации
- Количество просмотров

Интерфейс представляет собой разворачивающийся блок, который можно добавить в любое веб-приложение для удобного тестирования и проверки правильности работы алгоритмов.

## Как использовать

### Вариант 1: Интеграция в существующее веб-приложение

1. Создайте экземпляр класса `YouTubeAnalyzer`:
   ```python
   analyzer = YouTubeAnalyzer(headless=True, use_proxy=False)
   ```

2. Получите HTML-код интерфейса:
   ```python
   html_interface = analyzer.render_video_tester_interface()
   ```

3. Вставьте полученный HTML-код в ваше веб-приложение.

4. Обработайте запросы на анализ видео на бэкенде:
   ```python
   @app.route('/api/test_video_parameters', methods=['POST'])
   def test_video_parameters():
       data = request.json
       urls = data.get('urls', [])
       
       # Анализируем видео
       results_df = analyzer.test_video_parameters(urls)
       
       # Преобразуем в список словарей для JSON
       results = results_df.to_dict(orient='records')
       
       return jsonify(results)
   ```

### Вариант 2: Использование демо-страницы

1. Откройте файл `video_test_interface.html` в вашем браузере.

2. Нажмите на заголовок "Тестирование алгоритма сбора параметров видео", чтобы развернуть интерфейс.

3. Вставьте ссылки на YouTube видео (по одной в строке).

4. Нажмите кнопку "Проверить параметры".

5. Результаты будут отображены в таблице ниже.

### Вариант 3: Использование из командной строки

```bash
python youtube_scraper.py --mode video_test --render-html > interface.html
```

После этого откройте созданный файл `interface.html` в браузере.

## Результаты тестирования

Для каждого видео будут выведены:
- URL видео
- Заголовок видео
- Количество дней с момента публикации
- Количество просмотров

## Интеграция с основным приложением

Для установки блока тестирования видео в ваше приложение, добавьте следующий код в нужное место вашего HTML:

```html
<div id="video-tester-container"></div>

<script>
// Загружаем HTML-интерфейс тестирования
document.addEventListener('DOMContentLoaded', function() {
    fetch('/api/video_tester_interface')
        .then(response => response.text())
        .then(html => {
            document.getElementById('video-tester-container').innerHTML = html;
        });
});
</script>
``` 