from rest_framework import serializers


class ChatRequestSerializer(serializers.Serializer):

    message = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        max_length=2000
    )

    website_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=True,
        allow_empty=False,
        max_length=10
    )
    conversation_id = serializers.IntegerField(
    required=False,
    allow_null=True,
    min_value=1
)

    def validate_website_ids(self, value):
        # Remove duplicate website IDs while preserving order.
        return list(dict.fromkeys(value))