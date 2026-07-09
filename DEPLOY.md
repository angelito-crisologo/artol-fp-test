# Deploying the tester (`floorplan_v1/app.py`)

## Run it locally first

```bash
pip install -r requirements.txt --break-system-packages   # if needed
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit .streamlit/secrets.toml with your real ANTHROPIC_API_KEY + a password
streamlit run floorplan_v1/app.py
```

Without `ANTHROPIC_API_KEY` set, step 2 (free-text extraction) falls back to
a regex-based stub instead of calling Claude — good for poking at the UI
without spending API credits, not for realistic extraction quality.

Without `APP_PASSWORD` set, the app has no login gate — fine for local use,
not for the public URL.

## Push to GitHub

```bash
git remote add origin <your-repo-url>
git push -u origin main
```

`.gitignore` already excludes `floorplan_v1/output/`, `test_output/`,
`cache/`, and `.streamlit/secrets.toml` — none of that should end up in the
repo.

## Deploy on Streamlit Community Cloud

1. https://share.streamlit.io -> New app -> pick the repo/branch.
2. **Main file path:** `floorplan_v1/app.py`
3. Deploy. It reads `requirements.txt` from the repo root automatically.
4. App -> Settings -> Secrets, paste:
   ```
   ANTHROPIC_API_KEY = "sk-ant-..."
   APP_PASSWORD = "choose-something-your-partner-can-type"
   ```
5. Reboot the app so the secrets take effect. Share the `*.streamlit.app`
   URL + the password with your partner.

## Notes

- First load after a period of inactivity will be slow (Streamlit Cloud
  free tier sleeps idle apps) — that's a cold start, not a bug.
- Each "Run selected" solve is capped at 10s per topology by the existing
  solver config (`solve(..., time_limit_s=10.0, ...)` in `run.py`); running
  several checked topologies at once means a wait proportional to how many
  are checked.
- The catalog today is 9 topologies, all single-storey/2BR
  (squarish + wide only) — requirements outside that (3BR, 2-storey, deep
  lots, etc.) will correctly show "no matching topology," not an error.
