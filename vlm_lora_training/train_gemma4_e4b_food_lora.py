import argparse
import json
from pathlib import Path

import torch
from peft import LoraConfig, PeftModel, TaskType, get_peft_model
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig, Trainer, TrainingArguments


def load_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def load_split(dataset_dir, split):
    from datasets import Dataset

    dataset_dir = Path(dataset_dir)
    rows = load_jsonl(dataset_dir / f"{split}.jsonl")
    normalized_rows = []
    for row in rows:
        normalized_rows.append(
            {
                "image_path": str(dataset_dir / row["image"]),
                "messages_json": json.dumps(row["messages"], ensure_ascii=False),
            }
        )
    return Dataset.from_list(normalized_rows)


def extract_message_text(messages, role):
    for message in messages:
        if message.get("role") != role:
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "\n".join(part for part in parts if part)
    return ""


def format_training_text(messages, eos_token):
    system_text = extract_message_text(messages, "system")
    user_text = extract_message_text(messages, "user")
    assistant_text = extract_message_text(messages, "assistant")
    prompt = (
        "<|image|>\n"
        f"System: {system_text}\n"
        f"User: {user_text}\n"
        "Assistant:"
    )
    full_text = f"{prompt} {assistant_text}{eos_token}"
    return prompt, full_text


def make_collator(processor):
    image_token_id = processor.tokenizer.convert_tokens_to_ids("<|image|>")

    def collate_fn(examples):
        prompt_texts = []
        full_texts = []
        images = []
        for example in examples:
            messages = json.loads(example["messages_json"])
            prompt_text, full_text = format_training_text(messages, processor.tokenizer.eos_token)
            prompt_texts.append(prompt_text)
            full_texts.append(full_text)
            images.append(Image.open(example["image_path"]).convert("RGB"))

        prompt_batch = processor(text=prompt_texts, images=images, return_tensors="pt", padding=True)
        batch = processor(text=full_texts, images=images, return_tensors="pt", padding=True)
        labels = batch["input_ids"].clone()
        labels[labels == processor.tokenizer.pad_token_id] = -100
        if image_token_id is not None:
            labels[labels == image_token_id] = -100
        prompt_lengths = prompt_batch["attention_mask"].sum(dim=1)
        for row_idx, prompt_length in enumerate(prompt_lengths.tolist()):
            labels[row_idx, :prompt_length] = -100
        batch["labels"] = labels
        return batch

    return collate_fn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", default="google/gemma-4-E4B")
    parser.add_argument("--dataset-dir", default="vlm_lora_training/data/food_vlm_sft_smoke")
    parser.add_argument("--output-dir", default="vlm_lora_training/outputs/gemma4-e4b-food-lora")
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--adapter-dir", default=None)
    parser.add_argument("--logging-steps", type=int, default=5)
    parser.add_argument("--eval-steps", type=int, default=None)
    parser.add_argument("--save-steps", type=int, default=None)
    parser.add_argument("--resume-from-checkpoint", default=None)
    parser.add_argument("--use-4bit", action="store_true")
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available. Gemma E4B LoRA training needs the NVIDIA GPU.")

    processor = AutoProcessor.from_pretrained(args.model_id)

    model_kwargs = {
        "dtype": torch.bfloat16,
        "device_map": "auto",
    }
    if args.use_4bit:
        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
        )

    model = AutoModelForImageTextToText.from_pretrained(args.model_id, **model_kwargs)
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    if hasattr(model, "enable_input_require_grads"):
        model.enable_input_require_grads()

    train_dataset = load_split(args.dataset_dir, "train")
    eval_dataset = load_split(args.dataset_dir, "val")

    if args.adapter_dir:
        model = PeftModel.from_pretrained(model, args.adapter_dir, is_trainable=True)
    else:
        peft_config = LoraConfig(
            task_type=TaskType.CAUSAL_LM,
            r=args.lora_r,
            lora_alpha=args.lora_alpha,
            lora_dropout=0.05,
            target_modules=[
                "q_proj.linear",
                "k_proj.linear",
                "v_proj.linear",
                "o_proj.linear",
                "gate_proj.linear",
                "up_proj.linear",
                "down_proj.linear",
            ],
        )
        model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    config = TrainingArguments(
        output_dir=args.output_dir,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.learning_rate,
        bf16=True,
        logging_steps=args.logging_steps,
        eval_strategy="steps",
        eval_steps=args.eval_steps or max(10, min(args.max_steps, 50)),
        save_steps=args.save_steps or max(10, min(args.max_steps, 50)),
        save_total_limit=2,
        gradient_checkpointing=True,
        remove_unused_columns=False,
        report_to=["tensorboard"],
    )

    trainer = Trainer(
        model=model,
        args=config,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=make_collator(processor),
    )
    trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    trainer.save_model(args.output_dir)
    processor.save_pretrained(args.output_dir)


if __name__ == "__main__":
    main()
