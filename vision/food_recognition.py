import logging
import json
import re
from openai import OpenAI
from django.conf import settings
from .models import FoodRecognitionLog

logger = logging.getLogger(__name__)

client = OpenAI(api_key=settings.OPENAI_API_KEY)

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
    return response  # JSON을 찾지 못한 경우 원본 응답을 반환

def process_food_image(base64_image: str, user_id: int) -> dict:
    try:
        logger.debug(f"Received base64 image data length in process_food_image: {len(base64_image)}")

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "You are an advanced food recognition system. Identify the main food item in the image and determine if it's generally safe for consumption. Respond in the following JSON format:\n{\n  \"food_name\": \"[Name of the food]\"\n}\nIf you cannot identify the food or the image does not contain food, set the food_name to \"Unknown\""
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Identify the main food item in this image."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=100,
        )

        result = response.choices[0].message.content
        logger.debug(f"Raw OpenAI API response: {result}")
        
        # API 응답 전처리
        preprocessed_result = preprocess_api_response(result)
        logger.debug(f"Preprocessed API response: {preprocessed_result}")
        
        try:
            data = json.loads(preprocessed_result)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse preprocessed API response: {e}")
            logger.error(f"Preprocessed API response: {preprocessed_result}")
            return {"error": "Failed to parse API response", "details": str(e)}

        if not isinstance(data, dict) or "food_name" not in data:
            logger.error(f"Unexpected API response format: {data}")
            return {"error": "Unexpected API response format"}

        # Save recognition log
        FoodRecognitionLog.objects.create(
            user_id=user_id,
            image_url="[Base64 image data not stored]",  # In MVP, we're not storing the actual image
            recognized_food=data["food_name"],
            confidence_score=0.8  # Placeholder confidence score for MVP
        )
        
        return data

    except Exception as e:
        logger.exception("Unexpected error in process_food_image")
        return {"error": "Unexpected error occurred", "details": str(e)}
