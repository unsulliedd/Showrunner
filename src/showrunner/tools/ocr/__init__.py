"""Reading picture subtitles as text: Tesseract's language data and pgsrip's decoder and OCR engine."""

from showrunner.tools.ocr.pgs import CHUNK, READING, OcrError, read_pgs
from showrunner.tools.ocr.tesseract import DEFAULT_CODE, installed_languages, model_stamp, tesseract_code

__all__ = [
    "CHUNK",
    "DEFAULT_CODE",
    "READING",
    "OcrError",
    "installed_languages",
    "model_stamp",
    "read_pgs",
    "tesseract_code",
]
