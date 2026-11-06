# SPDX-License-Identifier: Apache-2.0
#
# TigerTag Firebase Integration Guide
# Copyright (c) 2025-2026 TigerTag Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Build the integration guide's showcase site (GitHub Pages) into `_site/`.

One static page per language, all from `template.html` and `i18n/<lang>.json`:
English at the root, the others under `/<lang>/`. Every page is complete HTML in
its own language — what a search engine, an AI crawler or a reader without
JavaScript sees — with `hreflang` links between them, JSON-LD in its language,
and a sitemap listing them all.

The site presents the repository; the repository stays the reference. Every link
on the page points to a file or a heading of this repository on GitHub.

Usage:
    python site/build.py                 # build into _site/
    python site/build.py --check         # only check the translations
    python site/build.py --out DIR --url https://example.org/path/
"""

import argparse
import hashlib
import html
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SITE_URL = "https://tigertag-project.github.io/TigerTag_Firebase_Integration/"
REPO_URL = "https://github.com/TigerTag-Project/TigerTag_Firebase_Integration"

# The eleven languages of the TigerTag sites, in the same order. `pt` (Brazil)
# and `pt-pt` (Portugal) are separate dictionaries on purpose.
LANGS = ["en", "fr", "de", "es", "it", "zh", "pt", "pt-pt", "pl", "ru", "nl"]
HTML_LANG = {"zh": "zh-Hans", "pt": "pt-BR", "pt-pt": "pt-PT"}
OG_LOCALE = {"en": "en_US", "fr": "fr_FR", "de": "de_DE", "es": "es_ES", "it": "it_IT",
             "zh": "zh_CN", "pt": "pt_BR", "pt-pt": "pt_PT", "pl": "pl_PL", "ru": "ru_RU", "nl": "nl_NL"}

# Crawlers of search and answer engines, welcomed by name in robots.txt: the
# guide is meant to be read, cited and understood by them. Listing them is an
# explicit opt-in, not a ranking trick.
AI_AGENTS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "Claude-User",
             "PerplexityBot", "Perplexity-User", "Google-Extended", "Applebot-Extended", "CCBot",
             "Amazonbot", "Bytespider", "Meta-ExternalAgent", "cohere-ai", "DuckAssistBot", "MistralAI-User"]

ORG_ID = "https://tigersystem.io/#organization"
FAQ_COUNT = 7

PLACEHOLDER = re.compile(r"\{\{([a-z0-9_@]+)\}\}")


def asset_version(name):
    """Short sha256 of a published site file, appended to its URL as ?v=."""
    return hashlib.sha256((HERE / name).read_bytes()).hexdigest()[:10]


def page_date():
    """The last change to the site or to the README, as an ISO date (git), else today."""
    import subprocess
    from datetime import datetime, timezone
    try:
        date = subprocess.run(["git", "log", "-1", "--format=%cI", "--", "site", "README.md", "llms.txt"],
                              cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()[:10]
    except (OSError, subprocess.CalledProcessError):
        date = ""
    return date or datetime.now(timezone.utc).date().isoformat()


def load_dictionaries():
    """Every language, checked against English: same keys, none empty."""
    dicts = {}
    for lang in LANGS:
        path = HERE / "i18n" / f"{lang}.json"
        if not path.exists():
            raise SystemExit(f"error: missing translation {path.relative_to(REPO)}")
        dicts[lang] = json.loads(path.read_text(encoding="utf-8"))
    reference = list(dicts["en"])
    problems = []
    for lang, words in dicts.items():
        missing = [k for k in reference if k not in words]
        extra = [k for k in words if k not in dicts["en"]]
        empty = [k for k, v in words.items() if not isinstance(v, str) or not v.strip()]
        for label, keys in (("missing", missing), ("unknown", extra), ("empty", empty)):
            if keys:
                problems.append(f"{lang}.json: {label} key(s): {', '.join(keys)}")
    template_keys = set(PLACEHOLDER.findall((HERE / "template.html").read_text(encoding="utf-8")))
    unused = [k for k in template_keys if not k.startswith("@") and k not in dicts["en"]]
    if unused:
        problems.append(f"template.html uses unknown key(s): {', '.join(sorted(unused))}")
    if problems:
        raise SystemExit("error: translations do not match en.json\n  " + "\n  ".join(problems))
    return dicts


def page_path(lang):
    return "" if lang == "en" else f"{lang}/"


def jsonld_blocks(lang, words, site_url, url, date):
    in_lang = HTML_LANG.get(lang, lang)
    faq = [{"@type": "Question", "name": words[f"faq{i}_q"],
            "acceptedAnswer": {"@type": "Answer", "text": words[f"faq{i}_a"]}} for i in range(1, FAQ_COUNT + 1)]
    return [
        {"@context": "https://schema.org", "@type": "Organization", "@id": ORG_ID, "name": "TigerTag Corp",
         "url": "https://tigersystem.io", "logo": site_url + "assets/apple-touch-icon.png",
         "sameAs": ["https://github.com/TigerTag-Project",
                    "https://tigertag-project.github.io/TigerTag-RFID-Guide/"]},
        {"@context": "https://schema.org", "@type": "WebSite", "name": "TigerTag Firebase Integration", "url": url,
         "inLanguage": in_lang, "description": words["meta_description"], "publisher": {"@id": ORG_ID}},
        {"@context": "https://schema.org", "@type": "TechArticle", "headline": words["meta_title"],
         "description": words["meta_description"],
         "about": "Connecting third-party clients to a TigerTag account through Firebase Authentication and Firestore",
         "inLanguage": in_lang, "url": url, "image": site_url + "assets/og.jpg", "dateModified": date,
         "license": "https://creativecommons.org/licenses/by/4.0/",
         "isBasedOn": REPO_URL, "author": {"@id": ORG_ID}, "publisher": {"@id": ORG_ID}},
        {"@context": "https://schema.org", "@type": "FAQPage", "inLanguage": in_lang, "mainEntity": faq},
        {"@context": "https://schema.org", "@type": "SoftwareSourceCode",
         "name": "TigerTag Firebase Integration Guide", "codeRepository": REPO_URL,
         "programmingLanguage": ["Python", "C++"],
         "license": "https://www.apache.org/licenses/LICENSE-2.0",
         "description": "Reference documentation and examples for clients (Home Assistant, ESP32, Python, Spoolman bridge) "
                        "that sign in with the user's own TigerTag account and read or write Firestore.",
         "author": {"@id": ORG_ID}},
    ]


def render(template, lang, words, dicts, site_url, date):
    base = "" if lang == "en" else "../"
    url = site_url + page_path(lang)

    alternates = [f'<link rel="alternate" hreflang="{HTML_LANG.get(l, l)}" href="{site_url}{page_path(l)}">' for l in LANGS]
    alternates.append(f'<link rel="alternate" hreflang="x-default" href="{site_url}">')

    menu = []
    for l in LANGS:
        current = ' aria-current="true"' if l == lang else ""
        menu.append(f'          <li><a href="{base}{page_path(l)}" hreflang="{HTML_LANG.get(l, l)}" '
                    f'lang="{HTML_LANG.get(l, l)}" data-lang="{l}"{current}>{html.escape(dicts[l]["lang_name"])}</a></li>')

    # `</` never appears inside a <script> block.
    jsonld_html = "\n".join('<script type="application/ld+json">' + json.dumps(j, ensure_ascii=False).replace("</", "<\\/") + "</script>"
                            for j in jsonld_blocks(lang, words, site_url, url, date))

    special = {
        "@lang": lang,
        "@htmllang": HTML_LANG.get(lang, lang),
        "@oglocale": OG_LOCALE[lang],
        "@oglocalealt": "\n".join(f'<meta property="og:locale:alternate" content="{OG_LOCALE[l]}">' for l in LANGS if l != lang),
        "@url": url,
        "@siteurl": site_url,
        "@base": base,
        "@langpath": page_path(lang),
        "@alternates": "\n".join(alternates),
        "@langmenu": "\n".join(menu),
        "@jsonld": jsonld_html,
        "@repo": REPO_URL,
        # Content hashes: a new site.css / site.js gets a new URL, so no browser
        # keeps running the previous one from its cache.
        "@vcss": asset_version("site.css"),
        "@vjs": asset_version("site.js"),
        "@trademark": f'<a href="https://github.com/TigerTag-Project/TigerTag-RFID-Guide/blob/main/TRADEMARK.md">{html.escape(words["foot_trademark"])}</a>',
    }

    def fill(match):
        key = match.group(1)
        if key in special:
            return special[key]
        return html.escape(words[key], quote=True)

    return PLACEHOLDER.sub(fill, template)


def build(out, site_url):
    dicts = load_dictionaries()
    template = (HERE / "template.html").read_text(encoding="utf-8")
    date = page_date()
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)

    for lang in LANGS:
        target = out / page_path(lang) / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(template, lang, dicts[lang], dicts, site_url, date), encoding="utf-8")

    for name in ("site.css", "site.js"):
        shutil.copy2(HERE / name, out / name)
    # Logos (white on dark, contoured black on light), favicon and touch icon.
    for extra in sorted((HERE / "assets").glob("*")):
        shutil.copy2(extra, out / "assets" / extra.name)
    shutil.copy2(HERE / "og.jpg", out / "assets" / "og.jpg")
    # The machine-readable description of the guide, at the site root too.
    shutil.copy2(REPO / "llms.txt", out / "llms.txt")

    urls = "\n".join(
        "  <url><loc>{}</loc><lastmod>{}</lastmod>{}</url>".format(
            site_url + page_path(lang), date,
            "".join(f'<xhtml:link rel="alternate" hreflang="{HTML_LANG.get(l, l)}" href="{site_url}{page_path(l)}"/>' for l in LANGS))
        for lang in LANGS)
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
        f"{urls}\n</urlset>\n", encoding="utf-8")
    robots = ["User-agent: *", "Allow: /", ""]
    for agent in AI_AGENTS:
        robots += [f"User-agent: {agent}", "Allow: /", ""]
    robots += [f"Sitemap: {site_url}sitemap.xml"]
    (out / "robots.txt").write_text("\n".join(robots) + "\n", encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"built {len(LANGS)} languages into {out}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(REPO / "_site"))
    parser.add_argument("--url", default=SITE_URL)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--only", help="comma-separated languages, for a quick local preview")
    args = parser.parse_args()
    if args.only:
        LANGS[:] = [l for l in LANGS if l in args.only.split(",")]
    if args.check:
        load_dictionaries()
        print(f"translations OK: {len(LANGS)} languages")
        return
    url = args.url if args.url.endswith("/") else args.url + "/"
    build(Path(args.out), url)


if __name__ == "__main__":
    sys.exit(main())
