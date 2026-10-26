"""CPU-only inference using local Qwen model weights, without knowledge storage."""

import math
import os
from pathlib import Path

EMBEDDING_MODEL = "Qwen3-Embedding-0.6B"
RERANKER_MODEL = "Qwen3-Reranker-0.6B"
DIMENSIONS = 1024
INSTRUCTION = (
    "Given a Cool Data Sim customer question, retrieve relevant product information "
    "and customer support passages that directly answer it, including applicable "
    "destinations, plan conditions, activation and collection instructions."
)


def checked_vectors(vectors, count):
    if len(vectors) != count:
        raise RuntimeError("向量回傳數量不正確")
    for vector in vectors:
        if len(vector) != DIMENSIONS or any(not math.isfinite(float(value)) for value in vector):
            raise RuntimeError("向量維度或數值不正確")
        norm = math.sqrt(sum(float(value) ** 2 for value in vector))
        if not 0.99 <= norm <= 1.01:
            raise RuntimeError("向量不是有效的正規化向量")
    return vectors


def checked_scores(scores, count):
    if len(scores) != count or any(not math.isfinite(float(value)) or not 0 <= float(value) <= 1 for value in scores):
        raise RuntimeError("重排回傳數量或分數不正確")
    return [float(value) for value in scores]


class CpuModels:
    """Load read-only model weights once. Requests are serialized by the API."""

    def __init__(self, root, *, threads=8, max_tokens=2048, dtype="bfloat16"):
        # Disable GPU visibility before importing the runtime. No device_map=auto.
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        import torch
        import torch.nn.functional as functional
        from transformers import AutoModel, AutoModelForCausalLM, AutoTokenizer

        if not 1 <= threads <= 32 or not 256 <= max_tokens <= 4096:
            raise ValueError("CPU執行緒或輸入長度設定不正確")
        if dtype not in {"bfloat16", "float32"}:
            raise ValueError("CPU資料型別設定不正確")
        root = Path(root).resolve()
        if not all((root / name / "config.json").is_file() for name in (EMBEDDING_MODEL, RERANKER_MODEL)):
            raise ValueError("找不到已存在的本機模型檔")
        torch.set_num_threads(threads)
        torch.set_num_interop_threads(2)
        self.torch, self.functional = torch, functional
        self.max_tokens, self.dtype = max_tokens, dtype
        model_dtype = torch.bfloat16 if dtype == "bfloat16" else torch.float32
        tokenizer_options = {"padding_side": "left", "local_files_only": True, "trust_remote_code": False}
        model_options = {"torch_dtype": model_dtype, "local_files_only": True,
                         "trust_remote_code": False, "attn_implementation": "sdpa"}
        self.embed_tokenizer = AutoTokenizer.from_pretrained(root / EMBEDDING_MODEL, **tokenizer_options)
        self.embed_model = AutoModel.from_pretrained(root / EMBEDDING_MODEL, **model_options).to("cpu").eval()
        self.rank_tokenizer = AutoTokenizer.from_pretrained(root / RERANKER_MODEL, **tokenizer_options)
        self.rank_model = AutoModelForCausalLM.from_pretrained(root / RERANKER_MODEL, **model_options).to("cpu").eval()
        if int(self.embed_model.config.hidden_size) != DIMENSIONS:
            raise RuntimeError("載入的向量模型不是1024維")
        self.yes_no_ids = [self.rank_tokenizer.convert_tokens_to_ids(value) for value in ("no", "yes")]
        if len(set(self.yes_no_ids)) != 2 or any(value is None or value == self.rank_tokenizer.unk_token_id for value in self.yes_no_ids):
            raise RuntimeError("重排模型的判斷詞無效")
        self.rank_prefix = self.rank_tokenizer.encode(
            "<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. "
            "Note that the answer can only be \"yes\" or \"no\".<|im_end|>\n<|im_start|>user\n", add_special_tokens=False)
        self.rank_suffix = self.rank_tokenizer.encode(
            "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n", add_special_tokens=False)

    def _last_token(self, hidden, attention_mask):
        if bool((attention_mask[:, -1].sum() == attention_mask.shape[0]).item()):
            return hidden[:, -1]
        positions = attention_mask.sum(dim=1) - 1
        return hidden[self.torch.arange(hidden.shape[0], device=hidden.device), positions]

    def embed(self, texts, *, query=False):
        output, token_count = [], 0
        with self.torch.inference_mode():
            for offset in range(0, len(texts), 4):
                batch = texts[offset:offset + 4]
                if query:
                    batch = [f"Instruct: {INSTRUCTION}\nQuery:{value}" for value in batch]
                encoded = self.embed_tokenizer(batch, padding=True, truncation=False, return_tensors="pt")
                if encoded["input_ids"].shape[1] > self.max_tokens:
                    raise ValueError("輸入超過模型服務的Token上限，請縮短問題或分段")
                token_count += int(encoded["attention_mask"].sum().item())
                hidden = self.embed_model(**encoded).last_hidden_state
                pooled = self._last_token(hidden, encoded["attention_mask"]).float()
                output.extend(self.functional.normalize(pooled, p=2, dim=1).tolist())
        return checked_vectors(output, len(texts)), token_count

    def rerank(self, query, documents):
        output = []
        with self.torch.inference_mode():
            selected_weights = self.rank_model.lm_head.weight[self.yes_no_ids]
            bias = getattr(self.rank_model.lm_head, "bias", None)
            selected_bias = bias[self.yes_no_ids] if bias is not None else None
            for offset in range(0, len(documents), 4):
                pairs = [f"<Instruct>: {INSTRUCTION}\n<Query>: {query}\n<Document>: {value}"
                         for value in documents[offset:offset + 4]]
                tokens = self.rank_tokenizer(pairs, padding=False, truncation=False, return_attention_mask=False)
                sequences = [{"input_ids": self.rank_prefix + ids + self.rank_suffix} for ids in tokens["input_ids"]]
                if any(len(value["input_ids"]) > self.max_tokens for value in sequences):
                    raise ValueError("問題與文件超過重排Token上限，請縮短或分段")
                encoded = self.rank_tokenizer.pad(sequences, padding=True, return_tensors="pt")
                hidden = self.rank_model.model(**encoded).last_hidden_state
                pooled = self._last_token(hidden, encoded["attention_mask"])
                logits = self.functional.linear(pooled, selected_weights, selected_bias).float()
                output.extend(logits.softmax(dim=1)[:, 1].tolist())
        return checked_scores(output, len(documents))
