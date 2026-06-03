import json
import logging
import os
import re
import threading
from base64 import b64decode
from io import BytesIO
from typing import Any, Iterable, Optional

import requests
from django.conf import settings
from openai import OpenAI, OpenAIError
from vision.models import FoodRecognitionLog

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_VISION_MODELS = ("gpt-4o", "gpt-4o-mini")
DEFAULT_LOCAL_VISION_MODEL = "gemma4:e4b"
LOCAL_VISION_TIMEOUT_SECONDS = 120
DEFAULT_LOCAL_VLM_MODEL_ID = "google/gemma-4-E4B"
DEFAULT_LOCAL_VLM_ADAPTER_DIR = "vlm_lora_training/outputs/gemma4-e4b-food-lora-1000step"
DEFAULT_LOCAL_VLM_MAX_NEW_TOKENS = 160

_LOCAL_VLM_LOCK = threading.Lock()
_LOCAL_VLM_PROCESSOR = None
_LOCAL_VLM_MODEL = None

FOOD_RECOGNITION_SCHEMA = {
    "type": "object",
    "properties": {
        "food_name": {"type": "string"},
    },
    "required": ["food_name"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You are an expert food vision labeler. Identify only the single most "
    "salient food or beverage in the image and output its exact name in Korean. "
    "Return strict JSON only with this schema: {\"food_name\": \"...\"}. "
    "If it is a packaged or branded product with visible label, logo, or text, "
    "return the exact Korean market name including brand and flavor or variant. "
    "If it is a chain-branded menu item with identifiable packaging, include the "
    "brand and menu item name. Otherwise return the specific dish name in Korean. "
    "Avoid generic categories such as food, snack, drink, meal, or dessert. "
    "Do not add size, quantity, adjectives, or explanations. If multiple items "
    "appear, choose the most prominent, centered, largest, or most distinctive "
    "branded item. If it is clearly not food, return Unknown."
)

USER_PROMPT = (
    "Identify the single most salient food or beverage. Return only strict JSON "
    "like {\"food_name\": \"...\"}."
)

LOCAL_VLM_SYSTEM_PROMPT = (
    "You are a food recognition vision model. Return only compact JSON. "
    "Identify food, drink, or packaged food items visible in the image. "
    "Do not invent an item when the image is unclear."
)

LOCAL_VLM_USER_PROMPT = (
    "Analyze this food-related image. Return JSON with keys: "
    "image_type, is_food, detected_items, visible_text, needs_clarification. "
    "detected_items must be a list of objects with food_name, item_type, and confidence."
)

UNKNOWN_LOCAL_VLM_NAMES = {
    "",
    "unknown",
    "unknown food",
    "unknown_food",
    "unknown packaged food",
    "unknown_packaged_food",
}


def _as_model_tuple(value: Any, fallback: Iterable[str]) -> tuple[str, ...]:
    if not value:
        return tuple(fallback)
    if isinstance(value, str):
        return tuple(model.strip() for model in value.split(",") if model.strip())
    return tuple(value)


def _setting(name: str, default: Any = None) -> Any:
    return getattr(settings, name, os.getenv(name, default))


def _vision_provider() -> str:
    return _setting("VISION_PROVIDER", "openai").strip().lower()


def _setting_bool(name: str, default: bool = False) -> bool:
    value = str(_setting(name, str(default))).strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def get_openai_client() -> OpenAI:
    api_key = _setting("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=api_key)


def _openai_vision_models() -> tuple[str, ...]:
    configured_models = _setting("OPENAI_VISION_MODELS")
    if configured_models:
        return _as_model_tuple(configured_models, DEFAULT_OPENAI_VISION_MODELS)

    primary_model = _setting("OPENAI_VISION_MODEL", DEFAULT_OPENAI_VISION_MODELS[0])
    backup_model = _setting("OPENAI_BACKUP_VISION_MODEL", DEFAULT_OPENAI_VISION_MODELS[1])
    return tuple(model for model in (primary_model, backup_model) if model)


def _build_openai_messages(base64_image: str) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": USER_PROMPT,
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}",
                    },
                },
            ],
        },
    ]


def _invoke_openai_vision_model(client: OpenAI, model: str, base64_image: str):
    return client.chat.completions.create(
        model=model,
        messages=_build_openai_messages(base64_image),
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=128,
    )


