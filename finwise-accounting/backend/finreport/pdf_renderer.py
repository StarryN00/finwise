from __future__ import annotations

import html
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright


def render_html(template_dir: str, context: dict) -> str:
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)
    env.filters["wan"] = lambda x: f"{float(x or 0) / 10000:.2f}"
    env.filters["pct"] = lambda x: f"{float(x or 0) * 100:.2f}%"
    env.filters["md"] = md_to_html
    return env.get_template("report.html").render(**context)


def html_to_pdf(html_str: str, pdf_path: str, base_url: str):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 794, "height": 1123})
        page.set_content(html_str, wait_until="networkidle")
        page.add_style_tag(path=str(Path(base_url) / "static" / "styles.css"))
        page.pdf(
            path=pdf_path,
            format="A4",
            print_background=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            prefer_css_page_size=True,
        )
        browser.close()


def md_to_html(text: str) -> str:
    escaped = html.escape(str(text or ""))
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    lines = [line.strip() for line in escaped.splitlines() if line.strip()]
    if not lines:
        return ""
    if all(re.match(r"^\d+\.\s+", line) for line in lines):
        items = "".join(f"<li>{re.sub(r'^\\d+\\.\\s+', '', line)}</li>" for line in lines)
        return f"<ol>{items}</ol>"
    if any(line.startswith("- ") for line in lines):
        blocks = []
        paragraph_lines = [line for line in lines if not line.startswith("- ")]
        bullet_lines = [line[2:] for line in lines if line.startswith("- ")]
        if paragraph_lines:
            blocks.append("".join(f"<p>{line}</p>" for line in paragraph_lines))
        if bullet_lines:
            blocks.append("<ul>" + "".join(f"<li>{line}</li>" for line in bullet_lines) + "</ul>")
        return "".join(blocks)
    return "".join(f"<p>{line}</p>" for line in lines)
