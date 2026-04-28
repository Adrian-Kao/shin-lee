# OCR + RAG CLI POC

A terminal-first proof of concept for document OCR, vector indexing, and RAG answers with citations.

## Stack

- OCR: PaddleOCR
- Embedding: BGE-M3 via `FlagEmbedding`
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
python -m ocr_rag_cli.cli ask "這份文件的重點是什麼？"
```

Interactive mode:

```powershell
python -m ocr_rag_cli.cli chat
```

## POC behavior

The model is instructed to answer only from retrieved context. If there is not enough evidence, it should say: `根據目前文件內容，無法確認`.

Returned citations include file name, page, score, and a preview of the retrieved chunk.