def _ollama_base_url() -> str:
    return _setting("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")


def _ollama_vision_models() -> tuple[str, ...]:
    configured_models = _setting("OLLAMA_VISION_MODELS")
    if configured_models:
        return _as_model_tuple(configured_models, (DEFAULT_LOCAL_VISION_MODEL,))

    primary_model = _setting("OLLAMA_VISION_MODEL", DEFAULT_LOCAL_VISION_MODEL)
    backup_model = _setting("OLLAMA_BACKUP_VISION_MODEL", "")
    return tuple(model for model in (primary_model, backup_model) if model)


def _invoke_ollama_vision_model(model: str, base64_image: str) -> str:
    timeout = int(_setting("OLLAMA_TIMEOUT_SECONDS", LOCAL_VISION_TIMEOUT_SECONDS))
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": USER_PROMPT,
                "images": [base64_image],
            },
        ],
        "format": FOOD_RECOGNITION_SCHEMA,
        "think": False,
        "stream": False,
        "options": {
            "temperature": 0,
            "num_predict": 128,
        },
    }

    response = requests.post(
        f"{_ollama_base_url()}/api/chat",
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    response_data = response.json()
    content = response_data.get("message", {}).get("content", "")
    if not content:
        raise ValueError("Ollama returned an empty response")
    return content


def _local_vlm_adapter_dir() -> str:
    return str(_setting("LOCAL_VLM_ADAPTER_DIR", DEFAULT_LOCAL_VLM_ADAPTER_DIR))


def _local_vlm_model_id() -> str:
    return str(_setting("LOCAL_VLM_MODEL_ID", DEFAULT_LOCAL_VLM_MODEL_ID))


def _local_vlm_max_new_tokens() -> int:
    return int(_setting("LOCAL_VLM_MAX_NEW_TOKENS", DEFAULT_LOCAL_VLM_MAX_NEW_TOKENS))


def _build_local_vlm_prompt() -> str:
    return (
        "<|image|>\n"
        f"System: {LOCAL_VLM_SYSTEM_PROMPT}\n"
        f"User: {LOCAL_VLM_USER_PROMPT}\n"
        "Assistant:"
    )


def _decode_base64_image(base64_image: str):
    from PIL import Image

    image_bytes = b64decode(base64_image, validate=False)
    return Image.open(BytesIO(image_bytes)).convert("RGB")


def _local_vlm_dtype(torch_module):
    dtype_name = str(_setting("LOCAL_VLM_TORCH_DTYPE", "bfloat16")).strip().lower()
    if dtype_name in {"bf16", "bfloat16"}:
        return torch_module.bfloat16
    if dtype_name in {"fp16", "float16", "half"}:
        return torch_module.float16
    if dtype_name in {"fp32", "float32"}:
        return torch_module.float32
    raise ValueError(f"Unsupported LOCAL_VLM_TORCH_DTYPE: {dtype_name}")


def _load_local_vlm():
    global _LOCAL_VLM_MODEL, _LOCAL_VLM_PROCESSOR

    if _LOCAL_VLM_MODEL is not None and _LOCAL_VLM_PROCESSOR is not None:
        return _LOCAL_VLM_PROCESSOR, _LOCAL_VLM_MODEL

    with _LOCAL_VLM_LOCK:
        if _LOCAL_VLM_MODEL is not None and _LOCAL_VLM_PROCESSOR is not None:
            return _LOCAL_VLM_PROCESSOR, _LOCAL_VLM_MODEL

        try:
            import torch
            from peft import PeftModel
            from transformers import AutoModelForImageTextToText, AutoProcessor
        except ImportError as exc:
            raise RuntimeError(
                "Local VLM dependencies are missing. Install torch, transformers, peft, "
                "accelerate, safetensors, sentencepiece, and protobuf."
            ) from exc

        if _setting_bool("LOCAL_VLM_REQUIRE_CUDA", True) and not torch.cuda.is_available():
            raise RuntimeError("LOCAL_VLM_REQUIRE_CUDA is true, but CUDA is not available.")

        adapter_dir = _local_vlm_adapter_dir()
        if not os.path.exists(adapter_dir):
            raise RuntimeError(f"LOCAL_VLM_ADAPTER_DIR does not exist: {adapter_dir}")

        model_id = _local_vlm_model_id()
        device_map = str(_setting("LOCAL_VLM_DEVICE_MAP", "auto")).strip()
        model_kwargs = {"dtype": _local_vlm_dtype(torch)}
        if device_map:
            model_kwargs["device_map"] = device_map

        logger.info("Loading local VLM base model %s with adapter %s", model_id, adapter_dir)
        processor = AutoProcessor.from_pretrained(model_id)
        base_model = AutoModelForImageTextToText.from_pretrained(model_id, **model_kwargs)
        model = PeftModel.from_pretrained(base_model, adapter_dir)
        model.eval()

        _LOCAL_VLM_PROCESSOR = processor
        _LOCAL_VLM_MODEL = model
        return processor, model


def _model_input_device(model):
    device = getattr(model, "device", None)
    if device is not None:
        return device
    return next(model.parameters()).device


def _invoke_local_lora_vision_model(base64_image: str) -> str:
    import torch

    processor, model = _load_local_vlm()
    image = _decode_base64_image(base64_image)
    inputs = processor(text=[_build_local_vlm_prompt()], images=[image], return_tensors="pt")
    input_device = _model_input_device(model)
    inputs = {key: value.to(input_device) if hasattr(value, "to") else value for key, value in inputs.items()}

    with torch.inference_mode():
        output_ids = model.generate(
            **inputs,
            do_sample=False,
            max_new_tokens=_local_vlm_max_new_tokens(),
            eos_token_id=processor.tokenizer.eos_token_id,
            pad_token_id=processor.tokenizer.pad_token_id,
        )

    generated_ids = output_ids[0, inputs["input_ids"].shape[1] :]
    return processor.tokenizer.decode(generated_ids, skip_special_tokens=True).strip()


def _local_lora_food_name(raw_result: str) -> str:
    preprocessed = preprocess_api_response(raw_result)
    parsed = json.loads(preprocessed)
    if not isinstance(parsed, dict):
        raise ValueError("Local VLM response is not a JSON object")

    if parsed.get("is_food") is False:
        return "Unknown"

    if isinstance(parsed.get("food_name"), str):
        food_name = parsed["food_name"].strip()
    else:
        detected_items = parsed.get("detected_items") or []
        if not isinstance(detected_items, list) or not detected_items:
            return "Unknown"

        def confidence(item: Any) -> float:
            if not isinstance(item, dict):
                return 0.0
            try:
                return float(item.get("confidence", 0.0))
            except (TypeError, ValueError):
                return 0.0

        best_item = max((item for item in detected_items if isinstance(item, dict)), key=confidence, default={})
        food_name = str(best_item.get("food_name", "")).strip()

    normalized = food_name.lower().replace("-", " ").strip()
    if normalized in UNKNOWN_LOCAL_VLM_NAMES:
        return "Unknown"
    return food_name or "Unknown"


def preprocess_api_response(response: str) -> str:
    """
    Extract the JSON object from a model response.
    """
    if not response:
        return ""

    response = response.strip()

    try:
        json.loads(response)
        return response
    except json.JSONDecodeError:
        pass

    markdown_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    match = re.search(markdown_pattern, response, re.DOTALL)
    if match:
        extracted = match.group(1).strip()
        try:
            json.loads(extracted)
            return extracted
        except json.JSONDecodeError:
            pass

    json_pattern = r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
    match = re.search(json_pattern, response, re.DOTALL)
    if match:
        extracted = match.group(0)
        try:
            json.loads(extracted)
            return extracted
        except json.JSONDecodeError:
            pass

    json_pattern_wide = r"\{.*\}"
    match = re.search(json_pattern_wide, response, re.DOTALL)
    if match:
        return match.group(0).strip()

    return response


def _save_food_recognition(data: dict, user_id: int) -> dict:
    getattr(FoodRecognitionLog, "objects").create(
        user_id=user_id,
        image_url="[Base64 image data not stored]",
        recognized_food=data["food_name"],
        confidence_score=0.8,
    )
    return data


def _parse_and_log_food_response(raw_result: str, user_id: int, provider_name: str) -> dict:
    result = raw_result.strip()
    logger.debug("Raw %s vision response: %s", provider_name, result)

    if not result:
        logger.error("%s returned empty content", provider_name)
        return {"error": "Empty content in API response"}

    preprocessed_result = preprocess_api_response(result)
    logger.debug("Preprocessed %s vision response: %s", provider_name, preprocessed_result)

    if not preprocessed_result:
        logger.error("Preprocessing resulted in empty string. Original: %s", result)
        return {"error": "Failed to extract JSON from API response"}

    try:
        data = json.loads(preprocessed_result)
    except json.JSONDecodeError as e:
        logger.error(
            "JSON decode error: %s, Raw response: %s, Preprocessed: %s",
            str(e),
            result,
            preprocessed_result,
        )
        return {"error": "Failed to parse API response", "details": str(e)}

    if not isinstance(data, dict):
        logger.error("API response is not a dict. Type: %s, Value: %s", type(data), data)
        return {"error": "Unexpected API response format: response is not a dictionary"}

    if "food_name" not in data:
        logger.error(
            "API response missing 'food_name' key. Keys: %s, Full response: %s",
            list(data.keys()),
            data,
        )
        return {"error": "Unexpected API response format: missing 'food_name' field"}

    return _save_food_recognition(data, user_id)


def _recognize_with_openai(base64_image: str, user_id: int) -> dict:
    client = get_openai_client()
    response: Optional[Any] = None
    last_error: Optional[Exception] = None

    for model in _openai_vision_models():
        try:
            logger.debug("Invoking OpenAI vision model %s for user %s", model, user_id)
            candidate = _invoke_openai_vision_model(client, model, base64_image)
            if candidate and candidate.choices and candidate.choices[0].message.content:
                response = candidate
                break
            logger.warning("OpenAI vision model %s returned empty choices for user %s", model, user_id)
        except OpenAIError as vision_error:
            last_error = vision_error
            logger.warning("OpenAI vision model %s failed with error: %s", model, str(vision_error))
            continue

    if response is None or not response.choices or not response.choices[0].message.content:
        if last_error:
            logger.error("OpenAI vision pipeline failed after trying all models: %s", str(last_error))
            return {"error": "OpenAI API error", "details": str(last_error)}
        logger.error("OpenAI API returned empty response")
        return {"error": "Empty response from API"}

    return _parse_and_log_food_response(
        raw_result=response.choices[0].message.content,
        user_id=user_id,
        provider_name="OpenAI",
    )


def _recognize_with_ollama(base64_image: str, user_id: int) -> dict:
    last_error: Optional[Exception] = None

    for model in _ollama_vision_models():
        try:
            logger.debug("Invoking Ollama vision model %s for user %s", model, user_id)
            return _parse_and_log_food_response(
                raw_result=_invoke_ollama_vision_model(model, base64_image),
                user_id=user_id,
                provider_name="Ollama",
            )
        except (requests.RequestException, ValueError, json.JSONDecodeError) as vision_error:
            last_error = vision_error
            logger.warning("Ollama vision model %s failed with error: %s", model, str(vision_error))
            continue

    if last_error:
        logger.error("Ollama vision pipeline failed after trying all models: %s", str(last_error))
        return {"error": "Ollama API error", "details": str(last_error)}
    return {"error": "No Ollama vision model configured"}


def _recognize_with_local_lora(base64_image: str, user_id: int) -> dict:
    try:
        raw_result = _invoke_local_lora_vision_model(base64_image)
        logger.debug("Raw local LoRA vision response: %s", raw_result)
        food_name = _local_lora_food_name(raw_result)
        return _save_food_recognition({"food_name": food_name}, user_id)
    except (RuntimeError, ValueError, json.JSONDecodeError) as vision_error:
        logger.error("Local LoRA vision pipeline failed: %s", str(vision_error), exc_info=True)
        return {"error": "Local LoRA vision error", "details": str(vision_error)}


def process_food_image(base64_image: str, user_id: int) -> dict:
    try:
        provider = _vision_provider()
        if provider in {"lora", "local_lora", "peft", "gemma_lora"}:
            return _recognize_with_local_lora(base64_image, user_id)
        if provider in {"ollama", "local"}:
            return _recognize_with_ollama(base64_image, user_id)
        return _recognize_with_openai(base64_image, user_id)
    except OpenAIError as e:
        logger.error("OpenAI API error: %s", str(e), exc_info=True)
        return {"error": "OpenAI API error", "details": str(e)}
    except Exception as e:
        logger.error("Unexpected error in process_food_image: %s", str(e), exc_info=True)
        return {"error": "Unexpected error occurred", "details": str(e)}
