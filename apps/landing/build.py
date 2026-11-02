"""Build the static Agentaria landing page.

The page is one template (template.html) filled from one copy file per
language (copy/<lang>.json). Spanish is served at the root and English under
/en/. The output in public/ is committed, so any static host can serve the
folder as is; run this script again after editing the template or the copy.

Links the site points at come from the environment, so the same build can
target another domain:

    LANDING_APP_URL      where "Start free trial" and "Sign in" go
    LANDING_DEMO_URL     where "Book a demo" and "Talk to sales" go
    LANDING_PRIVACY_URL  privacy policy
    LANDING_TERMS_URL    terms of service

Usage: python build.py
"""

from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
LANGUAGES = {"es": "", "en": "en/"}  # language -> path under public/
DEFAULT_LINKS = {
    "app_url": "https://app.agentaria.com/login",
    "demo_url": "mailto:hello@agentaria.com?subject=Agentaria%20demo",
    "privacy_url": "#",
    "terms_url": "#",
}


def links() -> dict[str, str]:
    return {
        "app_url": os.environ.get("LANDING_APP_URL", DEFAULT_LINKS["app_url"]),
        "demo_url": os.environ.get("LANDING_DEMO_URL", DEFAULT_LINKS["demo_url"]),
        "privacy_url": os.environ.get("LANDING_PRIVACY_URL", DEFAULT_LINKS["privacy_url"]),
        "terms_url": os.environ.get("LANDING_TERMS_URL", DEFAULT_LINKS["terms_url"]),
    }


def render(template: str, copy: dict[str, str], lang: str) -> str:
    root = "./" if LANGUAGES[lang] == "" else "../"
    other = "en" if lang == "es" else "es"
    values = {key: html.escape(value) for key, value in copy.items()}
    values.update({key: html.escape(value) for key, value in links().items()})
    values["root"] = root
    values["other_lang_href"] = root + LANGUAGES[other]
    # Strings the inline script writes need to be JS literals, not HTML.
    values["billed_monthly_js"] = json.dumps(copy["billed_monthly"], ensure_ascii=False)
    values["billed_yearly_js"] = json.dumps(copy["billed_yearly"], ensure_ascii=False)

    def fill(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(f"copy/{lang}.json has no value for {{{{{key}}}}}")
        return values[key]

    return re.sub(r"\{\{(\w+)\}\}", fill, template)


def main() -> None:
    template = (HERE / "template.html").read_text(encoding="utf-8")
    for lang, sub in LANGUAGES.items():
        copy = json.loads((HERE / "copy" / f"{lang}.json").read_text(encoding="utf-8"))
        out = HERE / "public" / sub / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render(template, copy, lang), encoding="utf-8")
        print(f"wrote {out.relative_to(HERE)}")


if __name__ == "__main__":
    main()
