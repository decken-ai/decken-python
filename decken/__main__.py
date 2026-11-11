import argparse
import json
from pathlib import Path
from .client import DeckenClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Decken Python CLI — The Native OpenXML (.pptx) Slide Kernel")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("capabilities", help="Inspect gateway capabilities")

    gen = sub.add_parser("generate", help="Generate or improve a native .pptx deck (POST /v1/decks)")
    gen.add_argument("--outline", default=None, help="Outline Markdown text or path to .md/.json")
    gen.add_argument("--reference", default=None, help="Optional reference .pptx template or slide image")
    gen.add_argument("--source", default=None, help="Existing rough .pptx or slide image to improve")
    gen.add_argument("--prompt", default=None, help="Brief or improvement instruction")
    gen.add_argument("-o", "--output", default="deck.pptx", help="Output .pptx path")
    gen.add_argument("--engine", default="vlm", choices=["vlm", "deterministic"])
    gen.add_argument("--model", default=None)

    rec = sub.add_parser("reconstruct", help="Reconstruct slide image(s) into a native .pptx")
    rec.add_argument("images", nargs="+", help="Input slide image paths")
    rec.add_argument("-o", "--output", default="reconstructed.pptx", help="Output .pptx path")
    rec.add_argument("--engine", default="vlm", choices=["vlm", "deterministic"])
    rec.add_argument("--model", default=None)

    args = parser.parse_args()
    client = DeckenClient()

    if args.command == "capabilities":
        print(json.dumps(client.get_capabilities(), indent=2))
    elif args.command == "generate":
        outline_val = args.outline
        if outline_val and Path(outline_val).exists() and outline_val.endswith((".md", ".json")):
            raw = Path(outline_val).read_text(encoding="utf-8")
            outline_val = json.loads(raw) if outline_val.endswith(".json") else raw
        job = client.generate(
            outline=outline_val,
            reference=args.reference,
            source=args.source,
            prompt=args.prompt,
            output_path=args.output,
            engine_mode=args.engine,
            model_id=args.model,
        )
        print(f"Saved {args.output} ({job.get('scenario', 'deck')}, job: {job['jobId']})")
    elif args.command == "reconstruct":
        if len(args.images) == 1:
            job = client.reconstruct_slide(
                image_path=args.images[0],
                output_path=args.output,
                engine_mode=args.engine,
                model_id=args.model,
            )
        else:
            job = client.reconstruct_deck(
                [{"image_path": p} for p in args.images],
                output_path=args.output,
                engine_mode=args.engine,
                model_id=args.model,
            )
        print(f"Saved {args.output} (job: {job['jobId']}, objects: {job.get('metrics', {}).get('totalObjectCount', 0)})")


if __name__ == "__main__":
    main()
