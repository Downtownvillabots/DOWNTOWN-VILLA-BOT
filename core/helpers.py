import re

def render_caption(template, data):
    for key, value in data.items():
        template = template.replace("{" + key + "}", str(value))
    template = re.sub(r"{[^}]*}", "", template)
    return template

def human_size(size):
    size = float(size)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"

def extract_metadata_from_filename(filename):
    meta = {"quality": "", "year": "", "language": "", "season": "", "episode": "", "part": ""}
    if not filename:
        return meta
    q = re.search(r'(\d{3,4}[pP]|4K|2160p|1080p|720p|480p|360p)', filename)
    if q:
        meta["quality"] = q.group(1)
    y = re.search(r'(19\d{2}|20\d{2})', filename)
    if y:
        meta["year"] = y.group(1)
    langs = ["Hindi", "Tamil", "Telugu", "Malayalam", "English", "Kannada", "Bengali", "Punjabi"]
    for lang in langs:
        if lang.lower() in filename.lower():
            meta["language"] = lang
            break
    s = re.search(r'S(\d{1,2})', filename, re.IGNORECASE)
    if s:
        meta["season"] = "S" + s.group(1).zfill(2)
    e = re.search(r'E(\d{1,2})', filename, re.IGNORECASE)
    if e:
        meta["episode"] = "E" + e.group(1).zfill(2)
    p = re.search(r'Part\s*(\d+)|part(\d+)', filename, re.IGNORECASE)
    if p:
        meta["part"] = "Part " + (p.group(1) or p.group(2))
    return meta