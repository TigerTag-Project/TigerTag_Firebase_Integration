# The showcase site

The public page of this integration guide, published on GitHub Pages:
<https://tigertag-project.github.io/TigerTag_Firebase_Integration/>

It presents the repository — how a client connects, the integrations documented in
`docs/clients/`, the security model, the stability contract and the reference documents —
and links back to them. The repository stays the reference: every fact on the page comes
from the README, `docs/`, `rules/` or `CHANGELOG.md`, and every link points to a file or a
heading of this repository on GitHub.

It is static HTML, one page per language, built by [`build.py`](build.py) and published by
[`pages.yml`](../.github/workflows/pages.yml) on every push to `main` that touches `site/`
or `llms.txt`. On a pull request the same workflow builds and checks the site without
deploying it.

## Files

| File | Contents |
|---|---|
| [`template.html`](template.html) | The page. Every `{{key}}` is replaced by the text of that key in the page's language; `{{@…}}` keys are filled by `build.py` (language menu, `hreflang` links, JSON-LD, repository URL). |
| [`i18n/en.json`](i18n/en.json) | The English text, which is the reference: every other language has exactly its keys. |
| `i18n/<lang>.json` | One file per language: `fr`, `de`, `es`, `it`, `zh` (Simplified Chinese), `pt` (Brazil), `pt-pt` (Portugal), `pl`, `ru`, `nl`. |
| [`site.css`](site.css), [`site.js`](site.js) | The look (dark by default, light on request) and the theme / language buttons, the same as the TigerTag protocol site. Loaded with `?v=` and a hash of the file's content. |
| [`seo_check.py`](seo_check.py) | Checks the built pages for search and answer engines (rule: [`.agents/rules/seo-geo.md`](../.agents/rules/seo-geo.md)). |
| [`assets/`](assets/) | TigerTag logos (white on the dark theme, contoured black on the light one), favicon and touch icon, copied unmodified from the TigerTag brand kit. |

The build also publishes [`llms.txt`](../llms.txt) at the site root, a `sitemap.xml` with
`<lastmod>` and a `robots.txt`.

## Editing

- **Change a text**: edit `i18n/en.json`, then the same key in every other language.
- **Add a text**: add the key to every `i18n/*.json` file and use `{{key}}` in `template.html`.
  The build refuses a language that misses a key, has an unknown one or an empty value.
- **Check and preview**:

  ```bash
  python3 site/build.py --check
  python3 site/build.py && python3 -m http.server 8000 --directory _site
  python3 site/build.py --out _site && python3 site/seo_check.py _site
  ```

The English page is the root (`/`), every other language has its own folder (`/fr/`,
`/zh/`…). A language chosen in the menu is remembered, and the English root forwards to it
on the next visit.
