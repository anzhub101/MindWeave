from __future__ import annotations

import ast
import json
import re


def extract_json_object(raw: str) -> dict:
    candidate = _strip_code_fences(raw).strip()

    for variant in _candidate_variants(candidate):
        parsed = _parse_variant(variant)
        if isinstance(parsed, dict):
            return parsed

    raise ValueError("Response did not contain a valid JSON object.")


def _strip_code_fences(raw: str) -> str:
    candidate = raw.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json|JSON)?\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
    return candidate


def _candidate_variants(candidate: str) -> list[str]:
    variants: list[str] = []
    seen: set[str] = set()

    def add(value: str | None) -> None:
        if value is None:
            return
        normalized = value.strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        variants.append(normalized)

    segment = _extract_braced_segment(candidate)
    for value in (candidate, segment):
        add(value)
        if value is None:
            continue
        without_comments = _remove_js_comments(value)
        add(without_comments)
        add(_remove_trailing_commas(without_comments))
        add(_quote_bare_keys(_remove_trailing_commas(without_comments)))

    return variants


def _parse_variant(candidate: str) -> dict | None:
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return _sanitize_json_value(parsed)
    except json.JSONDecodeError:
        pass

    try:
        decoder = json.JSONDecoder()
        parsed, _ = decoder.raw_decode(candidate)
        if isinstance(parsed, dict):
            return _sanitize_json_value(parsed)
    except json.JSONDecodeError:
        pass

    pythonic_candidate = _pythonize_json_literals(candidate)
    try:
        parsed = ast.literal_eval(pythonic_candidate)
        if isinstance(parsed, dict):
            return _sanitize_json_value(parsed)
    except (SyntaxError, ValueError):
        return None

    return None


def _extract_braced_segment(candidate: str) -> str | None:
    start = candidate.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    string_quote = ""
    escaped = False

    for index, char in enumerate(candidate[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == string_quote:
                in_string = False
            continue

        if char in {'"', "'"}:
            in_string = True
            string_quote = char
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return candidate[start : index + 1]

    return candidate[start:]


def _remove_js_comments(candidate: str) -> str:
    candidate = re.sub(r"/\*.*?\*/", "", candidate, flags=re.DOTALL)
    return re.sub(r"(^|[^:])//.*?$", r"\1", candidate, flags=re.MULTILINE)


def _remove_trailing_commas(candidate: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", candidate)


def _quote_bare_keys(candidate: str) -> str:
    return re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)', r'\1"\2"\3', candidate)


def _pythonize_json_literals(candidate: str) -> str:
    replacements = {"true": "True", "false": "False", "null": "None"}
    result: list[str] = []
    index = 0
    in_string = False
    string_quote = ""
    escaped = False

    while index < len(candidate):
        char = candidate[index]
        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == string_quote:
                in_string = False
            index += 1
            continue

        if char in {'"', "'"}:
            in_string = True
            string_quote = char
            result.append(char)
            index += 1
            continue

        replaced = False
        for raw_value, python_value in replacements.items():
            if candidate.startswith(raw_value, index):
                left_boundary = index == 0 or not (candidate[index - 1].isalnum() or candidate[index - 1] == "_")
                right_index = index + len(raw_value)
                right_boundary = right_index == len(candidate) or not (
                    candidate[right_index].isalnum() or candidate[right_index] == "_"
                )
                if left_boundary and right_boundary:
                    result.append(python_value)
                    index = right_index
                    replaced = True
                    break
        if replaced:
            continue

        result.append(char)
        index += 1

    return "".join(result)


def _sanitize_json_value(value):
    if value is Ellipsis:
        return None
    if isinstance(value, dict):
        return {str(key): _sanitize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, set):
        return [_sanitize_json_value(item) for item in sorted(value, key=str)]
    return value
