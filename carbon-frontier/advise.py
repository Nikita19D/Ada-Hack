"""Deterministic portfolio advice: pure math, no LLM, no new dependencies.
"""
from __future__ import annotations


def _shares(values, total):
    if not total or total <= 0:
        return [0.0 for _ in values]
    return [v / total for v in values]


def _hhi(fractions):
    return sum(f * f for f in fractions)


def advise_rules(selected_projects, risk_result, cost, target=100000):
    """Build summary, risks, and up to 3 suggestions from real numbers only."""
    projects = list(selected_projects or [])
    nominal = sum(float(p.get("co2", 0) or 0) for p in projects)
    n = len(projects)
    success = float(risk_result.get("success_probability", 0) or 0)
    expected = float(risk_result.get("expected_co2", 0) or 0)
    sims = risk_result.get("simulation_results") or []
    try:
        ordered = sorted(float(v) for v in sims)
    except (TypeError, ValueError):
        ordered = []
    p5 = ordered[max(0, int(0.05 * len(ordered)) - 1)] if ordered else 0.0
    biggest = max(projects, key=lambda p: float(p.get("co2", 0) or 0), default=None)
    biggest_share = (float(biggest.get("co2", 0) or 0) / nominal) if biggest and nominal > 0 else 0.0
    country_totals = {}
    for p in projects:
        country = str(p.get("country") or "Unknown")
        country_totals[country] = country_totals.get(country, 0.0) + float(p.get("co2", 0) or 0)
    country_hhi = _hhi(_shares(list(country_totals.values()), nominal))
    top_country = max(country_totals.items(), key=lambda kv: kv[1], default=("Unknown", 0.0))
    try:
        cost_value = float(cost)
    except (TypeError, ValueError):
        cost_value = 0.0
    cost_per_expected = (cost_value / expected) if expected > 0 else 0.0
    cushion = nominal - target
    gap_to_p5 = max(0.0, target - p5)
    prices = [float(p["price_per_credit"]) for p in projects
              if isinstance(p.get("price_per_credit"), (int, float))]
    cheapest_price = min(prices) if prices else None
    # Per-project expected loss: failure_prob * co2 * (1 - recovery)
    def _expected_loss(p):
        try:
            fp = float(p.get("failure_probability", 0) or 0)
        except (TypeError, ValueError):
            fp = 0.0
        try:
            rec = float(p.get("loss_recovery_fraction", 0) or 0)
        except (TypeError, ValueError):
            rec = 0.0
        return max(0.0, fp) * float(p.get("co2", 0) or 0) * (1.0 - max(0.0, min(1.0, rec)))
    riskiest = max(projects, key=_expected_loss, default=None)
    riskiest_loss = _expected_loss(riskiest) if riskiest is not None else 0.0
    try:
        riskiest_fp = float(riskiest.get("failure_probability", 0) or 0) if riskiest else 0.0
    except (TypeError, ValueError):
        riskiest_fp = 0.0
    expected_loss = max(0.0, nominal - expected)
    top_country_share = (top_country[1] / nominal) if nominal else 0.0
    # Quantiles for cushion math: p1 = only 1% of outcomes worse.
    p1 = ordered[max(0, int(0.01 * len(ordered)) - 1)] if ordered else 0.0
    need_99 = max(0.0, target - p1)
    need_95 = max(0.0, target - p5)
    summary = (
        f"{success:.0%} success across {len(ordered)} simulations. "
        f"Expected {expected:,.0f} from {nominal:,.0f} purchased "
        f"(~{expected_loss:,.0f} lost to failures)."
    )
    if riskiest is not None and riskiest_loss > 0:
        summary += (
            f" Riskiest: '{riskiest.get('project_name', riskiest.get('id'))}' "
            f"({riskiest_fp:.0%} x {float(riskiest.get('co2', 0) or 0):,.0f} = "
            f"~{riskiest_loss:,.0f} expected loss)."
        )
    summary += (
        f" Top country '{top_country[0]}' {top_country_share:.0%}."
        + (f" ${cost_per_expected:.2f} per expected tonne." if cost_per_expected else "")
    )
    risks = []
    if nominal < target:
        risks.append(
            f"Nominal cover is short: {nominal:,.0f} vs {target:,.0f} target, "
            "so even perfect delivery misses.")
    if biggest is not None and (biggest_share > 0.5 or n == 1):
        risks.append(
            f"Concentration: '{biggest.get('project_name', biggest.get('id'))}' "
            f"holds {biggest_share:.0%} of purchased credits.")
    if country_hhi > 0.5 and n > 1:
        risks.append(
            f"Country concentration: '{top_country[0]}' holds "
            f"{(top_country[1] / nominal if nominal else 0):.0%} of credits.")
    if success < 0.8:
        risks.append(
            f"Shortfall risk is {1 - success:.0%}: "
            f"weak outcomes deliver {p5:,.0f} tCO2e.")
    risks = risks[:2]
    if not risks:
        risks = ["Diversified enough at this size: no single project or country dominates."]
    suggestions = []
    if nominal < target:
        need = target - nominal
        extra = f" About ${need * cheapest_price:,.0f} at cheapest price." if cheapest_price else ""
        suggestions.append({
            "action": f"Add about {need:,.0f} tCO2e of cushion to reach nominal cover.",
            "why": "Below-target nominal cover fails even with zero failures.",
            "tradeoff": "Extra credits cost more budget." + extra})
    if biggest is not None and n > 1 and (biggest_share > 0.5 or country_hhi > 0.5):
        suggestions.append({
            "action": f"Move part of '{biggest.get('project_name', biggest.get('id'))}' to another country or type.",
            "why": f"One project holds {biggest_share:.0%}; spreads single-failure pain.",
            "tradeoff": "A second project may cost more per credit."})
    if n == 1 and nominal >= target:
        suggestions.append({
            "action": "Split this single project into two countries or types.",
            "why": "With one project, its failure is your portfolio failure.",
            "tradeoff": f"Keep total near {nominal:,.0f} tCO2e."})
    if success < 0.8 and nominal >= target and gap_to_p5 > 0:
        extra = f" About ${gap_to_p5 * cheapest_price:,.0f} at cheapest price." if cheapest_price else ""
        suggestions.append({
            "action": f"Add about {gap_to_p5:,.0f} tCO2e extra cushion to lift weak outcomes.",
            "why": f"Weak outcomes reach only {p5:,.0f} tCO2e vs {target:,.0f} target.",
            "tradeoff": "Extra credits cost more budget." + extra})
    if not suggestions:
        if success >= 0.9 and need_99 > 0:
            cost99 = f" About ${need_99 * cheapest_price:,.0f} at cheapest price." if cheapest_price else ""
            suggestions.append({
                "action": f"To lift 99% of outcomes above target, add ~{need_99:,.0f} tCO2e cushion.",
                "why": f"1% of outcomes fall to {p1:,.0f}; 97% success still leaves a bad tail.",
                "tradeoff": "Optional safety spend." + cost99})
        else:
            suggestions.append({
                "action": "Hold steady: cover and diversification look adequate.",
                "why": f"{success:.0%} success with expected {expected:,.0f} tCO2e.",
                "tradeoff": "Only add cushion if you want success above 90%."})
    suggestions = suggestions[:3]
    if biggest is not None and n > 1:
        move = float(biggest.get("co2", 0) or 0) * 0.2
        what_if = (f"Move ~{move:,.0f} (20%) of '{biggest.get('project_name', biggest.get('id'))}' "
                   f"({biggest_share:.0%} now) to another country and re-run.")
        if riskiest is not None and riskiest_loss > 0:
            what_if += (f" Or trim '{riskiest.get('project_name', riskiest.get('id'))}' "
                        f"(~{riskiest_loss:,.0f} expected loss) first.")
    else:
        what_if = "Try adding a second project in another country, then re-run."
    return {
        "summary": summary, "risks": risks, "suggestions": suggestions,
        "what_if": what_if,
        "metrics": {"nominal_co2": nominal, "expected_co2": expected,
                    "success_probability": success, "p5_co2": p5, "p1_co2": p1,
                    "expected_loss_co2": expected_loss,
                    "need_95_co2": need_95, "need_99_co2": need_99,
                    "biggest_share": biggest_share, "country_hhi": country_hhi,
                    "top_country": top_country[0], "top_country_share": top_country_share,
                    "riskiest_id": str(riskiest.get("id")) if riskiest else None,
                    "riskiest_name": str(riskiest.get("project_name", "")) if riskiest else None,
                    "riskiest_expected_loss": riskiest_loss,
                    "cost_per_expected_tonne": cost_per_expected,
                    "cushion_co2": cushion},
        "project_ids": [str(p.get("id")) for p in projects],
    }



