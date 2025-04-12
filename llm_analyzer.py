import os
import time
import logging
from typing import Optional, Dict, Any, List, Union
import base64
from io import BytesIO
from PIL import Image

import openai
from anthropic import Anthropic, HUMAN_PROMPT, AI_PROMPT

from utils import get_api_keys

# Настройка логирования
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class LLMAnalyzer:
    """
    Класс для анализа контента с использованием LLM (OpenAI и Claude).
    """
    
    def __init__(self, model_name: str = "claude-3-5-sonnet-20240620"):
        """
        Инициализация анализатора LLM.
        
        Args:
            model_name (str): Название модели для использования.
        """
        self.model_name = model_name
        self.openai_api_key, self.anthropic_api_key = get_api_keys()
        
        self.openai_client = None
        self.anthropic_client = None
        
        self._initialize_clients()
        
    def _initialize_clients(self) -> None:
        """
        Инициализация клиентов API.
        """
        # Инициализация OpenAI
        if self.openai_api_key:
            try:
                self.openai_client = openai.OpenAI(api_key=self.openai_api_key)
                logger.info("Клиент OpenAI успешно инициализирован")
            except Exception as e:
                logger.error(f"Ошибка при инициализации клиента OpenAI: {e}")
                
        # Инициализация Anthropic
        if self.anthropic_api_key:
            try:
                self.anthropic_client = Anthropic(api_key=self.anthropic_api_key)
                logger.info("Клиент Anthropic успешно инициализирован")
            except Exception as e:
                logger.error(f"Ошибка при инициализации клиента Anthropic: {e}")
                
    def is_model_available(self) -> bool:
        """
        Проверяет доступность выбранной модели.
        
        Returns:
            bool: True, если модель доступна, иначе False.
        """
        if self.model_name.startswith(("gpt-4", "gpt-3.5")):
            return self.openai_client is not None
        elif self.model_name.startswith("claude"):
            return self.anthropic_client is not None
        else:
            return False
            
    def check_relevance(
        self, 
        title: str, 
        reference_topics: List[str], 
        temperature: float = 0.0
    ) -> Dict[str, Any]:
        """
        Проверяет релевантность заголовка видео для заданных эталонных тем.
        
        Args:
            title (str): Заголовок видео.
            reference_topics (List[str]): Список эталонных тем.
            temperature (float): Температура релевантности (0-10).
            
        Returns:
            Dict[str, Any]: Результат проверки релевантности.
        """
        if not self.is_model_available():
            return {"relevant": True, "score": 0.0, "explanation": "Модель недоступна, считаем релевантным по умолчанию"}
            
        # Если температура равна 0, считаем все релевантным
        if temperature <= 0.0:
            return {"relevant": True, "score": 1.0, "explanation": "Проверка релевантности отключена"}
            
        # Нормализуем температуру для API
        api_temperature = min(temperature / 10.0, 1.0)
        
        # Формируем запрос к модели
        topics_text = "\n".join([f"- {topic}" for topic in reference_topics])
        
        prompt = f"""
        Оцени релевантность следующего заголовка видео относительно списка эталонных тем.
        
        Заголовок: "{title}"
        
        Эталонные темы:
        {topics_text}
        
        Оцени релевантность по шкале от 0 до 10, где:
        - 0-3: Не релевантно
        - 4-6: Частично релевантно
        - 7-10: Полностью релевантно
        
        Ответ дай в формате JSON:
        {{
            "score": <числовая оценка от 0 до 10>,
            "relevant": <true/false, где true для оценки >= 7>,
            "explanation": "<краткое объяснение оценки>"
        }}
        """
        
        try:
            if self.model_name.startswith(("gpt-4", "gpt-3.5")):
                return self._check_relevance_openai(prompt, api_temperature)
            elif self.model_name.startswith("claude"):
                return self._check_relevance_anthropic(prompt, api_temperature)
            else:
                return {"relevant": True, "score": 0.0, "explanation": "Неизвестная модель, считаем релевантным по умолчанию"}
                
        except Exception as e:
            logger.error(f"Ошибка при проверке релевантности: {e}")
            return {"relevant": True, "score": 0.0, "explanation": f"Ошибка: {str(e)}"}
            
    def _check_relevance_openai(self, prompt: str, temperature: float) -> Dict[str, Any]:
        """
        Проверяет релевантность с использованием модели OpenAI.
        
        Args:
            prompt (str): Текст запроса.
            temperature (float): Температура генерации.
            
        Returns:
            Dict[str, Any]: Результат проверки релевантности.
        """
        try:
            response = self.openai_client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "Ты помощник, который оценивает релевантность заголовка видео относительно заданных тем."},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                response_format={"type": "json_object"}
            )
            
            result = response.choices[0].message.content
            
            try:
                import json
                result_json = json.loads(result)
                return result_json
            except:
                return {"relevant": True, "score": 0.0, "explanation": "Ошибка при парсинге ответа модели"}
                
        except Exception as e:
            logger.error(f"Ошибка при обращении к OpenAI API: {e}")
            return {"relevant": True, "score": 0.0, "explanation": f"Ошибка OpenAI API: {str(e)}"}
            
    def _check_relevance_anthropic(self, prompt: str, temperature: float) -> Dict[str, Any]:
        """
        Проверяет релевантность с использованием модели Anthropic Claude.
        
        Args:
            prompt (str): Текст запроса.
            temperature (float): Температура генерации.
            
        Returns:
            Dict[str, Any]: Результат проверки релевантности.
        """
        try:
            response = self.anthropic_client.messages.create(
                model=self.model_name,
                max_tokens=1000,
                temperature=temperature,
                system="Ты помощник, который оценивает релевантность заголовка видео относительно заданных тем.",
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            result = response.content[0].text
            
            try:
                import json
                # Извлекаем JSON из ответа
                import re
                json_match = re.search(r'({.*})', result, re.DOTALL)
                if json_match:
                    result_json = json.loads(json_match.group(1))
                    return result_json
                else:
                    return {"relevant": True, "score": 0.0, "explanation": "Ответ модели не содержит JSON"}
            except:
                return {"relevant": True, "score": 0.0, "explanation": "Ошибка при парсинге ответа модели"}
                
        except Exception as e:
            logger.error(f"Ошибка при обращении к Anthropic API: {e}")
            return {"relevant": True, "score": 0.0, "explanation": f"Ошибка Anthropic API: {str(e)}"}
            
    def extract_text_from_thumbnail(self, image: Image.Image) -> str:
        """
        Извлекает текст из миниатюры видео с использованием LLM.
        
        Args:
            image (Image.Image): Изображение миниатюры.
            
        Returns:
            str: Извлеченный текст или пустая строка в случае ошибки.
        """
        if not self.is_model_available():
            return ""
            
        try:
            # Преобразуем изображение в base64
            buffered = BytesIO()
            image.save(buffered, format="JPEG")
            img_str = base64.b64encode(buffered.getvalue()).decode()
            
            if self.model_name.startswith(("gpt-4", "gpt-3.5")):
                return self._extract_text_openai(img_str)
            elif self.model_name.startswith("claude"):
                return self._extract_text_anthropic(img_str)
            else:
                return ""
                
        except Exception as e:
            logger.error(f"Ошибка при извлечении текста из миниатюры: {e}")
            return ""
            
    def _extract_text_openai(self, img_base64: str) -> str:
        """
        Извлекает текст из миниатюры с использованием модели OpenAI.
        
        Args:
            img_base64 (str): Изображение в формате base64.
            
        Returns:
            str: Извлеченный текст.
        """
        try:
            response = self.openai_client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "system", 
                        "content": "Ты помощник по распознаванию текста с изображений. Твоя задача - извлечь весь видимый текст с миниатюры YouTube видео."
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Извлеки весь текст с этой миниатюры YouTube видео. Верни только текст, без дополнительных комментариев."},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{img_base64}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=300
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"Ошибка при обращении к OpenAI API для распознавания текста: {e}")
            return ""
            
    def _extract_text_anthropic(self, img_base64: str) -> str:
        """
        Извлекает текст из миниатюры с использованием модели Anthropic Claude.
        
        Args:
            img_base64 (str): Изображение в формате base64.
            
        Returns:
            str: Извлеченный текст.
        """
        try:
            response = self.anthropic_client.messages.create(
                model=self.model_name,
                max_tokens=1000,
                system="Ты помощник по распознаванию текста с изображений. Твоя задача - извлечь весь видимый текст с миниатюры YouTube видео.",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Извлеки весь текст с этой миниатюры YouTube видео. Верни только текст, без дополнительных комментариев."},
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": img_base64
                                }
                            }
                        ]
                    }
                ]
            )
            
            return response.content[0].text.strip()
            
        except Exception as e:
            logger.error(f"Ошибка при обращении к Anthropic API для распознавания текста: {e}")
            return "" 