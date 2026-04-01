from __future__ import annotations

import re
from typing import Mapping


PLACEHOLDER_PATTERN = re.compile(r"{{\s*([^{}]+?)\s*}}")


def render_prompt(template: str, values: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return values.get(key, "")

    return PLACEHOLDER_PATTERN.sub(replace, template)
