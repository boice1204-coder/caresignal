# CareSignal

**AI for Better Living and Smarter Communities** — a data intelligence tool
for family caregivers coordinating an elderly parent's health across
scattered sources (clinic prescriptions, home vitals, diet notes, family
group-chat updates), built for the Gen AI Academy APAC Edition hackathon.

**Live interactive wireframe:** https://YOUR-GITHUB-USERNAME.github.io/YOUR-REPO-NAME/
*(replace with your actual GitHub Pages URL — see "Deploying the wireframe" below)*

## What's in this repo

- **`docs/`** — the interactive front-end wireframe (3 screens: Family
  Circle home, Alert detail with audit-trail drill-down, Quick log). Static
  HTML/CSS/JS, no build step. Named `index.html` so GitHub Pages serves it
  directly.
- **`backend/`** — the decision-engine backend: clinical rule engine (17
  rules, 14 sourced from a peer-reviewed expert-consensus panel — Phansalkar
  et al. 2012, JAMIA), a live openFDA drug-label cross-check, a Gemini
  explanation layer, BigQuery schema, and 27 passing unit tests. See
  `backend/README.md` for the full architecture writeup and how to run it.
- **`CareSignal_Deck.pdf`** — the submission deck.

## Deploying the wireframe (for the "Working Prototype Deployed Link" field)

This repo is already structured for GitHub Pages, which is the fastest
zero-config way to get a public link:

1. Push this repo to GitHub (see commands below).
2. On GitHub.com, go to your repo → **Settings → Pages**.
3. Under "Build and deployment" → **Source**, choose **Deploy from a branch**.
4. Branch: `main`, folder: **`/docs`** → **Save**.
5. GitHub will publish it at `https://YOUR-USERNAME.github.io/YOUR-REPO-NAME/`
   within a minute or two — that's your deployed link.

## Pushing this repo to GitHub

```bash
cd CareSignal_Repo
git init
git add .
git commit -m "CareSignal: wireframe + decision engine backend"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPO-NAME.git
git push -u origin main
```

(Create the empty repository on GitHub first — github.com → New repository
→ don't initialize with a README — then use the URL it gives you above.)

## Running the backend locally

```bash
cd backend
pip install -r requirements.txt
cd tests && python3 -m pytest -v          # 27 tests, no GCP project needed
cd ../pipeline && python3 run_pipeline.py   # runs the demo scenario end to end
```
