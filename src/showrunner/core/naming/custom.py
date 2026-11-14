"""Tokens the user defines. They are stored in the naming options, so every profile has its own.

- constant: a fixed text, for example `group` = `GRP`.
- composite: a template of other tokens, for example `quality` = `{resolution}[ {hdr}] {source}`.
- pattern: the first group of a regular expression searched in the file name or in a parent folder's name,
  for example `release_group` = `-([^-]+)$`.

A value map (`token name -> {value read -> text to use}`) rewrites any token, built-in or defined here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CustomKind(StrEnum):
    CONSTANT = "constant"
    COMPOSITE = "composite"
    PATTERN = "pattern"


class PatternSource(StrEnum):
    FILE_NAME = "file-name"  # without the extension
    FOLDER_1 = "folder-1"  # the folder holding the file
    FOLDER_2 = "folder-2"
    FOLDER_3 = "folder-3"


@dataclass(frozen=True, slots=True)
class CustomToken:
    # Lower case letters, digits and underscores, starting with a letter or underscore.
    name: str = ""
    kind: CustomKind = CustomKind.CONSTANT
    # The fixed text (constant), the template (composite) or the regular expression (pattern).
    text: str = ""
    # Patterns only.
    source: PatternSource = PatternSource.FILE_NAME
