"""Tamp-compatible LLMLingua-2 sidecar, same API as tamp/sidecar/server.py but on the RTX 3090 in fp16.
Run in WSL: uv run --project ~/lingua-bench --with fastapi --with uvicorn uvicorn sidecar_gpu:app --host 0.0.0.0 --port 8788
"""
import torch
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()
compressor = None


class CompressRequest(BaseModel):
    text: str
    rate: float = 0.5


@app.on_event("startup")
async def load_model():
    global compressor
    from llmlingua import PromptCompressor
    compressor = PromptCompressor(
        model_name="microsoft/llmlingua-2-xlm-roberta-large-meetingbank",
        use_llmlingua2=True, device_map="cuda", model_config={"dtype": torch.float16},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": compressor is not None}


@app.post("/compress")
async def compress(payload: CompressRequest):
    result = compressor.compress_prompt(
        payload.text, rate=payload.rate, force_tokens=["\n", "?", "!", ".", ",", "'", '"'],
    )
    return {"text": result["compressed_prompt"], "original_tokens": result["origin_tokens"],
            "compressed_tokens": result["compressed_tokens"]}
