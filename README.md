# OCR + RAG CLI POC

A terminal-first proof of concept for document OCR, vector indexing, and RAG answers with citations.

## Stack

- OCR: PaddleOCR
- Embedding: BGE-M3 via `sentence-transformers`
- Vector DB: Qdrant
- LLM: Ollama + `qwen2.5:7b`
- CLI: Python argparse + Rich

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Start Qdrant:

```powershell
docker compose up -d
```

Install and start Ollama, then pull the model:

```powershell
ollama pull qwen2.5:7b
ollama serve
```

## Ingest a document

PDFs with embedded text are parsed directly. Scanned PDFs and images use PaddleOCR.

```powershell
python -m ocr_rag_cli.cli ingest "C:\path\to\document.pdf"
```

Force OCR for every PDF page:

```powershell
python -m ocr_rag_cli.cli ingest "C:\path\to\document.pdf" --force-ocr
```

## Ask questions

```powershell
python -m ocr_rag_cli.cli ask "?謕??刻麾????綜等謢??餅??"
```

Interactive mode:

```powershell
python -m ocr_rag_cli.cli chat
```

## POC behavior

The model is instructed to answer only from retrieved context. If there is not enough evidence, it should say: `?撖??獢???刻麾??寞?????﹦?歹.

Returned citations include file name, page, score, and a preview of the retrieved chunk.

## Use LM Studio instead of Ollama

In LM Studio, load a chat/instruct model, open the Local Server tab, and start the OpenAI-compatible server. The default base URL is usually:

```text
http://localhost:1234/v1
```

Then update `.env`:

```powershell
LLM_PROVIDER=lmstudio
LM_STUDIO_URL=http://localhost:1234/v1
LM_STUDIO_MODEL=local-model
```

If LM Studio shows a specific model id in the server page, use that value for `LM_STUDIO_MODEL`.