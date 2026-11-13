"""Language value type; the only module that imports babelfish."""

from __future__ import annotations

from dataclasses import dataclass

from babelfish import Language as _Babelfish
from babelfish.exceptions import Error as _BabelfishError


@dataclass(frozen=True, slots=True)
class Language:
    """A language by identity: `tr` and `tur` give equal values.

    The region and script are part of the identity, so `pt-BR` differs from `pt`.
    """

    alpha3: str
    region: str | None = None
    script: str | None = None

    def __post_init__(self) -> None:
        # Raises ValueError for a code babelfish does not know.
        self._babelfish()

    def _babelfish(self) -> _Babelfish:
        return _Babelfish(self.alpha3, self.region, self.script)

    @property
    def ietf(self) -> str:
        """Shortest IETF tag: `tr`, `pt-BR`, `zh-Hant`; the 3-letter code when no 2-letter one exists."""
        return str(self._babelfish())

    @property
    def name(self) -> str:
        """English name."""
        return self._babelfish().name

    @classmethod
    def parse(cls, text: str) -> Language | None:
        """Read an IETF tag, an ISO 639-2 code (either form) or an English name.

        Returns None for text that is not a language and for `und` (undetermined).
        """
        text = text.strip()
        for read in (_Babelfish.fromietf, _Babelfish.fromalpha3b, _Babelfish.fromname):
            try:
                found = read(text)
            except (ValueError, _BabelfishError):
                continue
            if found.alpha3 == "und":
                return None
            return cls(
                found.alpha3,
                found.country.alpha2 if found.country else None,
                found.script.code if found.script else None,
            )
        return None
