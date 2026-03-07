from app.services.json_utils import extract_json_object


def test_extract_json_object_handles_code_fences_and_trailing_text() -> None:
    raw = """```json
    {
      "template_id": "sample_template",
      "program": {
        "program_id": "sample_v1"
      }
    }
    ```
    Additional commentary after the JSON object.
    """

    parsed = extract_json_object(raw)

    assert parsed["template_id"] == "sample_template"
    assert parsed["program"]["program_id"] == "sample_v1"


def test_extract_json_object_repairs_js_style_object() -> None:
    raw = """
    {
      template_id: 'sample_template',
      mapping_explanation: 'Generated from prompt',
      verified: true,
      program: {
        program_id: 'sample_v1',
      },
    }
    """

    parsed = extract_json_object(raw)

    assert parsed["template_id"] == "sample_template"
    assert parsed["verified"] is True
    assert parsed["program"]["program_id"] == "sample_v1"


def test_extract_json_object_sanitizes_non_json_literals() -> None:
    raw = """
    {
      template_id: 'sample_template',
      placeholders: ...,
      tags: {'alpha', 'beta'}
    }
    """

    parsed = extract_json_object(raw)

    assert parsed["template_id"] == "sample_template"
    assert parsed["placeholders"] is None
    assert parsed["tags"] == ["alpha", "beta"]
