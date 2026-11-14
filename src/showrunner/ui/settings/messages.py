"""The words for each problem the engines report, with the fix a field can apply."""

from __future__ import annotations

from collections.abc import Sequence

from showrunner.core.language import common_codes
from showrunner.core.naming import Problem, ProblemKind
from showrunner.stages.tracks import RuleProblem, RuleProblemKind
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.settings.problem_field import FieldProblem, suggest


def problem_text(kind: str, detail: str = "") -> str:
    return tr(f"problem.{kind.replace('-', '_')}", detail=detail)


def template_problem(problem: Problem, names: Sequence[str]) -> FieldProblem:
    """`names` are the token names a misspelt one is compared with."""
    if problem.kind is ProblemKind.UNKNOWN_TOKEN and (near := suggest(problem.detail, names)):
        token = f"{{{near}}}"
        message = f"{problem_text(problem.kind, problem.detail)} {tr('problem.did_you_mean', token=token)}"
        return FieldProblem(problem.start, problem.end, message, (tr("problem.use", text=token), token))
    return FieldProblem(problem.start, problem.end, problem_text(problem.kind, problem.detail))


def rule_problem(problem: RuleProblem, start: int = 0) -> FieldProblem:
    """`start` is where the entry or the pattern begins in the field's text."""
    begin, end = start + problem.start, start + problem.end
    if problem.kind is RuleProblemKind.NOT_A_LANGUAGE and (near := suggest(problem.detail.casefold(), common_codes())):
        message = f"{problem_text(problem.kind, problem.detail)} {tr('problem.did_you_mean', token=near)}"
        return FieldProblem(begin, end, message, (tr("problem.use", text=near), near))
    return FieldProblem(begin, end, problem_text(problem.kind, problem.detail))
