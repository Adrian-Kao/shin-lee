from __future__ import annotations

import httpx

from .config import LLM_PROVIDER, LM_STUDIO_MODEL, LM_STUDIO_URL, OLLAMA_MODEL, OLLAMA_URL


PROMPT_TEMPLATE = """你是一個文件問答助手。請只根據 Context 回答問題。

規則：
1. 如果 Context 沒有足夠證據，回答「根據目前文件內容，無法確認」。
2. 不要使用外部知識補充答案。
3. 回答請使用繁體中文。
4. 回答最後列出引用來源，格式為「來源：檔名 p.頁碼」。

Question:
{question}

Context:
{context}
"""


def build_context(hits: list[dict]) -> str:
    parts = []
    for index, hit in enumerate(hits, 1):
        parts.append(
            f"[{index}] file={hit['file_name']} page={hit['page']} score={hit['score']:.4f}\n{hit['text']}"
        )
    return "\n\n".join(parts)


def _generate_with_ollama(prompt: str) -> str:
    with httpx.Client(timeout=120) as client:
        response = client.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        )
        response.raise_for_status()
        return response.json().get("response", "").strip()


def _generate_with_lm_studio(prompt: str) -> str:
    with httpx.Client(timeout=120) as client:
        response = client.post(
            f"{LM_STUDIO_URL.rstrip('/')}/chat/completions",
            json={
                "model": LM_STUDIO_MODEL,
                "messages": [
                    {"role": "system", "content": "你是嚴格根據文件內容回答的繁體中文文件問答助手。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "stream": False,
            },
        )
        response.raise_for_status()
        data = response.json()
        if "choices" not in data:
            raise RuntimeError(
                "LM Studio did not return a chat completion. "
                "Check that the local server is running and LM_STUDIO_MODEL matches the loaded model. "
                f"Response: {data}"
            )
        return data["choices"][0]["message"]["content"].strip()


def generate_answer(question: str, hits: list[dict]) -> str:
    prompt = PROMPT_TEMPLATE.format(question=question, context=build_context(hits))
    if LLM_PROVIDER == "lmstudio":
        return _generate_with_lm_studio(prompt)
    return _generate_with_ollama(prompt)