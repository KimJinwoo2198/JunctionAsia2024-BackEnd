import logging
import json
import re
from typing import Any, Optional
from openai import OpenAI, OpenAIError
from django.conf import settings
from vision.models import FoodRecognitionLog

logger = logging.getLogger(__name__)
DEFAULT_VISION_MODEL = "gpt-4o"
BACKUP_VISION_MODEL = "gpt-4o-mini"

def get_openai_client() -> OpenAI:
    api_key = settings.OPENAI_API_KEY
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=api_key)

def _build_messages(base64_image: str):
    return [
        {
            "role": "system",
            "content": (
                "You are an expert food vision labeler. Identify ONLY the single most salient food or beverage in the image and output its exact name in Korean.\n"
                "Follow these rules strictly and return JSON only.\n\n"
                "Output format (strict JSON):\n{\n  \"food_name\": \"<정확한 이름(한국어)>\"\n}\n\n"
                "Labeling rules (priority):\n"
                "1) If it is a packaged/branded product with visible label/logo/text, return the exact Korean market name including brand and flavor/variant (e.g., \"이클립스 피치향\", \"코카콜라 제로\", \"오레오 더블 스터프\").\n"
                "2) If it is a chain-branded menu item with identifiable packaging, return \"<브랜드> <메뉴명>\" (e.g., \"맥도날드 빅맥\", \"스타벅스 카페 라떼\").\n"
                "3) Otherwise (homemade/restaurant dish without labels), return the specific dish name in Korean (e.g., \"김치볶음밥\", \"된장찌개\").\n"
                "Constraints:\n"
                "- Avoid generic categories like \"사탕\", \"과자\", \"음료\". Prefer the most specific name available from packaging or visual cues.\n"
                "- Do NOT add size, quantity, adjectives, or descriptions beyond the official product/dish name.\n"
                "- Read visible text on packaging to extract brand and flavor accurately.\n"
                "- If multiple items appear, choose the most prominent/centered/largest or most distinctive branded item.\n"
                "- If it's clearly not food, return \"Unknown\".\n"
            )
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Identify the single most salient food or beverage. "
                        "If it is a packaged product, return the exact Korean product name including brand and flavor (e.g., '이클립스 피치향'). "
                        "Otherwise, return the specific dish name. Respond only with the strict JSON schema."
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                }
            ]
        }
    ]

def _invoke_vision_model(client: OpenAI, model: str, base64_image: str):
    return client.chat.completions.create(
        model=model,
        messages=_build_messages(base64_image),
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=128,
    )

def preprocess_api_response(response: str) -> str:
    """
    API 응답에서 JSON 부분만 추출합니다.
    Markdown 코드 블록이나 다른 형식의 텍스트를 제거합니다.
    """
    if not response:
        return ""
    
    response = response.strip()
    
    # 먼저 전체 응답이 유효한 JSON인지 확인
    try:
        json.loads(response)
        return response
    except json.JSONDecodeError:
        pass
    
    # Markdown 코드 블록 제거 (```json ... ``` 또는 ``` ... ```)
    markdown_pattern = r'```(?:json)?\s*(\{[\s\S]*?\})\s*```'
    match = re.search(markdown_pattern, response, re.DOTALL)
    if match:
        return match.group(1).strip()
    
    # JSON 객체 부분만 추출하기 위한 정규 표현식 (중첩된 중괄호 처리)
    json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
    match = re.search(json_pattern, response, re.DOTALL)
    if match:
        extracted = match.group(0)
        # 추출된 JSON이 유효한지 확인
        try:
            json.loads(extracted)
            return extracted
        except json.JSONDecodeError:
            pass
    
    # 더 넓은 범위로 시도 (중첩 중괄호 포함)
    json_pattern_wide = r'\{.*\}'
    match = re.search(json_pattern_wide, response, re.DOTALL)
    if match:
        return match.group(0).strip()
    
    return response

def process_food_image(base64_image: str, user_id: int) -> dict:
    try:
        client = get_openai_client()
        response: Optional[Any] = None
        last_error: Optional[Exception] = None

        for model in (DEFAULT_VISION_MODEL, BACKUP_VISION_MODEL):
            try:
                logger.debug("Invoking vision model %s for user %s", model, user_id)
                candidate = _invoke_vision_model(client, model, base64_image)
                if candidate and candidate.choices and candidate.choices[0].message.content:
                    response = candidate
                    break
                logger.warning("Vision model %s returned empty choices for user %s", model, user_id)
            except OpenAIError as vision_error:
                last_error = vision_error
                logger.warning("Vision model %s failed with error: %s", model, str(vision_error))
                continue

        if response is None or not response.choices or not response.choices[0].message.content:
            if last_error:
                logger.error("Vision pipeline failed after trying all models: %s", str(last_error))
                return {"error": "OpenAI API error", "details": str(last_error)}
            logger.error("OpenAI API returned empty response")
            return {"error": "Empty response from API"}

        result = response.choices[0].message.content.strip()
        logger.debug("Raw OpenAI API response: %s", result)

        if not result:
            logger.error("OpenAI API returned empty content")
            return {"error": "Empty content in API response"}

        # API 응답 전처리
        preprocessed_result = preprocess_api_response(result)
        logger.debug("Preprocessed API response: %s", preprocessed_result)

        if not preprocessed_result:
            logger.error("Preprocessing resulted in empty string. Original: %s", result)
            return {"error": "Failed to extract JSON from API response"}

        try:
            data = json.loads(preprocessed_result)
        except json.JSONDecodeError as e:
            logger.error("JSON decode error: %s, Raw response: %s, Preprocessed: %s",
                        str(e), result, preprocessed_result)
            return {"error": "Failed to parse API response", "details": str(e)}

        # 응답 형식 검증 및 상세 로깅
        if not isinstance(data, dict):
            logger.error("API response is not a dict. Type: %s, Value: %s", type(data), data)
            return {"error": "Unexpected API response format: response is not a dictionary"}

        if "food_name" not in data:
            logger.error("API response missing 'food_name' key. Keys: %s, Full response: %s",
                        list(data.keys()) if isinstance(data, dict) else "N/A", data)
            return {"error": "Unexpected API response format: missing 'food_name' field"}

        getattr(FoodRecognitionLog, "objects").create(
            user_id=user_id,
            image_url="[Base64 image data not stored]",
            recognized_food=data["food_name"],
            confidence_score=0.8
        )

        return data

    except OpenAIError as e:
        logger.error("OpenAI API error: %s", str(e), exc_info=True)
        return {"error": "OpenAI API error", "details": str(e)}
    except Exception as e:
        logger.error("Unexpected error in process_food_image: %s", str(e), exc_info=True)
        return {"error": "Unexpected error occurred", "details": str(e)}
