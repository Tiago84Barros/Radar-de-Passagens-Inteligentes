import json

from providers.openai_search_provider import _extract_grounded_output


SOURCE_URL = "https://www.decolar.com/shop/flights/results/oneway/gru/lis/2026-09-10/1/0/0"


def test_extracts_openai_text_and_native_url_citations():
    text = json.dumps(
        [
            {
                "companhia": "TAP",
                "origem": "GRU",
                "destino": "LIS",
                "data_ida": "2026-09-10",
                "preco_brl": 1800.0,
                "source_url": SOURCE_URL,
            }
        ]
    )
    response = {
        "output": [
            {"type": "web_search_call", "status": "completed"},
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": SOURCE_URL,
                                "title": "Decolar",
                                "start_index": 0,
                                "end_index": len(text),
                            }
                        ],
                    }
                ],
            },
        ]
    }

    grounded = _extract_grounded_output(response)

    assert grounded["text"] == text
    assert grounded["citations"] == [
        {
            "url": SOURCE_URL,
            "title": "Decolar",
            "start_index": 0,
            "end_index": len(text),
        }
    ]


def test_supports_nested_openai_url_citation_shape():
    response = {
        "output_text": "[]",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "[]",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url_citation": {
                                    "url": SOURCE_URL,
                                    "title": "Decolar",
                                    "start_index": 0,
                                    "end_index": 2,
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    }

    grounded = _extract_grounded_output(response)

    assert grounded["citations"][0]["url"] == SOURCE_URL


def test_ignores_uncited_sources_and_non_url_annotations():
    response = {
        "output_text": "[]",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "[]",
                        "annotations": [
                            {"type": "file_citation", "file_id": "file_123"},
                            {"type": "url_citation", "url": "", "title": "Missing URL"},
                        ],
                    }
                ],
            }
        ],
    }

    grounded = _extract_grounded_output(response)

    assert grounded["citations"] == []
