import argparse
import json
import random
from pathlib import Path

from datasets import load_dataset
from PIL import Image
from tqdm import tqdm


SYSTEM_PROMPT = (
    "You are a food recognition vision model. Return only compact JSON. "
    "Identify food, drink, or packaged food items visible in the image. "
    "Do not invent an item when the image is unclear."
)

USER_PROMPT = (
    "Analyze this food-related image. Return JSON with keys: "
    "image_type, is_food, detected_items, visible_text, needs_clarification. "
    "detected_items must be a list of objects with food_name, item_type, and confidence."
)

FOOD_PRODUCT_KEYWORDS = {
    "chocolate",
    "lays",
    "pringles",
    "water",
    "energydrink",
    "ketchup",
    "mayo",
    "pesto",
    "pomodoro",
    "lasagne",
}


def normalize_name(value):
    return str(value).strip().replace("_", " ").replace("-", " ")


def answer_json(image_type, is_food, items, visible_text="", needs_clarification=False):
    return json.dumps(
        {
            "image_type": image_type,
            "is_food": bool(is_food),
            "detected_items": items,
            "visible_text": visible_text,
            "needs_clarification": bool(needs_clarification),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def json_field(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def truthy_food_flag(value):
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    return str(value).strip().lower() in {"1", "true", "yes", "food"}


def message_record(image_rel_path, assistant_text):
    return {
        "image": image_rel_path,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image"},
                    {"type": "text", "text": USER_PROMPT},
                ],
            },
            {"role": "assistant", "content": assistant_text},
        ],
    }


def save_image(image, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not isinstance(image, Image.Image):
        raise TypeError(f"expected PIL image, got {type(image)}")
    image.convert("RGB").save(path, format="JPEG", quality=92)


def add_food101(records, image_dir, max_rows):
    ds = load_dataset("ethz/food101", split="train", streaming=True)
    names = ds.features["label"].names
    for idx, sample in enumerate(tqdm(ds, total=max_rows, desc="food101")):
        if idx >= max_rows:
            break
        label = names[int(sample["label"])]
        food_name = normalize_name(label)
        rel = f"images/food101_{idx:07d}.jpg"
        save_image(sample["image"], image_dir / f"food101_{idx:07d}.jpg")
        assistant = answer_json(
            "cooked_food",
            True,
            [{"food_name": food_name, "item_type": "dish", "confidence": 1.0}],
        )
        records.append(message_record(rel, assistant))


def add_vlm_food4k(records, image_dir, max_rows):
    ds = load_dataset("berkeruveyik/vlm-food-4k-not-food-dataset", split="train", streaming=True)
    count = 0
    for sample in tqdm(ds, total=max_rows, desc="vlm-food-4k"):
        output = json_field(sample.get("output_json"))
        if not truthy_food_flag(output.get("is_food")):
            continue
        if count >= max_rows:
            break
        title = normalize_name(sample.get("food270_class_name") or sample.get("category") or output.get("image_title"))
        items = output.get("food_items") or [title]
        detected = [
            {"food_name": normalize_name(item), "item_type": "food_or_ingredient", "confidence": 0.9}
            for item in items
            if str(item).strip()
        ]
        if not any(item["food_name"] == title for item in detected):
            detected.insert(0, {"food_name": title, "item_type": "dish", "confidence": 1.0})
        rel = f"images/vlm_food4k_{count:07d}.jpg"
        save_image(sample["image"], image_dir / f"vlm_food4k_{count:07d}.jpg")
        records.append(message_record(rel, answer_json("cooked_food", True, detected)))
        count += 1


def is_mimex_food(product_name):
    product = str(product_name).lower()
    return any(keyword in product for keyword in FOOD_PRODUCT_KEYWORDS)


def add_mimex(records, image_dir, max_rows):
    ds = load_dataset("Anilot/MIMEX", split="train", streaming=True)
    count = 0
    for sample in tqdm(ds, total=max_rows, desc="mimex-food-products"):
        product_name = sample.get("product_name", "")
        if not is_mimex_food(product_name):
            continue
        if count >= max_rows:
            break
        food_name = normalize_name(product_name)
        rel = f"images/mimex_{count:07d}.jpg"
        save_image(sample["image"], image_dir / f"mimex_{count:07d}.jpg")
        assistant = answer_json(
            "packaged_food",
            True,
            [{"food_name": food_name, "item_type": "packaged_food_or_drink", "confidence": 1.0}],
        )
        records.append(message_record(rel, assistant))
        count += 1


def add_openfoodfacts_front(records, image_dir, max_rows):
    ds = load_dataset("openfoodfacts/front_image_classification", split="train", streaming=True)
    count = 0
    for sample in tqdm(ds, total=max_rows, desc="off-front"):
        if count >= max_rows:
            break
        category = sample.get("category_name", "unknown")
        rel = f"images/off_front_{count:07d}.jpg"
        save_image(sample["image"], image_dir / f"off_front_{count:07d}.jpg")
        image_type = "packaged_food_front" if category == "front" else "packaged_food_other"
        assistant = answer_json(
            image_type,
            True,
            [{"food_name": "unknown packaged food", "item_type": image_type, "confidence": 0.5}],
            needs_clarification=True,
        )
        records.append(message_record(rel, assistant))
        count += 1


def add_datacomp(records, image_dir, max_rows):
    ds = load_dataset("mrdbourke/DataComp-1B-food-and-drink-3M", split="train", streaming=True)
    count = 0
    for sample in tqdm(ds, total=max_rows, desc="datacomp-food"):
        if count >= max_rows:
            break
        if sample.get("quality_tier") != "gold":
            continue
        if not bool(sample.get("siglip2_is_food_or_drink")):
            continue
        top_prompt = normalize_name(sample.get("siglip2_top_prompt") or sample.get("caption") or "food or drink")
        rel = f"images/datacomp_{count:07d}.jpg"
        save_image(sample["image"], image_dir / f"datacomp_{count:07d}.jpg")
        assistant = answer_json(
            "food_or_drink",
            True,
            [{"food_name": top_prompt, "item_type": "food_or_drink", "confidence": float(sample.get("siglip2_score") or 0.7)}],
        )
        records.append(message_record(rel, assistant))
        count += 1


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="vlm_lora_training/data/food_vlm_sft_smoke")
    parser.add_argument("--max-per-source", type=int, default=200)
    parser.add_argument("--val-ratio", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--include-datacomp", action="store_true")
    args = parser.parse_args()

    random.seed(args.seed)
    output_dir = Path(args.output_dir)
    image_dir = output_dir / "images"
    records = []

    add_food101(records, image_dir, args.max_per_source)
    add_vlm_food4k(records, image_dir, args.max_per_source)
    add_mimex(records, image_dir, args.max_per_source)
    add_openfoodfacts_front(records, image_dir, min(args.max_per_source, 1000))
    if args.include_datacomp:
        add_datacomp(records, image_dir, args.max_per_source)

    random.shuffle(records)
    val_count = max(1, int(len(records) * args.val_ratio))
    val_rows = records[:val_count]
    train_rows = records[val_count:]

    write_jsonl(output_dir / "train.jsonl", train_rows)
    write_jsonl(output_dir / "val.jsonl", val_rows)
    summary = {
        "total": len(records),
        "train": len(train_rows),
        "val": len(val_rows),
        "include_datacomp": args.include_datacomp,
        "max_per_source": args.max_per_source,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
