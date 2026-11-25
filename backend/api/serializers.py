"""DRF serializers: request validation and the documented response schema of ``/api/v2/chat/``."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from rest_framework import serializers


class StrictCharField(serializers.CharField):
    """A CharField that rejects non-string JSON values instead of coercing numbers or booleans to text."""

    def to_internal_value(self, data: Any) -> str:
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class ChatRequestSerializer(serializers.Serializer[dict[str, Any]]):
    """``{"question": str}``; the length cap comes from ``CHAT_MAX_QUESTION_CHARS``."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        limit = settings.CHAT_MAX_QUESTION_CHARS
        self.fields["question"] = StrictCharField(
            max_length=limit,
            trim_whitespace=True,
            allow_blank=False,
            error_messages={
                "required": "Indique la pregunta en el campo 'question'.",
                "blank": "La pregunta no puede estar vacía.",
                "max_length": f"La pregunta no puede exceder {limit} caracteres.",
                "invalid": "La pregunta debe ser texto.",
            },
        )


class SourceSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.CharField()
    kind = serializers.ChoiceField(choices=["legislacion", "dof"])
    citation = serializers.CharField()
    title = serializers.CharField()
    excerpt = serializers.CharField()
    excerpt_is_complete = serializers.BooleanField()
    url = serializers.CharField(allow_null=True)
    date = serializers.CharField(allow_null=True)
    hierarchy = serializers.CharField(allow_null=True)
    is_repealed = serializers.BooleanField()


class ChatResponseSerializer(serializers.Serializer[dict[str, Any]]):
    answer = serializers.CharField()
    refused = serializers.BooleanField()
    route = serializers.ChoiceField(choices=["rag", "mcp", "hybrid"], allow_null=True)
    retries = serializers.IntegerField()
    sources = SourceSerializer(many=True)
