"""Short GPU fine-tune of the bot's Laya checkpoint on the synthetic teacher data (re-runnable).

Uses the installed package's own trainer (laya.train.finetune, verified in laya/train.py: JSONL rows
{state, questions, expected}, RLCD loss, calibration, before/after held-out evaluation). The output loads with
laya.load(dir) and is picked up by the gateway automatically (decision/laya_service.py: ai/models/laya-bot).

Memory: full fine-tuning of ModernBERT-large (weights + grads + AdamW states ~ 6.4 GB fp32) does not fit a 6 GB laptop
GPU, so the default trains the decision head on top of the FROZEN encoder (--freeze-encoder, the trainer's own option).

    cd ai
    .venv\\Scripts\\python.exe -m laya_finetune.generate_dataset --rows 4000
    .venv\\Scripts\\python.exe -m laya_finetune.train --epochs 2
Limit: the model imitates the teacher (bot_heuristic); it cannot become better than the teacher on what the teacher knows.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

AI_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = AI_DIR / "models" / "laya-bot-data"
OUT_DIR = AI_DIR / "models" / "laya-bot"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="typed-decisions", help="base checkpoint alias / Hub id / local dir")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--micro-batch", type=int, default=8)
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--full", action="store_true", help="also train the encoder (needs > 6 GB VRAM)")
    ap.add_argument("--loss", default="rlcd", choices=["rlcd", "soft-ce"])
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args()

    import torch
    from laya.train import TrainConfig, finetune, resolve_checkpoint_dir

    train_path, val_path = DATA_DIR / "train.jsonl", DATA_DIR / "val.jsonl"
    if not train_path.exists():
        sys.exit("No dataset: run  python -m laya_finetune.generate_dataset  first.")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        print("WARNING: CUDA not available - fine-tuning on CPU will be slow.")
    gpu = torch.cuda.get_device_name(0) if device == "cuda" else "cpu"

    base_dir = resolve_checkpoint_dir(args.base)
    cfg = TrainConfig(epochs=args.epochs, micro_batch=args.micro_batch, grad_accum=args.grad_accum,
                      loss=args.loss, freeze_encoder=not args.full, eval_data=str(val_path), log_every=200, seed=0)
    tmp_out = args.out + "_tmp"
    if os.path.isdir(tmp_out):
        shutil.rmtree(tmp_out)
    t0 = time.perf_counter()
    summary = finetune(str(train_path), base_dir, tmp_out, cfg, device=device)
    minutes = (time.perf_counter() - t0) / 60.0

    # Atomic swap: the gateway never sees a half-written checkpoint
    if os.path.isdir(args.out):
        shutil.rmtree(args.out)
    os.replace(tmp_out, args.out)
    report = {"base": args.base, "device": device, "gpu": gpu, "minutes": round(minutes, 1),
              "freeze_encoder": not args.full, "epochs": args.epochs, "train_rows": sum(1 for _ in open(train_path, encoding="utf-8")),
              "summary": summary}   # laya.train.finetune summary (before / after held-out metrics, calibration, config)
    (Path(args.out) / "finetune_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("base", "device", "gpu", "minutes", "freeze_encoder", "epochs", "train_rows")}, indent=1))
    print("saved:", args.out)


if __name__ == "__main__":
    main()
