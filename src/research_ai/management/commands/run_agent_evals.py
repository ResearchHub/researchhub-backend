from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from research_ai.evals.cases import AGENTS, load_cases
from research_ai.evals.harness import AgentEvalHarness
from research_ai.evals.report import (
    ScoredRun,
    build_report,
    format_summary,
    write_report,
)
from research_ai.evals.scorers import score_run


class Command(BaseCommand):
    help = (
        "Run the assistant and notebook chat agents against the eval cases in "
        "research_ai/evals/cases with a real model, score each run, and write "
        "a JSON report. Commits users, notes, and chats: run it on a "
        "throwaway stack (scripts/stack.sh), never a shared database."
    )

    def add_arguments(self, parser):
        parser.add_argument("--agent", choices=AGENTS, help="Only this agent's cases.")
        parser.add_argument(
            "--cases",
            default="*",
            help="Glob over case ids, e.g. 'notebook/*' or '*citation*'.",
        )
        parser.add_argument(
            "--model",
            help="Catalog model ref (provider:model). Defaults to the tier default.",
        )
        parser.add_argument("--trials", type=int, default=1)
        parser.add_argument("--tag", default="", help="Label for this run's report.")
        parser.add_argument(
            "--out",
            default="agent-eval-reports",
            help="Directory for the JSON report.",
        )

    def handle(self, *args, **options):
        if settings.PRODUCTION or settings.STAGING:
            raise CommandError("Agent evals write fixture data; not on a shared env.")
        if options["trials"] < 1:
            raise CommandError("--trials must be at least 1")
        cases = load_cases(agent=options["agent"], pattern=options["cases"])
        if not cases:
            raise CommandError("No cases match.")

        harness = AgentEvalHarness(model_ref=options["model"])
        started_at = datetime.now()
        results = []
        for case in cases:
            for trial in range(options["trials"]):
                self.stdout.write(f"{case.id} #{trial} ...", ending="")
                self.stdout.flush()
                run = harness.run(case, trial=trial)
                results.append(ScoredRun(case, run, score_run(case, run)))
                status = "crashed" if run.error else f"{run.elapsed_s}s"
                self.stdout.write(f" {status}")

        model = options["model"] or next(
            (result.run.model for result in results if result.run.model), ""
        )
        report = build_report(
            results, model=model, tag=options["tag"], started_at=started_at
        )
        path = write_report(report, Path(options["out"]))
        self.stdout.write("")
        self.stdout.write(format_summary(report))
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Report: {path}"))
