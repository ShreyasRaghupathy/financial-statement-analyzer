"""
Financial Statement Analyzer Agent
-----------------------------------
Computes a standard ratio suite (liquidity, profitability, leverage,
efficiency) for one or more companies, flags peer-relative anomalies,
runs a configurable stress-test scenario, and uses a Claude model to
generate an analyst-style narrative summary of the findings.

Usage:
    python financial_statement_analyzer.py companies.json --shock revenue_decline_pct=10

Input file format (JSON list of companies):
[
  {
    "name": "Company A",
    "sector": "Automotive",
    "revenue": 100000,
    "cogs": 60000,
    "operating_income": 15000,
    "net_income": 10000,
    "total_assets": 200000,
    "total_liabilities": 120000,
    "total_equity": 80000,
    "current_assets": 50000,
    "current_liabilities": 30000,
    "inventory": 10000,
    "cash": 15000,
    "total_debt": 70000,
    "interest_expense": 4000
  },
  ...
]

Requires: pip install -r requirements.txt
Set ANTHROPIC_API_KEY in a local .env file (see .env.example) before running.
NEVER hardcode your API key in this file or commit a .env file to git.
"""

import argparse
import json
import os
import statistics
import sys

from dotenv import load_dotenv

load_dotenv()  # loads ANTHROPIC_API_KEY from a local .env file, if present


# ---------------------------------------------------------------------------
# 1. Ratio calculations
# ---------------------------------------------------------------------------

def compute_ratios(c):
    """Compute a standard ratio suite for a single company dict."""
    r = {}

    # Profitability
    r["gross_margin_pct"] = safe_div(c["revenue"] - c["cogs"], c["revenue"]) * 100
    r["operating_margin_pct"] = safe_div(c["operating_income"], c["revenue"]) * 100
    r["net_margin_pct"] = safe_div(c["net_income"], c["revenue"]) * 100
    r["roe_pct"] = safe_div(c["net_income"], c["total_equity"]) * 100
    r["roa_pct"] = safe_div(c["net_income"], c["total_assets"]) * 100

    # Liquidity
    r["current_ratio"] = safe_div(c["current_assets"], c["current_liabilities"])
    r["quick_ratio"] = safe_div(c["current_assets"] - c.get("inventory", 0), c["current_liabilities"])

    # Leverage
    r["debt_to_equity"] = safe_div(c["total_debt"], c["total_equity"])
    r["interest_coverage"] = safe_div(c["operating_income"], c.get("interest_expense", 0))

    # Efficiency
    r["asset_turnover"] = safe_div(c["revenue"], c["total_assets"])

    return r


def safe_div(a, b):
    return a / b if b else 0.0


# ---------------------------------------------------------------------------
# 2. Peer comparison / anomaly flagging
# ---------------------------------------------------------------------------

def flag_anomalies(all_ratios, z_threshold=1.0):
    """
    For each ratio, compute the peer mean/stdev and flag any company whose
    value deviates by more than z_threshold standard deviations.
    Returns a dict: company_name -> list of anomaly strings.

    Requires at least 3 companies. With exactly 2, the z-score of any
    unequal pair is mathematically always exactly +/-1.0 (mean is the
    midpoint, stdev is half the gap), so every metric would "flag" as
    an outlier regardless of how similar the companies actually are.
    That's not a real signal, so anomaly detection is skipped below
    n=3 rather than reporting numbers that look meaningful but aren't.
    """
    if len(all_ratios) < 3:
        return {c: [] for c in all_ratios}

    metric_names = next(iter(all_ratios.values())).keys()
    anomalies = {name: [] for name in all_ratios}

    for metric in metric_names:
        values = [all_ratios[c][metric] for c in all_ratios]
        mean = statistics.mean(values)
        stdev = statistics.pstdev(values) or 1e-9

        for company, ratios in all_ratios.items():
            z = (ratios[metric] - mean) / stdev
            if abs(z) >= z_threshold:
                direction = "above" if z > 0 else "below"
                anomalies[company].append(
                    f"{metric.replace('_', ' ')}: {ratios[metric]:.2f} "
                    f"({direction} peer average of {mean:.2f}, z={z:.2f})"
                )
    return anomalies


# ---------------------------------------------------------------------------
# 3. Stress testing
# ---------------------------------------------------------------------------

