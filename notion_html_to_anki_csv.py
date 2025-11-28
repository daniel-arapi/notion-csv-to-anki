from bs4 import BeautifulSoup
import csv, re
from pathlib import Path

CSS_COLOR_MAP = {
    "default": "black",
    "gray": "gray",
    "brown": "saddlebrown",
    "orange": "orange",
    "yellow": "gold",
    "teal": "teal",
    "blue": "blue",
    "purple": "purple",
    "pink": "deeppink",
    "red": "red",
}

ALLOWED_TAGS = {
    "strong", "b", "em", "i", "u",
    "code", "pre", "span", "br",
    "ul", "ol", "li", "a", "div"
}

def merge_style(el, new_rules):
    existing = el.get("style", "").strip().rstrip(";")
    el["style"] = (existing + ";" + new_rules) if existing else new_rules

def convert_color_classes_to_inline(el):
    classes = el.get("class", [])
    if not classes:
        return

    for cls in list(classes):
        m = re.match(r"(?:highlight|block-color)-([a-z_]+)$", cls)
        if not m:
            continue

        key = m.group(1)

        # Only apply text colors, not background colors
        if not key.endswith("_background"):
            col = CSS_COLOR_MAP.get(key)
            if col:
                merge_style(el, f"color:{col}")

        classes.remove(cls)

    if classes:
        el["class"] = classes
    else:
        el.attrs.pop("class", None)

def sanitize_inline_html(cell, strip_all=False):
    if strip_all:
        return cell.get_text(" ", strip=True)

    # Replace <mark> with <span> to avoid highlight
    for mark in cell.find_all("mark"):
        mark.name = "span"
        convert_color_classes_to_inline(mark)

    # Convert color classes
    for el in cell.find_all("span"):
        convert_color_classes_to_inline(el)

    # Clean <a> tags (remove styling, keep href)
    for a in cell.find_all("a"):
        href = a.get("href")
        a.attrs = {"href": href} if href else {}

    # Remove disallowed tags but keep their contents
    for tag in list(cell.find_all(True)):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()

    # Strip background-color
    for el in cell.find_all(True):
        if "style" in el.attrs:
            styles = [
                s for s in el["style"].split(";")
                if not s.strip().startswith("background-color")
            ]
            el["style"] = ";".join(s for s in styles if s.strip())

    # Normalize <br>
    html_str = (
        cell.decode_contents()
        .replace("<br>", "<br/>")
        .replace("<br />", "<br/>")
    )

    # Temporarily treat <br/> as newline for codeblock parsing
    tmp = html_str.replace("<br/>", "\n")

    # Triple backtick fenced codeblocks → monospace <div>
    def fence_replacer(m):
        inner = m.group(1)
        inner_soup = BeautifulSoup(inner, "html.parser")

        # Remove background but preserve text color
        for el in inner_soup.find_all(True):
            if "style" in el.attrs:
                styles = [
                    s for s in el["style"].split(";")
                    if not s.strip().startswith("background-color")
                ]
                el["style"] = ";".join(s for s in styles if s.strip())

        return (
            "<div style=\"font-family:Menlo,Consolas,'Courier New',monospace; "
            "white-space:pre\">" +
            inner_soup.decode_contents() +
            "</div>"
        )

    tmp = re.sub(r"```(.*?)```", fence_replacer, tmp, flags=re.DOTALL)

    # Convert remaining newlines back to <br>
    tmp = tmp.replace("\n", "<br/>")

    return tmp

def tags_from_cell(cell):
    raw = cell.get_text(" ", strip=True)
    tokens = [
        t.strip() for t in re.split(r"[,;\n]+", raw)
        if t.strip()
    ]

    clean = []
    seen = set()

    for tok in tokens:
        # Multiword tags → dashed
        tok = re.sub(r"\s+", "-", tok.strip()).strip(",;")

        if tok and tok not in seen:
            clean.append(tok)
            seen.add(tok)

    return " ".join(clean)

def parse_table(soup):
    table = soup.find("table")
    thead = table.find("thead")
    headers = [th.get_text(strip=True).lower() for th in thead.find_all("th")]

    col_map = {}
    for idx, name in enumerate(headers):
        if "notion-id" in name:
            col_map["id"] = idx
        elif "front" == name:
            col_map["front"] = idx
        elif "back" == name:
            col_map["back"] = idx
        elif "tags" in name:
            col_map["tags"] = idx

    return table, col_map

def convert_file(input_path, output_path):
    html = Path(input_path).read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")

    table, col_map = parse_table(soup)
    rows_out = []

    for tr in table.find("tbody").find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue

        notion_id = tds[col_map["id"]].get_text(strip=True)
        front_plain = sanitize_inline_html(tds[col_map["front"]], strip_all=True)
        back_html = sanitize_inline_html(tds[col_map["back"]], strip_all=False)
        tags = tags_from_cell(tds[col_map["tags"]]) if "tags" in col_map else ""

        rows_out.append({
            "Notion-ID": notion_id,
            "Front": front_plain,
            "Back": back_html,
            "Tags": tags
        })

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["Notion-ID", "Front", "Back", "Tags"]
        )
        writer.writeheader()
        writer.writerows(rows_out)
