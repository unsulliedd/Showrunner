"""The rule sets there are: cleanit's own, read only, and the user's, one YAML file each in a folder."""

from __future__ import annotations

import pkgutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path

from showrunner.core.language import Language
from showrunner.tools.cleanit.engine import (
    CleanitUnavailableError,
    CompiledRules,
    check_rule,
    cleanit_module,
    compile_sets,
)
from showrunner.tools.cleanit.files import (
    FILE_PREFIX,
    FILE_SUFFIX,
    NAME_PATTERN,
    ParsedFile,
    RulesFileError,
    parse_file,
    set_name_of,
)
from showrunner.tools.cleanit.model import RuleSet

# Cleanit's sets in the order a person looks for them.
BUILTIN_ORDER = ("no-sdh", "no-lyrics", "no-spam", "no-style", "tidy", "ocr")
# The set picture subtitles read by OCR always get, and the user's own additions to it, which run with it.
OCR_SET = "ocr"
OCR_EXTRA = "ocr-fixes"
# The file that pauses built-in rules by name; it is no set of its own.
PAUSES = "pauses"
# Sets that are applied by the app itself, not chosen on a place.
NOT_CHOSEN = (OCR_SET, OCR_EXTRA)


@dataclass(frozen=True, slots=True)
class Problem:
    """A file of the user's rules that was not read, with why; its set is left out until the file is fixed."""

    file: str
    message: str


@dataclass(frozen=True, slots=True)
class RuleBook:
    """Every rule set at one moment: the built-in ones first, then the user's in name order."""

    sets: Mapping[str, RuleSet] = field(default_factory=dict)
    problems: tuple[Problem, ...] = ()

    def own(self) -> tuple[RuleSet, ...]:
        return tuple(rule_set for rule_set in self.sets.values() if not rule_set.builtin)

    def chosen(self) -> tuple[RuleSet, ...]:
        """The sets a place can choose for cleanup."""
        return tuple(rule_set for name, rule_set in self.sets.items() if name not in NOT_CHOSEN)

    def known(self, names: Iterable[str]) -> tuple[RuleSet, ...]:
        """The sets of `names` that exist, in the order given: a set that was deleted or whose file is broken is
        left out."""
        return tuple(self.sets[name] for name in names if name in self.sets)

    def compile(self, names: Iterable[str], language: Language | None) -> CompiledRules:
        return compile_sets(self.known(names), language)

    def ocr(self, language: Language | None) -> CompiledRules:
        """The OCR fixes for a language: cleanit's set and the user's additions to it."""
        return self.compile((OCR_SET, OCR_EXTRA), language)


def valid_name(name: str) -> str:
    """Why `name` cannot be an own set's, or an empty string."""
    if not NAME_PATTERN.fullmatch(name):
        return "characters"
    # File names are not case sensitive on Windows, so `Tidy` and `tidy` would be one file.
    if name.casefold() in {*BUILTIN_ORDER, PAUSES}:
        return "taken"
    return ""


@lru_cache(maxsize=1)
def builtin_sets() -> dict[str, RuleSet]:
    """Cleanit's own sets, by name, with every rule on. Raises `CleanitUnavailableError`."""
    files = cleanit_module("data").default_config_resources
    rules: dict[str, list[ParsedFile]] = {}
    for file in files:
        if not file.startswith(FILE_PREFIX):
            continue  # the base file holds the words for character ranges only
        name = file.removeprefix(FILE_PREFIX).removesuffix(FILE_SUFFIX).split(".")[0]
        data = pkgutil.get_data("cleanit", f"data/{file}")
        if data is not None:
            rules.setdefault(name, []).append(parse_file(data.decode("utf-8")))
    return {
        name: RuleSet(name, tuple(rule for parsed in rules[name] for rule in parsed.rules), builtin=True)
        for name in BUILTIN_ORDER
        if name in rules
    }


type _Read = RuleSet | Problem | frozenset[str]  # an own set, the file's problem, or the rules a pauses file pauses
type Cache = dict[tuple[str, int, int], _Read]


def load_book(folder: Path | None, cache: Cache | None = None) -> RuleBook:
    """The built-in sets and the sets of the YAML files in `folder`, which may be missing. `cache` keeps what each file
    read as, by its name, time and size, so a long set is checked once and not at every change of a file beside it."""
    cache = {} if cache is None else cache
    try:
        sets = dict(builtin_sets())
    except (CleanitUnavailableError, RulesFileError) as error:
        return RuleBook({}, (Problem("cleanit", str(error)),))
    problems: list[Problem] = []
    paused: frozenset[str] = frozenset()
    own: dict[str, RuleSet] = {}
    keys = signature(folder) if folder is not None else ()
    for key in keys:
        if key not in cache and folder is not None:
            cache[key] = _read_own(folder / key[0])
        found = cache[key]
        if isinstance(found, Problem):
            problems.append(found)
        elif isinstance(found, frozenset):
            paused = found
        else:
            own[found.name] = found
    for stale in set(cache) - set(keys):
        del cache[stale]  # a file that changed or went
    for name, rule_set in sets.items():
        sets[name] = replace(rule_set, rules=tuple(replace(r, paused=r.name in paused) for r in rule_set.rules))
    return RuleBook({**sets, **own}, tuple(problems))


def _read_own(path: Path) -> _Read:
    name = set_name_of(path.name) or ""
    try:
        parsed = parse_file(path.read_text(encoding="utf-8"))
        if name == PAUSES:
            return parsed.paused
        if message := valid_name(name):
            raise RulesFileError(message)
        for rule in parsed.rules:
            if error := check_rule(rule, parsed.aliases):
                raise RulesFileError(f"{rule.name}: {error}")
    except (OSError, UnicodeDecodeError, RulesFileError) as error:
        return Problem(path.name, str(error))
    return RuleSet(name, parsed.rules, aliases=parsed.aliases)


def signature(folder: Path) -> tuple[tuple[str, int, int], ...]:
    """What the folder's rule files are now: when it changes, the book is read again."""
    found = []
    try:
        for path in sorted(folder.iterdir()):
            if set_name_of(path.name) is not None:
                info = path.stat()
                found.append((path.name, info.st_mtime_ns, info.st_size))
    except OSError:
        pass
    return tuple(found)
