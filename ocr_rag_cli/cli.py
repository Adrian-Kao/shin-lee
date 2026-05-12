from __future__ import annotations

import argparse
import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .chunker import chunk_pages
from .config import PROCESSED_DIR, TOP_K
from .loader import load_document
from .ollama import generate_answer
from .vector_store import search, upsert_chunks

console = Console()


def cmd_ingest(args: argparse.Namespace) -> None:
    path = Path(args.file).resolve()
    console.print(f"[bold]Loading[/bold] {path}")
    pages = load_document(path, force_ocr=args.force_ocr)
    chunks = chunk_pages(pages, chunk_size=args.chunk_size, overlap=args.overlap)
    count = upsert_chunks(chunks)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / f"{path.stem}.json"
    out_path.write_text(
        json.dumps(
            {
                "file": str(path),
                "pages": [page.__dict__ for page in pages],
                "chunks": [chunk.__dict__ for chunk in chunks],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    console.print(f"Indexed [bold green]{count}[/bold green] chunks")
    console.print(f"Processed JSON: {out_path}")


def _print_citations(hits: list[dict]) -> None:
    table = Table(title="Retrieved Sources")
    table.add_column("#")
    table.add_column("Score")
    table.add_column("File")
    table.add_column("Page")
    table.add_column("Preview")
    for index, hit in enumerate(hits, 1):
        preview = str(hit["text"]).replace("\n", " ")[:120]
        table.add_row(str(index), f"{hit['score']:.4f}", str(hit["file_name"]), str(hit["page"]), preview)
    console.print(table)


def cmd_ask(args: argparse.Namespace) -> None:
    question = args.question or console.input("Question> ")
    hits = search(question, top_k=args.top_k)
    if not hits:
        console.print("No indexed context found. Run ingest first.")
        return
    answer = generate_answer(question, hits)
    console.print(Panel(answer, title="Answer", border_style="green"))
    _print_citations(hits)


def cmd_chat(args: argparse.Namespace) -> None:
    console.print("Type /exit to quit.")
    while True:
        question = console.input("Question> ").strip()
        if question.lower() in {"/exit", "exit", "quit", "q"}:
            break
        if not question:
            continue
        hits = search(question, top_k=args.top_k)
        if not hits:
            console.print("No indexed context found. Run ingest first.")
            continue
        answer = generate_answer(question, hits)
        console.print(Panel(answer, title="Answer", border_style="green"))
        _print_citations(hits)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Terminal OCR + RAG POC")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="OCR/extract, chunk, embed, and index a document")
    ingest.add_argument("file")
    ingest.add_argument("--force-ocr", action="store_true", help="OCR every PDF page instead of using embedded text")
    ingest.add_argument("--chunk-size", type=int, default=900)
    ingest.add_argument("--overlap", type=int, default=150)
    ingest.set_defaults(func=cmd_ingest)

    ask = subparsers.add_parser("ask", help="Ask one question")
    ask.add_argument("question", nargs="?")
    ask.add_argument("--top-k", type=int, default=TOP_K)
    ask.set_defaults(func=cmd_ask)

    chat = subparsers.add_parser("chat", help="Interactive terminal chat")
    chat.add_argument("--top-k", type=int, default=TOP_K)
    chat.set_defaults(func=cmd_chat)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
