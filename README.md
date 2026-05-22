# XSD Visualizer

A browser-based interactive viewer for ISO 20022 XSD message schemas.
Parses XSD files into a JSON model and renders an expandable tree with diff comparison.

Built to visualize the Georgian national adaptation of ISO 20022 pain.001 (credit transfer initiation).

## Live Demo

Deployed on GitHub Pages — three view modes available:
- **ISO 20022** — the international standard schema
- **Georgian** — the Georgian national adaptation
- **Diff** — side-by-side change highlighting with severity classification

## Install

```bash
pip install -r requirements.txt
```

## Parse an XSD

```bash
# Single XSD file
python parser/parse_xsd.py \
  --input path/to/schema.xsd \
  --out viewer/schema-model.json

# XSD with imports (pass the folder containing referenced files)
python parser/parse_xsd.py \
  --input path/to/schema.xsd \
  --imports path/to/xsd-folder/ \
  --out viewer/schema-model.json
```

## Generate a Diff

```bash
# Parse both versions first
python parser/parse_xsd.py --input pain.001.001.09.xsd          --out viewer/original.json
python parser/parse_xsd.py --input GEO_pain.001.001.09.xsd      --out viewer/schema-model.json

# Generate diff
python parser/diff_xsd.py \
  --old viewer/original.json \
  --new viewer/schema-model.json \
  --out viewer/diff-model.json
```

The viewer detects the diff automatically and adds the **ISO 20022 / Georgian / Diff** switcher.

## Open the Viewer Locally

```bash
cd viewer
python -m http.server 8080
# open http://localhost:8080
```

Or open `viewer/index.html` directly in your browser (uses `.js` sidecars written by the parser as a fallback).

## Deploy to GitHub Pages

1. Push the repo to GitHub.
2. Go to **Settings → Pages → Source** and choose **GitHub Actions**.
3. Push to `main` — the workflow in `.github/workflows/deploy.yml` deploys `viewer/` automatically.

The generated `viewer/*.json` and `viewer/*.js` files are committed alongside the source so the site is always ready to deploy without a build step.

## Run Tests

```bash
pytest tests/ -v
```

## Known Limitations

- `xs:group` and `xs:attributeGroup` are not expanded (v1 limitation).
- `xs:any` / `xs:anyAttribute` are skipped with a warning.
- Deep self-referencing types are shown with a `[REF]` sentinel node at the point of recursion.
- `file://` fallback for the Original view requires an `original.js` sidecar in the viewer folder.
