"""Whisper language table: Whisper code -> (English name, ISO 639-2/B code).

MKV and MP4 both expect ISO 639-2 three-letter codes in the `language` tag.
"""

from __future__ import annotations

# whisper code: (name, iso639-2/B)
LANGUAGES: dict[str, tuple[str, str]] = {
    "en": ("English", "eng"),
    "zh": ("Chinese", "chi"),
    "de": ("German", "ger"),
    "es": ("Spanish", "spa"),
    "ru": ("Russian", "rus"),
    "ko": ("Korean", "kor"),
    "fr": ("French", "fre"),
    "ja": ("Japanese", "jpn"),
    "pt": ("Portuguese", "por"),
    "tr": ("Turkish", "tur"),
    "pl": ("Polish", "pol"),
    "ca": ("Catalan", "cat"),
    "nl": ("Dutch", "dut"),
    "ar": ("Arabic", "ara"),
    "sv": ("Swedish", "swe"),
    "it": ("Italian", "ita"),
    "id": ("Indonesian", "ind"),
    "hi": ("Hindi", "hin"),
    "fi": ("Finnish", "fin"),
    "vi": ("Vietnamese", "vie"),
    "he": ("Hebrew", "heb"),
    "uk": ("Ukrainian", "ukr"),
    "el": ("Greek", "gre"),
    "ms": ("Malay", "may"),
    "cs": ("Czech", "cze"),
    "ro": ("Romanian", "rum"),
    "da": ("Danish", "dan"),
    "hu": ("Hungarian", "hun"),
    "ta": ("Tamil", "tam"),
    "no": ("Norwegian", "nor"),
    "th": ("Thai", "tha"),
    "ur": ("Urdu", "urd"),
    "hr": ("Croatian", "hrv"),
    "bg": ("Bulgarian", "bul"),
    "lt": ("Lithuanian", "lit"),
    "la": ("Latin", "lat"),
    "mi": ("Maori", "mao"),
    "ml": ("Malayalam", "mal"),
    "cy": ("Welsh", "wel"),
    "sk": ("Slovak", "slo"),
    "te": ("Telugu", "tel"),
    "fa": ("Persian", "per"),
    "lv": ("Latvian", "lav"),
    "bn": ("Bengali", "ben"),
    "sr": ("Serbian", "srp"),
    "az": ("Azerbaijani", "aze"),
    "sl": ("Slovenian", "slv"),
    "kn": ("Kannada", "kan"),
    "et": ("Estonian", "est"),
    "mk": ("Macedonian", "mac"),
    "br": ("Breton", "bre"),
    "eu": ("Basque", "baq"),
    "is": ("Icelandic", "ice"),
    "hy": ("Armenian", "arm"),
    "ne": ("Nepali", "nep"),
    "mn": ("Mongolian", "mon"),
    "bs": ("Bosnian", "bos"),
    "kk": ("Kazakh", "kaz"),
    "sq": ("Albanian", "alb"),
    "sw": ("Swahili", "swa"),
    "gl": ("Galician", "glg"),
    "mr": ("Marathi", "mar"),
    "pa": ("Punjabi", "pan"),
    "si": ("Sinhala", "sin"),
    "km": ("Khmer", "khm"),
    "sn": ("Shona", "sna"),
    "yo": ("Yoruba", "yor"),
    "so": ("Somali", "som"),
    "af": ("Afrikaans", "afr"),
    "oc": ("Occitan", "oci"),
    "ka": ("Georgian", "geo"),
    "be": ("Belarusian", "bel"),
    "tg": ("Tajik", "tgk"),
    "sd": ("Sindhi", "snd"),
    "gu": ("Gujarati", "guj"),
    "am": ("Amharic", "amh"),
    "yi": ("Yiddish", "yid"),
    "lo": ("Lao", "lao"),
    "uz": ("Uzbek", "uzb"),
    "fo": ("Faroese", "fao"),
    "ht": ("Haitian Creole", "hat"),
    "ps": ("Pashto", "pus"),
    "tk": ("Turkmen", "tuk"),
    "nn": ("Nynorsk", "nno"),
    "mt": ("Maltese", "mlt"),
    "sa": ("Sanskrit", "san"),
    "lb": ("Luxembourgish", "ltz"),
    "my": ("Myanmar", "bur"),
    "bo": ("Tibetan", "tib"),
    "tl": ("Tagalog", "tgl"),
    "mg": ("Malagasy", "mlg"),
    "as": ("Assamese", "asm"),
    "tt": ("Tatar", "tat"),
    "haw": ("Hawaiian", "haw"),
    "ln": ("Lingala", "lin"),
    "ha": ("Hausa", "hau"),
    "ba": ("Bashkir", "bak"),
    "jw": ("Javanese", "jav"),
    "su": ("Sundanese", "sun"),
    "yue": ("Cantonese", "chi"),
}


def name_of(code: str | None) -> str:
    if not code:
        return "Unknown"
    return LANGUAGES.get(code, (code, "und"))[0]


def iso639_2(code: str | None) -> str:
    if not code:
        return "und"
    return LANGUAGES.get(code, ("", "und"))[1]


def sorted_choices() -> list[tuple[str, str]]:
    """(code, name) sorted by name, for dropdowns."""
    return sorted(((c, n) for c, (n, _) in LANGUAGES.items()), key=lambda x: x[1])
