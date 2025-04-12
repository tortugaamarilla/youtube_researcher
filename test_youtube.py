#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Скрипт для тестирования функционала YouTube Analyzer

Этот скрипт позволяет проверить работоспособность основных функций 
YouTube Analyzer без использования прокси. Он тестирует получение видео 
с канала и получение рекомендаций для видео.
"""

import argparse
import logging
import sys
import traceback
from typing import List, Dict, Any

# Настройка логирования
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_youtube_analyzer(test_urls: List[str], headless: bool = True) -> bool:
    """
    Тестирует основные функции YouTube Analyzer.
    
    Args:
        test_urls (List[str]): Список URL для тестирования.
        headless (bool): Использовать ли безголовый режим браузера.
        
    Returns:
        bool: True, если тест прошел успешно, False в противном случае.
    """
    try:
        from youtube_scraper import YouTubeAnalyzer
        import pandas as pd
        
        # Выводим информацию о тестировании
        logger.info(f"Начинаем тестирование YouTube Analyzer с {len(test_urls)} URL")
        logger.info(f"Режим без интерфейса (headless): {headless}")
        
        # Создаем анализатор YouTube без прокси
        analyzer = YouTubeAnalyzer(headless=headless, use_proxy=False)
        
        # Список для сохранения результатов
        all_results = []
        
        # Инициализируем драйвер
        logger.info("Инициализация драйвера...")
        analyzer.setup_driver()
        
        if not analyzer.driver:
            logger.error("Не удалось инициализировать драйвер")
            return False
        
        # Тестируем каждый URL
        for idx, url in enumerate(test_urls, 1):
            try:
                logger.info(f"[{idx}/{len(test_urls)}] Тестирование URL: {url}")
                
                # Проверяем тип URL (канал или видео)
                from utils import parse_youtube_url
                parsed_url, is_channel = parse_youtube_url(url)
                
                if is_channel:
                    # Тестируем получение видео с канала
                    logger.info(f"URL является каналом, получаем последние видео...")
                    videos = analyzer.get_last_videos_from_channel(parsed_url, limit=3)
                    
                    if videos:
                        logger.info(f"Успешно получено {len(videos)} видео с канала")
                        
                        # Сохраняем результаты
                        for video in videos:
                            video["source"] = f"Канал: {parsed_url}"
                            all_results.append(video)
                        
                        # Тестируем получение рекомендаций для первого видео
                        first_video_url = videos[0].get("url")
                        if first_video_url:
                            logger.info(f"Получаем рекомендации для видео {first_video_url}")
                            recommendations = analyzer.get_recommended_videos(first_video_url, limit=3)
                            
                            if recommendations:
                                logger.info(f"Успешно получено {len(recommendations)} рекомендаций")
                                
                                # Получаем детали каждой рекомендации
                                for rec in recommendations:
                                    rec_url = rec.get("url")
                                    if rec_url:
                                        rec_details = analyzer.get_video_details(rec_url)
                                        if rec_details:
                                            rec_details["source"] = f"Рекомендация для: {first_video_url}"
                                            all_results.append(rec_details)
                            else:
                                logger.warning(f"Не удалось получить рекомендации для видео {first_video_url}")
                    else:
                        logger.warning(f"Не удалось получить видео с канала {parsed_url}")
                else:
                    # Тестируем получение деталей видео
                    logger.info(f"URL является видео, получаем детали...")
                    video_details = analyzer.get_video_details(parsed_url)
                    
                    if video_details and video_details.get("title"):
                        logger.info(f"Успешно получены детали видео: {video_details.get('title')}")
                        
                        # Сохраняем результаты
                        video_details["source"] = f"Прямая ссылка: {parsed_url}"
                        all_results.append(video_details)
                        
                        # Тестируем получение рекомендаций
                        logger.info(f"Получаем рекомендации для видео {parsed_url}")
                        recommendations = analyzer.get_recommended_videos(parsed_url, limit=3)
                        
                        if recommendations:
                            logger.info(f"Успешно получено {len(recommendations)} рекомендаций")
                            
                            # Получаем детали каждой рекомендации
                            for rec in recommendations:
                                rec_url = rec.get("url")
                                if rec_url:
                                    rec_details = analyzer.get_video_details(rec_url)
                                    if rec_details:
                                        rec_details["source"] = f"Рекомендация для: {parsed_url}"
                                        all_results.append(rec_details)
                        else:
                            logger.warning(f"Не удалось получить рекомендации для видео {parsed_url}")
                    else:
                        logger.warning(f"Не удалось получить детали видео {parsed_url}")
            
            except Exception as e:
                logger.error(f"Ошибка при тестировании URL {url}: {e}")
                traceback.print_exc()
        
        # Закрываем драйвер
        analyzer.quit_driver()
        
        # Сохраняем результаты в CSV и выводим статистику
        if all_results:
            try:
                df = pd.DataFrame(all_results)
                output_file = "youtube_test_results.csv"
                df.to_csv(output_file, index=False)
                logger.info(f"Результаты сохранены в файл: {output_file}")
                
                # Выводим статистику
                logger.info(f"Общее количество собранных видео: {len(all_results)}")
                
                # Группируем по источнику
                source_counts = {}
                for result in all_results:
                    source = result.get("source", "Неизвестно")
                    source_counts[source] = source_counts.get(source, 0) + 1
                
                logger.info("Статистика по источникам:")
                for source, count in source_counts.items():
                    logger.info(f"  - {source}: {count} видео")
                
                return True
            except Exception as e:
                logger.error(f"Ошибка при сохранении результатов: {e}")
                return False
        else:
            logger.warning("Не удалось собрать никаких данных для сохранения")
            return False
        
    except Exception as e:
        logger.error(f"Общая ошибка при тестировании YouTube Analyzer: {e}")
        traceback.print_exc()
        return False

def main():
    """
    Главная функция скрипта.
    """
    parser = argparse.ArgumentParser(description="Скрипт для тестирования YouTube Analyzer")
    
    # Добавляем параметры командной строки
    parser.add_argument("--urls", "-u", type=str, nargs="+", help="Список URL для тестирования")
    parser.add_argument("--no-headless", action="store_true", help="Запустить браузер с интерфейсом")
    parser.add_argument("--verbose", "-v", action="store_true", help="Подробный вывод")
    
    args = parser.parse_args()
    
    # Настраиваем уровень логирования
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # Определяем список URL для тестирования
    test_urls = args.urls if args.urls else [
        "https://www.youtube.com/@MrBeast",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # Известное видео
    ]
    
    # Запускаем тестирование
    headless = not args.no_headless
    success = test_youtube_analyzer(test_urls, headless)
    
    # Выводим итоги тестирования
    if success:
        logger.info("Тестирование успешно завершено")
        return 0
    else:
        logger.error("Тестирование завершилось с ошибками")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 