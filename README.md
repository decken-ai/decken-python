# `decken` — Official Python SDK & CLI

Pure-stdlib Python 3.9+ SDK and CLI for **[Decken](https://decken.ai)** — the Native OpenXML (`.pptx`) Slide Generation Kernel that turns any Coding Agent, PowerPoint, WPS Office, or SaaS into a **better Gamma**.

- **Website**: [https://decken.ai](https://decken.ai)
- **Documentation**: [https://docs.decken.ai](https://docs.decken.ai)
- **Node.js SDK**: [`decken-ai/decken-node`](https://github.com/decken-ai/decken-node)
- **MCP Server**: [`decken-ai/decken-mcp`](https://github.com/decken-ai/decken-mcp)

## Install

```bash
pip install git+https://github.com/decken-ai/decken-python.git
```

## Unified 3-Scenario Usage (`client.generate` / `POST /v1/decks`)

```python
from decken import DeckenClient

client = DeckenClient()  # reads DECKEN_API_KEY

# 1. Generate directly from outline (expressive diagrams + native <a:tbl> tables)
client.generate(
    deck_title="Edge Inference Architecture",
    outline=[
        {
            "title": "Zero-Copy KV Routing Pipeline",
            "diagram": {
                "kind": "flow",
                "nodes": [
                    {"label": "Anycast Edge", "detail": "TLS + Auth"},
                    {"label": "Prefix Mesh", "detail": "Radix KV tree"},
                    {"label": "FP8 Worker", "detail": "29ms p99"},
                ],
            },
        }
    ],
    output_path="./edge-architecture.pptx",
)

# 2. Generate from outline + reference image OR corporate .pptx template
client.generate(
    outline="## FY26 Revenue\n- ARR reached $42.8M (+138% YoY)",
    reference="./corporate-master.pptx",  # or "./style-reference.png"
    output_path="./fy26-board.pptx",
)

# 3. Improve an existing rough .pptx OR reconstruct flat screenshots
client.generate(
    source="./rough-draft.pptx",  # or "./screenshot.png"
    prompt="Unify visual hierarchy while preserving 100% of numbers verbatim.",
    output_path="./upgraded.pptx",
)
```

## CLI

```bash
export DECKEN_API_KEY="dk_live_..."

decken generate \
  --outline ./outline.md \
  --reference ./corporate-master.pptx \
  -o ./deck.pptx
```

## License

MIT
