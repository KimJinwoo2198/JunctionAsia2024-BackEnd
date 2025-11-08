import logging
import json
import re
from openai import OpenAI, OpenAIError
from django.conf import settings
from vision.models import FoodRecognitionLog

logger = logging.getLogger(__name__)

def get_openai_client() -> OpenAI:
    api_key = settings.OPENAI_API_KEY
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=api_key)

def preprocess_api_response(response: str) -> str:
    """
    API 응답에서 JSON 부분만 추출합니다.
    Markdown 코드 블록이나 다른 형식의 텍스트를 제거합니다.
    """
    # JSON 부분만 추출하기 위한 정규 표현식
    json_pattern = r'\{[\s\S]*\}'
    match = re.search(json_pattern, response)
    if match:
        return match.group(0)
    return response

def process_food_image(base64_image: str, user_id: int) -> dict:
    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert food vision labeler. Identify ONLY the single most salient food or beverage in the image and output its exact name in Korean.\n"
                        "Follow these rules strictly and return JSON only.\n\n"
                        "Output format (strict JSON):\\n{\\n  \"food_name\": \"<정확한 이름(한국어)>\"\\n}\\n\n"
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
                        {"type": "text", "text": "Identify the single most salient food or beverage. If it is a packaged product, return the exact Korean product name including brand and flavor (e.g., '이클립스 피치향'). Otherwise, return the specific dish name. Respond only with the strict JSON schema."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            response_format={"type": "json_object"},
        )

        result = response.choices[0].message.content
        logger.debug("Raw OpenAI API response: %s", result)

        # API 응답 전처리
        preprocessed_result = preprocess_api_response(result)
        logger.debug("Preprocessed API response: %s", preprocessed_result)

        try:
            data = json.loads(preprocessed_result)
        except json.JSONDecodeError as e:
            return {"error": "Failed to parse API response", "details": str(e)}

        if not isinstance(data, dict) or "food_name" not in data:
            return {"error": "Unexpected API response format"}

        getattr(FoodRecognitionLog, "objects").create(
            user_id=user_id,
            image_url="[Base64 image data not stored]",
            recognized_food=data["food_name"],
            confidence_score=0.8
        )

        return data

    except OpenAIError as e:
        return {"error": "OpenAI API error", "details": str(e)}
