"""A notes API. The pure rule is checked by fox. The route only does HTTP.

    uv run --group examples python -m fox examples/notes.py
    uv run --group examples python examples/notes.py
"""

from __future__ import annotations

from flask import Flask, jsonify, request

from fox import PreconditionError, effect, fox

http = effect("http")
fox.track(jsonify, http)

app = Flask(__name__)


@fox(
    requires=lambda text: text.strip() != "",
    ensures=lambda text, result: result["text"] == text.strip(),
)
def make_note(text: str) -> dict[str, str]:
    return {"text": text.strip()}


@fox(effects=http)
def read_text() -> str:
    body = request.get_json(silent=True) or {}
    text = body.get("text", "")
    if not isinstance(text, str):
        return ""
    return text


@app.post("/notes")
@fox(effects=http)
def post_note():
    try:
        note = make_note(read_text())
    except PreconditionError:
        return jsonify(error="text is required"), 400
    return jsonify(note)


def main() -> None:
    client = app.test_client()
    kept = client.post("/notes", json={"text": "  hello "})
    blank = client.post("/notes", json={"text": "   "})
    print(kept.status_code, kept.get_json())
    print(blank.status_code, blank.get_json())


if __name__ == "__main__":
    main()
