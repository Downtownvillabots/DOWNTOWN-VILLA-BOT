"""
Centralised alias maps for indexing engine.
Edit here only — never scatter these across files.
"""
import re

# ─────────── Language aliases → canonical ───────────
LANGUAGE_ALIASES = {
    # English
    "eng": "ENGLISH", "en": "ENGLISH", "english": "ENGLISH", "eng.": "ENGLISH",
    # Hindi
    "hin": "HINDI", "hi": "HINDI", "hindi": "HINDI",
    # Malayalam
    "mal": "MALAYALAM", "ml": "MALAYALAM", "malayalam": "MALAYALAM",
    # Tamil
    "tam": "TAMIL", "ta": "TAMIL", "tamil": "TAMIL",
    # Telugu
    "tel": "TELUGU", "te": "TELUGU", "telugu": "TELUGU",
    # Kannada
    "kan": "KANNADA", "kn": "KANNADA", "kannada": "KANNADA",
    # Bengali
    "ben": "BENGALI", "bn": "BENGALI", "bengali": "BENGALI",
    # Marathi
    "mar": "MARATHI", "mr": "MARATHI", "marathi": "MARATHI",
    # Punjabi
    "pun": "PUNJABI", "pa": "PUNJABI", "punjabi": "PUNJABI",
    # Gujarati
    "guj": "GUJARATI", "gu": "GUJARATI", "gujarati": "GUJARATI",
    # Urdu
    "urd": "URDU", "ur": "URDU", "urdu": "URDU",
    # Arabic
    "ara": "ARABIC", "ar": "ARABIC", "arabic": "ARABIC",
    # Spanish
    "spa": "SPANISH", "es": "SPANISH", "spanish": "SPANISH",
    # French
    "fre": "FRENCH", "fra": "FRENCH", "fr": "FRENCH", "french": "FRENCH",
    # German
    "ger": "GERMAN", "deu": "GERMAN", "de": "GERMAN", "german": "GERMAN",
    # Japanese
    "jpn": "JAPANESE", "jp": "JAPANESE", "ja": "JAPANESE", "japanese": "JAPANESE",
    # Korean
    "kor": "KOREAN", "ko": "KOREAN", "korean": "KOREAN",
    # Chinese
    "chi": "CHINESE", "zho": "CHINESE", "zh": "CHINESE", "chinese": "CHINESE",
    # Russian
    "rus": "RUSSIAN", "ru": "RUSSIAN", "russian": "RUSSIAN",
    # Portuguese
    "por": "PORTUGUESE", "pt": "PORTUGUESE", "portuguese": "PORTUGUESE",
    # Italian
    "ita": "ITALIAN", "it": "ITALIAN", "italian": "ITALIAN",
    # Turkish
    "tur": "TURKISH", "tr": "TURKISH", "turkish": "TURKISH",
    # Dutch
    "dut": "DUTCH", "nld": "DUTCH", "nl": "DUTCH", "dutch": "DUTCH",
    # Multi
    "multi": "MULTI",
}

# ─────────── Subtitle aliases ───────────
SUBTITLE_KEYWORDS = {
    "sub", "subs", "subtitle", "subtitles", "msub", "msubtitle", "esub",
    "esubs", "vostfr", "srt", "vtt", "ass",
}
SUBTITLE_PHRASES = re.compile(
    r"\b(eng|en|english|hin|hindi|mal|malayalam|tam|tamil|tel|telugu|kan|kannada|"
    r"ara|arabic|spa|spanish|fre|french|ger|german|jpn|japanese|kor|korean|"
    r"chi|chinese|rus|russian)\s+sub(s|titles)?\b",
    re.IGNORECASE,
)

# ─────────── Quality aliases → canonical ───────────
QUALITY_ALIASES = {
    "4k": "2160p", "uhd": "2160p", "2160": "2160p", "2160p": "2160p",
    "2k": "1440p", "1440": "1440p", "1440p": "1440p",
    "fhd": "1080p", "fullhd": "1080p", "1080": "1080p", "1080p": "1080p",
    "1080i": "1080i",
    "hd": "720p", "720": "720p", "720p": "720p",
    "576": "576p", "576p": "576p",
    "480": "480p", "480p": "480p", "sd": "480p",
    "360": "360p", "360p": "360p",
}
# Priority for choosing among multiple matches
QUALITY_PRIORITY = ["2160p", "1440p", "1080p", "1080i", "720p", "576p", "480p", "360p"]

