"""Eval results: a JSON report on disk and a plain-text summary.

The JSON keeps every run in full (trace digest, notes before and after, each
score's details), so a report can be re-scored or diffed against another one
without re-running the model.
"""

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean

from research_ai.evals.cases import EvalCase
from research_ai.evals.harness import CaseRun
from research_ai.evals.scorers import Score


@dataclass
class ScoredRun:
    case: EvalCase
    run: CaseRun
    scores: list[Score]


def build_report(
    results: list[ScoredRun], *, model: str, tag: str, started_at: datetime
) -> dict:
    by_scorer = defaultdict(list)
    by_case = defaultdict(lambda: defaultdict(list))
    for result in results:
        for score in result.scores:
            by_scorer[score.name].append(score.value)
            by_case[result.case.id][score.name].append(score.value)
    cost_microusd = sum(
        turn.cost_microusd for result in results for turn in result.run.turns
    )
    return {
        "tag": tag,
        "model": model,
        "started_at": started_at.isoformat(),
        "summary": {
            "runs": len(results),
            "crashed_runs": sum(1 for result in results if result.run.error),
            "cost_usd": round(cost_microusd / 1_000_000, 4),
            "by_scorer": {name: _mean(values) for name, values in by_scorer.items()},
            "by_case": {
                case_id: {name: _mean(values) for name, values in scores.items()}
                for case_id, scores in by_case.items()
            },
        },
        "runs": [
            {
                "case_id": result.case.id,
                "trial": result.run.trial,
                "scores": [asdict(score) for score in result.scores],
                "run": asdict(result.run),
            }
            for result in results
        ],
    }


def write_report(report: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = report["started_at"].replace(":", "").split(".")[0]
    name = f"{stamp}-{report['tag']}.json" if report["tag"] else f"{stamp}.json"
    path = out_dir / name
    path.write_text(json.dumps(report, indent=2, default=str))
    return path


def format_summary(report: dict) -> str:
    summary = report["summary"]
    scorers = sorted(summary["by_scorer"])
    width = max([len(case_id) for case_id in summary["by_case"]] + [4])
    lines = [
        f"model {report['model'] or '(tier default)'}  tag {report['tag'] or '-'}  "
        f"runs {summary['runs']}  crashed {summary['crashed_runs']}  "
        f"cost ${summary['cost_usd']:.4f}",
        "",
        "case".ljust(width) + "  " + "  ".join(scorers),
    ]
    for case_id, scores in sorted(summary["by_case"].items()):
        cells = [_cell(scores.get(name), len(name)) for name in scorers]
        lines.append(case_id.ljust(width) + "  " + "  ".join(cells))
    cells = [_cell(summary["by_scorer"][name], len(name)) for name in scorers]
    lines.append("all".ljust(width) + "  " + "  ".join(cells))
    failures = [
        f"  {run['case_id']} #{run['trial']} {score['name']}: {detail}"
        for run in report["runs"]
        for score in run["scores"]
        if score["value"] < 1
        for detail in score["details"][:3]
    ]
    if failures:
        lines += ["", "failures:", *failures]
    return "\n".join(lines)


def _mean(values: list[float]) -> float:
    return round(mean(values), 3)


def _cell(value: float | None, width: int) -> str:
    return ("-" if value is None else f"{value:.2f}").rjust(width)
