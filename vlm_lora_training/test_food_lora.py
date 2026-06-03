import argparse
import json
import random
from pathlib import Path

import torch
from peft import PeftModel
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor

from train_gemma4_e4b_food_lora import extract_message_text


def load_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def normalize(value):
    return str(value).lower().replace("_", " ").replace("-", " ").strip()


def extract_json(text):
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def expected_name(messages):
    assistant = extract_message_text(messages, "assistant")
    parsed = extract_json(assistant)
    if not parsed:
        return ""
    items = parsed.get("detected_items") or []
    if not items:
        return ""
    return normalize(items[0].get("food_name", ""))


def predicted_names(parsed):
    if not parsed:
        return []
    items = parsed.get("detected_items") or []
    return [normalize(item.get("food_name", "")) for item in items if item.get("food_name")]


def is_match(expected, predictions):
    if not expected or not predictions:
        return False
    for prediction in predictions:
        if expected == prediction:
            return True
        if expected in prediction or prediction in expected:
            return True
    return False


def build_prompt(messages):
    system_text = extract_message_text(messages, "system")
    user_text = extract_message_text(messages, "user")
    return (
        "<|image|>\n"
        f"System: {system_text}\n"
        f"User: {user_text}\n"
        "Assistant:"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", default="google/gemma-4-E4B")
    parser.add_argument("--adapter-dir", required=True)
    parser.add_argument("--dataset-dir", default="vlm_lora_training/data/food_vlm_sft")
    parser.add_argument("--split", default="val")
    parser.add_argument("--num-samples", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-jsonl", default=None)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available.")

    random.seed(args.seed)
    dataset_dir = Path(args.dataset_dir)
    rows = load_jsonl(dataset_dir / f"{args.split}.jsonl")
    rows = random.sample(rows, min(args.num_samples, len(rows)))

    processor = AutoProcessor.from_pretrained(args.model_id)
    base_model = AutoModelForImageTextToText.from_pretrained(
        args.model_id,
        dtype=torch.bfloat16,
        device_map="auto",
    )
    model = PeftModel.from_pretrained(base_model, args.adapter_dir)
    model.eval()

    results = []
    matches = 0
    parse_success = 0

    for idx, row in enumerate(rows):
        messages = row["messages"]
        expected = expected_name(messages)
        image_path = dataset_dir / row["image"]
        prompt = build_prompt(messages)
        image = Image.open(image_path).convert("RGB")
        inputs = processor(text=[prompt], images=[image], return_tensors="pt")
        inputs = {key: value.to(model.device) for key, value in inputs.items()}

        with torch.inference_mode():
            output_ids = model.generate(
                **inputs,
                do_sample=False,
                max_new_tokens=160,
                eos_token_id=processor.tokenizer.eos_token_id,
                pad_token_id=processor.tokenizer.pad_token_id,
            )

        generated_ids = output_ids[0, inputs["input_ids"].shape[1] :]
        text = processor.tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
        parsed = extract_json(text)
        predictions = predicted_names(parsed)
        matched = is_match(expected, predictions)
        matches += int(matched)
        parse_success += int(parsed is not None)

        result = {
            "idx": idx,
            "image": row["image"],
            "expected": expected,
            "predictions": predictions,
            "matched": matched,
            "parsed": parsed is not None,
            "raw": text,
        }
        results.append(result)
        print(json.dumps(result, ensure_ascii=False))

    summary = {
        "samples": len(results),
        "json_parse_rate": parse_success / len(results) if results else 0.0,
        "name_match_rate": matches / len(results) if results else 0.0,
        "matches": matches,
    }
    print(json.dumps({"summary": summary}, ensure_ascii=False, indent=2))

    if args.output_jsonl:
        output_path = Path(args.output_jsonl)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            for result in results:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
            f.write(json.dumps({"summary": summary}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