# ─────────── Codec aliases → canonical ───────────
CODEC_ALIASES = {
    "hevc": "HEVC", "h265": "HEVC", "h.265": "HEVC", "x265": "HEVC",
    "h264": "H264", "h.264": "H264", "x264": "H264", "avc": "H264",
    "av1": "AV1",
    "vp9": "VP9", "vp8": "VP8",
    "mpeg2": "MPEG2", "mpeg4": "MPEG4",
}

# ─────────── Source aliases → canonical ───────────
SOURCE_ALIASES = {
    "webdl": "WEB-DL", "web-dl": "WEB-DL", "web": "WEB",
    "webrip": "WEBRip", "web-rip": "WEBRip",
    "bluray": "BluRay", "blu-ray": "BluRay", "brrip": "BRRip", "br-rip": "BRRip",
    "bdrip": "BDRip", "bd-rip": "BDRip",
    "hdrip": "HDRip", "hd-rip": "HDRip",
    "dvdrip": "DVDRip", "dvd-rip": "DVDRip", "dvd": "DVD",
    "hdtv": "HDTV", "hd-tv": "HDTV",
    "hdcam": "HDCAM", "hdcamrip": "HDCAM",
    "cam": "CAM", "camrip": "CAM",
    "ts": "TS", "tc": "TC", "r5": "R5",
    "dvdscr": "DVDScr", "dvd-scr": "DVDScr",
    "predvd": "PreDVD", "predvdrip": "PreDVD",
    "prehd": "PreHD",
    "amzn": "AMZN", "amazon": "AMZN",
    "nf": "NF", "netflix": "NF",
    "dsnp": "DSNP", "disney": "DSNP",
    "atvp": "ATVP", "apple": "ATVP",
    "hmax": "HMAX", "hbo": "HMAX",
    "pcok": "PCOK",
    "hulu": "HULU",
    "zee5": "ZEE5", "zee": "ZEE5",
    "hotstar": "HOTSTAR", "dsnp-hs": "HOTSTAR",
    "sonyliv": "SONYLIV",
    "voot": "VOOT",
    "mx": "MX",
    "jio": "JIO",
    "aha": "AHA",
    "sun": "SUNNXT", "sunnxt": "SUNNXT",
}

# ─────────── Release group / misc tokens to strip from titles ───────────
MISC_NOISE = {
    "remux", "proper", "repack", "extended", "unrated", "directors", "cut",
    "imax", "hybrid", "limited", "internal", "complete", "amzn", "nf",
    "atmos", "truehd", "dts", "dts-hd", "dtshd", "ac3", "eac3", "ddp5",
    "ddp5.1", "ddp", "aac", "aac2", "aac5", "aac5.1", "dolby", "dolbyvision",
    "dovi", "hdr", "hdr10", "hdr10plus", "sdr", "10bit", "8bit", "10-bit",
    "8-bit", "60fps", "30fps", "24fps", "hdrip", "x265-", "x264-",
}

# ─────────── Prefix/suffix watermarks to strip from filenames ───────────
# Removes @username, @channelname, [Channel], (Channel), etc. at start
PREFIX_PATTERNS = [
    re.compile(r"^@\w+[\s._\-]+", re.IGNORECASE),
    re.compile(r"^\[[^\]]+\][\s._\-]+"),
    re.compile(r"^\([^\)]+\)[\s._\-]+"),
    re.compile(r"^\w+\.(com|net|org|to|cc|me|tv|in)[\s._\-]+", re.IGNORECASE),
    re.compile(r"^www\.[\s._\-]+", re.IGNORECASE),
]
# Any remaining @user, @channel anywhere in text
AT_MENTION = re.compile(r"@\w+", re.IGNORECASE)