def apply_shock(c, revenue_decline_pct=0.0, margin_compression_bps=0.0, provision_increase_pct=0.0):
    """
    Return a shocked copy of a company's financials.
    - revenue_decline_pct: e.g. 10 means revenue falls 10%
    - margin_compression_bps: basis points shaved off gross margin
    - provision_increase_pct: for banks, % rise in an assumed loan-loss
      provision, modeled as a direct hit to operating_income and net_income
    """
    shocked = dict(c)
    revenue = c["revenue"] * (1 - revenue_decline_pct / 100.0)
    shocked["revenue"] = revenue

    gross_margin = safe_div(c["revenue"] - c["cogs"], c["revenue"])
    gross_margin_shocked = gross_margin - (margin_compression_bps / 10000.0)
    shocked["cogs"] = revenue * (1 - gross_margin_shocked)

    op_margin = safe_div(c["operating_income"], c["revenue"])
    shocked["operating_income"] = revenue * op_margin

    # crude provision hit: assume base "provision" is 10% of operating income
    # unless a more precise field is supplied
    base_provision = c.get("provision_expense", c["operating_income"] * 0.10)
    extra_provision = base_provision * (provision_increase_pct / 100.0)
    shocked["operating_income"] -= extra_provision

    net_margin = safe_div(c["net_income"], c["revenue"])
    shocked["net_income"] = revenue * net_margin - extra_provision

    return shocked


# ---------------------------------------------------------------------------
# 4. Narrative generation via Claude
# ---------------------------------------------------------------------------

def generate_narrative(companies, ratios, anomalies, shocked_ratios, shock_params, model):
    try:
        import anthropic
    except ImportError:
        print("anthropic package not installed. Run: pip install -r requirements.txt")
        sys.exit(1)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY not found. Copy .env.example to .env and add your "
            "own key there. Never commit .env or paste your key into this script."
        )
        sys.exit(1)

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env (loaded via .env above)

    payload = {
        "companies": companies,
        "base_ratios": ratios,
        "anomalies": anomalies,
        "shock_params": shock_params,
        "shocked_ratios": shocked_ratios,
    }

    prompt = f"""You are a sell-side equity/credit analyst. Given the structured
financial ratio data below (base case and a stress-tested scenario), write a
concise analyst note (350-500 words) that:
1. Summarizes each company's financial health in 1-2 sentences.
2. Highlights the most material peer-relative anomalies and what they imply.
3. Explains how each company's earnings/margins respond to the stress
   scenario, and which company shows the most resilience vs. vulnerability.
4. Ends with a one-line takeaway per company.

Be quantitative and specific — cite the actual numbers. Do not hedge with
generic disclaimers.

DATA:
{json.dumps(payload, indent=2)}
"""

    response = client.messages.create(
        model=model,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
    return "\n".join(text_blocks), response.usage


# ---------------------------------------------------------------------------
# 5. CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Financial Statement Analyzer Agent")
    parser.add_argument("input_file", help="Path to JSON file with a list of companies")
    parser.add_argument("--revenue-decline-pct", type=float, default=10.0)
    parser.add_argument("--margin-compression-bps", type=float, default=0.0)
    parser.add_argument("--provision-increase-pct", type=float, default=0.0)
    parser.add_argument("--model", default="claude-fable-5",
                         help="Model to use for the narrative step (default: claude-fable-5)")
    parser.add_argument("--skip-narrative", action="store_true",
                         help="Only compute ratios/anomalies, skip the API call")
    parser.add_argument("--out", default="analysis_report.md")
    args = parser.parse_args()

    with open(args.input_file) as f:
        companies = json.load(f)

    base_ratios = {c["name"]: compute_ratios(c) for c in companies}
    anomalies = flag_anomalies(base_ratios)
    if len(companies) < 3:
        print(
            f"Note: anomaly detection skipped ({len(companies)} companies loaded, "
            "3+ required for a meaningful peer z-score).",
            file=sys.stderr,
        )

    shock_params = {
        "revenue_decline_pct": args.revenue_decline_pct,
        "margin_compression_bps": args.margin_compression_bps,
        "provision_increase_pct": args.provision_increase_pct,
    }
    shocked_companies = [apply_shock(c, **shock_params) for c in companies]
    shocked_ratios = {c["name"]: compute_ratios(c) for c in shocked_companies}

    print(json.dumps({"base_ratios": base_ratios, "anomalies": anomalies,
                       "shocked_ratios": shocked_ratios}, indent=2))

    if args.skip_narrative:
        return

    narrative, usage = generate_narrative(
        companies, base_ratios, anomalies, shocked_ratios, shock_params, args.model
    )

    with open(args.out, "w") as f:
        f.write("# Financial Statement Analysis Report\n\n")
        f.write(narrative)

    print(f"\n--- Report written to {args.out} ---")
    print(f"Token usage: input={usage.input_tokens}, output={usage.output_tokens}")


if __name__ == "__main__":
    main()
