"""What the app knows about each external program: where to find it, how to read its version, where to get it."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Feature(StrEnum):
    """Things the app can do only when some program is present. Shown to the user as `feature.<value>`."""

    MUX = "mux"
    EDIT_PROPERTIES = "edit_properties"
    EXTRACT_TRACKS = "extract_tracks"
    PROBE_MEDIA = "probe_media"
    CONVERT_AUDIO = "convert_audio"
    SYNC_FFSUBSYNC = "sync_ffsubsync"
    SYNC_ALASS = "sync_alass"
    SYNC_LAPSE = "sync_lapse"
    OCR = "ocr"
    TRANSLATE_OLLAMA = "translate_ollama"
    TRANSLATE_LLAMA_CPP = "translate_llama_cpp"
    PLAYER = "player"


class Archive(StrEnum):
    ZIP = "zip"
    SEVEN_ZIP = "7z"
    # Downloaded, then started for the user after they confirm; never unpacked by the app.
    INSTALLER = "installer"


@dataclass(frozen=True, slots=True)
class Variant:
    """One build of a program. Every pattern must match one asset of the release; all of them are installed
    into the same folder (a GPU build may need a separate runtime archive)."""

    id: str
    patterns: tuple[str, ...]
    archive: Archive


@dataclass(frozen=True, slots=True)
class GitHubRelease:
    """Assets of the newest release of `repo` whose assets match the variant. `prerelease` admits
    releases marked as pre-releases, for projects that publish their builds only that way."""

    repo: str
    variants: tuple[Variant, ...]
    prerelease: bool = False


@dataclass(frozen=True, slots=True)
class IndexedRelease:
    """A download whose version comes from a JSON index on the project's own site, with the file and its
    SHA-256 list at URLs built from that version."""

    index_url: str
    version_keys: tuple[str, ...]
    url_template: str
    sums_template: str
    variants: tuple[Variant, ...]


type Source = GitHubRelease | IndexedRelease


@dataclass(frozen=True, slots=True)
class DependencySpec:
    id: str
    # Program names without the Windows `.exe`; a name with its own extension (a library) is used as given.
    # The first one is probed for the version; the others must sit in the same folder.
    executables: tuple[str, ...]
    version_args: tuple[str, ...] | None
    # Group 1 is the version.
    version_pattern: str | None
    min_version: str | None
    official_url: str
    source: Source
    features: tuple[Feature, ...]
    # Environment variables in `%NAME%` form are expanded; folders whose variables are unset are skipped.
    install_dirs: tuple[str, ...] = field(default_factory=tuple)

    @property
    def name_key(self) -> str:
        return f"dependency.{self.id}"


_VERSION = r"(\d+(?:\.\d+)+)"

SPECS: tuple[DependencySpec, ...] = (
    DependencySpec(
        id="mkvtoolnix",
        executables=("mkvmerge", "mkvpropedit", "mkvextract"),
        version_args=("--version",),
        version_pattern=rf"mkvmerge v{_VERSION}",
        min_version="60.0",
        official_url="https://mkvtoolnix.download/",
        source=IndexedRelease(
            index_url="https://mkvtoolnix.download/latest-release.json",
            version_keys=("mkvtoolnix-releases", "latest-source", "version"),
            url_template="https://mkvtoolnix.download/windows/releases/{version}/mkvtoolnix-64-bit-{version}.zip",
            sums_template="https://mkvtoolnix.download/windows/releases/{version}/sha256sums.txt",
            variants=(Variant("default", (r"mkvtoolnix-64-bit-[\d.]+\.zip",), Archive.ZIP),),
        ),
        features=(Feature.MUX, Feature.EDIT_PROPERTIES, Feature.EXTRACT_TRACKS),
        install_dirs=(r"%ProgramFiles%\MKVToolNix", r"%ProgramFiles(x86)%\MKVToolNix"),
    ),
    DependencySpec(
        id="ffmpeg",
        executables=("ffmpeg", "ffprobe"),
        version_args=("-version",),
        version_pattern=rf"ffmpeg version n?{_VERSION}",
        min_version="6.0",
        official_url="https://ffmpeg.org/download.html",
        # The GitHub mirror of the gyan.dev release builds, which ffmpeg.org links for Windows.
        source=GitHubRelease(
            "GyanD/codexffmpeg",
            (Variant("default", (r"ffmpeg-[\d.]+-essentials_build\.zip",), Archive.ZIP),),
        ),
        features=(Feature.PROBE_MEDIA, Feature.CONVERT_AUDIO, Feature.SYNC_FFSUBSYNC),
    ),
    DependencySpec(
        id="tesseract",
        executables=("tesseract",),
        version_args=("--version",),
        version_pattern=rf"tesseract v?{_VERSION}",
        min_version="5.0",
        official_url="https://github.com/UB-Mannheim/tesseract/wiki",
        source=GitHubRelease(
            "UB-Mannheim/tesseract",
            (Variant("default", (r"tesseract-ocr-w64-setup-[\w.]+\.exe",), Archive.INSTALLER),),
        ),
        features=(Feature.OCR,),
        install_dirs=(r"%ProgramFiles%\Tesseract-OCR", r"%LOCALAPPDATA%\Programs\Tesseract-OCR"),
    ),
    DependencySpec(
        id="ollama",
        executables=("ollama",),
        # Never run: on Windows the command starts the desktop app. Its state and version come from its server.
        version_args=None,
        version_pattern=None,
        min_version="0.5.0",
        official_url="https://ollama.com/download/windows",
        source=GitHubRelease("ollama/ollama", (Variant("default", (r"ollama-windows-amd64\.zip",), Archive.ZIP),)),
        features=(Feature.TRANSLATE_OLLAMA,),
        install_dirs=(r"%LOCALAPPDATA%\Programs\Ollama",),
    ),
    DependencySpec(
        id="llama_cpp",
        executables=("llama-server",),
        version_args=("--version",),
        # Builds are numbered, not versioned: "version: 12366 (abc1234)".
        version_pattern=r"version: (\d+)",
        min_version=None,
        official_url="https://github.com/ggml-org/llama.cpp",
        # Every build is published as a pre-release; the latest full release carries no binaries.
        source=GitHubRelease(
            "ggml-org/llama.cpp",
            (
                Variant("vulkan", (r"llama-b\d+-bin-win-vulkan-x64\.zip",), Archive.ZIP),
                Variant(
                    "cuda",
                    (r"llama-b\d+-bin-win-cuda-12\.\d+-x64\.zip", r"cudart-llama-bin-win-cuda-12\.\d+-x64\.zip"),
                    Archive.ZIP,
                ),
                Variant("cpu", (r"llama-b\d+-bin-win-cpu-x64\.zip",), Archive.ZIP),
            ),
            prerelease=True,
        ),
        features=(Feature.TRANSLATE_LLAMA_CPP,),
    ),
    DependencySpec(
        id="alass",
        executables=("alass-cli",),
        version_args=("--version",),
        version_pattern=rf"alass-cli {_VERSION}",
        min_version="2.0.0",
        official_url="https://github.com/kaegi/alass",
        source=GitHubRelease("kaegi/alass", (Variant("default", (r"alass-windows64\.zip",), Archive.ZIP),)),
        features=(Feature.SYNC_ALASS,),
    ),
    DependencySpec(
        id="libmpv",
        executables=("libmpv-2.dll",),
        version_args=None,
        version_pattern=None,
        min_version=None,
        official_url="https://mpv.io/installation/",
        # The x86-64-v3 builds need AVX2; the plain build runs on every 64-bit processor.
        source=GitHubRelease(
            "shinchiro/mpv-winbuild-cmake",
            (Variant("default", (r"mpv-dev-x86_64-\d{8}-git-[0-9a-f]+\.7z",), Archive.SEVEN_ZIP),),
        ),
        features=(Feature.PLAYER,),
    ),
    DependencySpec(
        id="lapse",
        executables=("lapse",),
        version_args=("--version",),
        version_pattern=_VERSION,
        min_version="2.0.0",
        official_url="https://github.com/Schwponaco-org/lapse",
        source=GitHubRelease("Schwponaco-org/lapse", (Variant("default", (r"lapse-windows-x64\.zip",), Archive.ZIP),)),
        features=(Feature.SYNC_LAPSE,),
    ),
)

SPEC_BY_ID: dict[str, DependencySpec] = {spec.id: spec for spec in SPECS}
