# Gemma E4B Food Vision LoRA Adapter

This directory contains the trained PEFT LoRA adapter used by the backend when
`VISION_PROVIDER=lora`.

Included files:

- `adapter_config.json`
- `adapter_model.safetensors`

The Gemma base model is not stored in this repository. At runtime the backend
loads `google/gemma-4-E4B` and applies this adapter.

Training summary:

- Dataset samples: 9,696 total, 9,212 train, 484 validation
- Training: 100 starter steps + 900 resumed steps
- Final eval loss: 0.09397
- Held-out sample test: JSON parse 30/30, strict name match 20/30
