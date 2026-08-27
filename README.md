# Financial Statement Analyzer Agent

Computes a standard financial ratio suite (liquidity, profitability, leverage,
efficiency) across a set of companies, flags peer-relative anomalies using
z-scores, runs a configurable stress-test scenario (revenue decline, margin
compression, provision shocks), and uses Claude to generate an analyst-style
narrative summary of the findings.

Built as an extension of manual sector comparisons (e.g. Tata Motors vs.
Mahindra & Mahindra, NVIDIA vs. AMD, HDFC vs. ICICI) into a reusable tool.

## Setup

```bash
git clone <your-repo-url>
cd financial-statement-analyzer
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and paste in your own Anthropic API key from
[console.anthropic.com](https://console.anthropic.com/settings/keys).
**Never commit your `.env` file** — it's already excluded via `.gitignore`.

## Usage

```bash
python3 financial_statement_analyzer.py sample_companies.json --revenue-decline-pct 10
```

Options:
- `--revenue-decline-pct` — % revenue decline in the stress scenario (default 10)
- `--margin-compression-bps` — basis points shaved off gross margin under stress
- `--provision-increase-pct` — % rise in an assumed loan-loss provision (for banks)
- `--model` — Claude model to use for the narrative step (default `claude-fable-5`)
- `--skip-narrative` — only compute ratios/anomalies locally, skip the API call
- `--out` — output file for the narrative report (default `analysis_report.md`)

Input is a JSON list of companies — see `sample_companies.json` for the schema.

**Anomaly detection needs 3+ companies.** With only 2, the z-score of any
unequal pair is mathematically always exactly ±1.0 (the mean sits at the
midpoint and the stdev is half the gap), so every metric would "flag" as
an outlier regardless of how similar the companies actually are. Below 3
companies, the anomaly section is intentionally left empty rather than
printing numbers that look meaningful but aren't. `sample_companies.json`
ships with 2 companies (Tata Motors vs. M&M) to exercise the ratio and
stress-test logic — add a third peer to see anomaly flagging in action.

## How costs work

Only the final narrative step calls the Anthropic API — all ratio math,
peer comparison, and stress testing run entirely offline and cost nothing.
**Your API key is read from your own local `.env` file and is never included
in this repository.** Anyone who clones this repo needs to supply their own
key to generate a narrative; they cannot use yours.

## Security notes

- API keys belong in `.env` only, never hardcoded in the script.
- `.env` is git-ignored by default — double check `git status` before
  committing if you ever touch this file.
- If a key is ever accidentally committed, rotate it immediately in the
  Anthropic Console — removing the commit afterward is not sufficient since
  it remains in git history.
