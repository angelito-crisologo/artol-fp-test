# artol-topologies

Static browsable catalog of every hand-authored room topology in the
artol-ai CP-SAT floor plan generator. Generated from
`floorplan_v1/topologies/` + `floorplan_v1/briefs/test/` — every JSON
document, floor plan, and validator result in the site is live solver
output at generation time, not hand-written.

## Structure

```
artol-topologies/
├── index.html              single-page app: gallery + one page per topology
├── assets/
│   ├── styles.css
│   └── app.js               accordion, shape filter, hash router, JSON copy/highlight
├── plans/                    one rendered floor-plan SVG per verified topology
├── data/
│   ├── topologies/           raw topology definition JSON, every entry
│   └── briefs/                raw test-brief JSON, verified entries only
└── README.md
```

Counts drift as topologies are added — see the header stats on the live
page, or `TOPOLOGY_CHANGES.md` (repo root) for what changed since the
last build.

## Viewing locally

Open `index.html` directly in a browser — no build step, no server
required. All assets are referenced with relative paths (stylesheet,
script, SVGs, JSON downloads), so it works over `file://` as well as any
HTTP host.

## Publishing

This is a plain static site: point any static host at this folder.
- **GitHub Pages** — commit this folder, enable Pages on the repo/branch, set the folder as the site root (or serve `/artol-topologies` as a project subpath).
- **Netlify / Vercel / Cloudflare Pages** — drag-and-drop deploy or point a project at this directory; no build command needed.
- **Any web server** (nginx, S3 static hosting, etc.) — copy the folder as-is.

## Regenerating

This folder is generated output — don't hand-edit it. The build tool is
checked in at `tools/topology_catalog/build_catalog.py` (repo root):

```
source .venv/bin/activate
python3 tools/topology_catalog/build_catalog.py
```

It solves every topology's canonical test brief through the real CP-SAT
solver and rewrites everything in this folder from scratch. See
`TOPOLOGY_CHANGES.md` (repo root) for what's pending before a run, and
that file's own docstring for how canonical-brief selection and content
derivation work.
