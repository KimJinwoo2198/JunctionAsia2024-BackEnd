# Gemma E4B Food VLM LoRA

This folder prepares food-image-heavy VLM SFT data and trains a LoRA adapter for
`google/gemma-4-E4B`.

The dataset mix intentionally avoids receipt, forum, board, and document-heavy
sets. It prioritizes:

- cooked food photos
- food/drink product images
- package/front images
- JSON-style food item extraction examples

## Prepare Data

On Windows, run the training commands with UTF-8 mode enabled so Python package
templates do not fall back to the local ANSI codepage:

```powershell
$env:PYTHONUTF8='1'
```

For an RTX 50-series GPU, install CUDA 13.0 PyTorch wheels after installing
`requirements.txt`:

```powershell
python -m pip install --upgrade --force-reinstall torch==2.12.0+cu130 torchvision==0.27.0+cu130 --index-url https://download.pytorch.org/whl/cu130
python -m pip install "fsspec[http]==2026.2.0"
```

Small smoke dataset:

```powershell
python vlm_lora_training\prepare_food_vlm_sft.py --max-per-source 200 --output-dir vlm_lora_training\data\food_vlm_sft_smoke
```

Larger first run:

```powershell
python vlm_lora_training\prepare_food_vlm_sft.py --max-per-source 3000 --output-dir vlm_lora_training\data\food_vlm_sft
```

Optional large web-image source:

```powershell
python vlm_lora_training\prepare_food_vlm_sft.py --include-datacomp --max-per-source 3000 --output-dir vlm_lora_training\data\food_vlm_sft
```

## Train

Smoke train:

```powershell
python vlm_lora_training\train_gemma4_e4b_food_lora.py --dataset-dir vlm_lora_training\data\food_vlm_sft_smoke --max-steps 20
```

Longer train:

```powershell
python vlm_lora_training\train_gemma4_e4b_food_lora.py --dataset-dir vlm_lora_training\data\food_vlm_sft --max-steps 1000 --output-dir vlm_lora_training\outputs\gemma4-e4b-food-lora
```

The script defaults to bf16 LoRA rather than 4-bit QLoRA because Windows
`bitsandbytes` compatibility can be uneven. Use `--use-4bit` only after the
environment confirms that bitsandbytes CUDA kernels work.

Verified local run:

```powershell
python vlm_lora_training\prepare_food_vlm_sft.py --max-per-source 3000 --output-dir vlm_lora_training\data\food_vlm_sft
python vlm_lora_training\train_gemma4_e4b_food_lora.py --dataset-dir vlm_lora_training\data\food_vlm_sft --max-steps 100 --output-dir vlm_lora_training\outputs\gemma4-e4b-food-lora-100step
python vlm_lora_training\train_gemma4_e4b_food_lora.py --dataset-dir vlm_lora_training\data\food_vlm_sft --adapter-dir vlm_lora_training\outputs\gemma4-e4b-food-lora-100step\checkpoint-100 --max-steps 900 --output-dir vlm_lora_training\outputs\gemma4-e4b-food-lora-1000step
```

That run produced 9,696 image samples and a 1000-step LoRA adapter. Runtime
inference uses the checked-in minimal adapter files under
`vlm_lora_adapter/gemma4-e4b-food-lora-1000step`.

Final validation and smoke-test summary:

- eval loss: 0.09397
- held-out sample JSON parse: 30/30
- strict name match: 20/30
