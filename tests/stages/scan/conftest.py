# ruff: noqa: RUF001 (Turkish letters are the point of this data)
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

TURKISH_LINES = [
    "Bu akşam çok yorgunum, çünkü bütün gün çalıştım.",
    "Yarın sabah erken kalkıp şehre gitmemiz gerekiyor.",
    "Çocuklar okuldan döndüğünde yemek hazır olmalı.",
    "Öğretmenin söylediği her şeyi dikkatle dinledim.",
    "Neden bana hiçbir şey anlatmadığını anlamıyorum.",
    "Güneş doğmadan önce yola çıkmak istiyorum.",
    "Bu işin ne kadar zor olduğunu sen de biliyorsun.",
    "Lütfen kapıyı kapat, dışarısı çok soğuk.",
    "Arkadaşlarım beni bekliyor, geç kalmak istemem.",
    "Şimdi eve gidip biraz dinlenmek en iyisi.",
    "Her zaman doğruyu söylediğini düşünüyordum.",
    "Bunu yarın konuşalım, şimdi çok geç oldu.",
]

ENGLISH_LINES = [
    "I am very tired tonight because I worked all day.",
    "We have to get up early tomorrow morning and go to town.",
    "The children are coming home from school, so dinner must be ready.",
    "I listened carefully to everything the teacher said.",
    "I do not understand why you never told me anything.",
    "I want to leave before the sun comes up.",
    "You know as well as I do how hard this job is.",
    "Please close the door, it is very cold outside.",
    "My friends are waiting for me and I do not want to be late.",
    "It is best to go home and rest for a while now.",
]


def srt_text(lines: list[str]) -> str:
    return "\n".join(f"{n}\n00:00:{n:02},000 --> 00:00:{n:02},500\n{line}\n" for n, line in enumerate(lines, 1))


@pytest.fixture
def turkish_cp1254() -> bytes:
    """Turkish subtitle text in the Windows-1254 code page, which is not valid UTF-8."""
    return srt_text(TURKISH_LINES).encode("cp1254")


@pytest.fixture
def english_utf8() -> bytes:
    return srt_text(ENGLISH_LINES).encode("utf-8")


@pytest.fixture
def make(tmp_path: Path) -> Callable[..., Path]:
    """Create a file below `tmp_path` and return its path; the content only has to exist unless a test reads it."""

    def make_file(relative: str, content: bytes = b"x") -> Path:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    return make_file
