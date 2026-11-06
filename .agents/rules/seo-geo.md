# Search and answer engines (SEO / GEO)

**Rule.** Everything this repository publishes — the README, `llms.txt` and the showcase
site built from `site/` — is written to be found, understood and quoted correctly by search
engines and AI answer engines, **with verifiable facts only**. The site is checked on every
PR and before every deploy by `site/seo_check.py`; a failing check is fixed, never bypassed.

**How.**

1. **Facts, not claims.** Every statement on the site can be checked in this repository (a
   doc page, the rules, the changelog). Numbers carry their source or date. No ranking or
   "the best" claim. No text or instructions aimed only at crawlers.
2. **Answer first.** A section opens with a sentence that can be quoted alone. Questions
   people ask live in a visible FAQ, mirrored by the `FAQPage` JSON-LD.
3. **One complete page per language** (`LANGS` in `site/build.py`): self canonical,
   `hreflang` to every language plus `x-default`, `og:locale` with its alternates.
4. **Titles ≤ 60 characters, descriptions 50–160**, unique per language. `seo_check.py`
   warns past 60 / 160 and fails past 70 / 200 or on a duplicate across languages.
5. **Structured data mirrors the page**: `Organization`, `WebSite`, `TechArticle` (with
   `dateModified`), `FAQPage`, `SoftwareSourceCode` (this repository). One `<h1>` per page.
6. **Images and diagrams** carry a description in the page's language (`alt`, or
   `aria-label` on the hero diagram).
7. **Machine-readable copies stay in step.** A fact shown on the site is in the README or
   `docs/`, and in `llms.txt`, in the same PR. `llms.txt` is published at the site root.
8. **Same names everywhere**: TigerTag, Tiger Studio Manager, TigerScale, Home Assistant,
   Spoolman — spelled as in the README.
9. **No emoji** on the site: inline SVG icons or words.
10. **Checks** before a PR: `python site/build.py --check`, then
    `python site/build.py --out _site && python site/seo_check.py _site`.
