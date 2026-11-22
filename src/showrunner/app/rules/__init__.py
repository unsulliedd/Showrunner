"""The cleanup rule sets the user keeps, and the one store the app reads them from."""

from showrunner.app.rules.store import RuleStore

# Shared by the plan, the clean engine and the rule editor, so an edit reaches all of them.
RULES = RuleStore()

__all__ = ["RULES", "RuleStore"]
