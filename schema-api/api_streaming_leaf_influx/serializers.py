from rest_framework import serializers
from .models import LeafInfluxDB


class LeafInfluxSourceSerializer(serializers.Serializer):
    api_url = serializers.URLField()
    token = serializers.CharField()

    organisation = serializers.CharField()
    department = serializers.CharField()
    entity = serializers.CharField(allow_blank=False)

    metrics = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
    )

    everyTs = serializers.IntegerField(min_value=1)


class LeafInfluxModelerSerializer(serializers.Serializer):
    endpoint = serializers.CharField()
    image = serializers.CharField()
    port = serializers.IntegerField()
    args = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
    )


class LeafInfluxMqttSerializer(serializers.Serializer):
    host = serializers.CharField()
    port = serializers.IntegerField(required=False, default=443)
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)
    topic = serializers.CharField()
    basepath = serializers.CharField(required=False, default="mqtt")

    # Required. No default.
    measurement = serializers.CharField(allow_blank=False)

    output_tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
    )


class LeafInfluxCreateSerializer(serializers.Serializer):
    namespace = serializers.CharField(required=False)
    source = LeafInfluxSourceSerializer()
    modeler = LeafInfluxModelerSerializer()

    # Required now.
    mqtt = LeafInfluxMqttSerializer()



class LeafInfluxSerializerHelpers:
    def _format_datetime(self, value):
        return serializers.DateTimeField().to_representation(value)

    def get_total_runtime(self, obj):
        delta = obj.computed_runtime
        seconds = round(delta.total_seconds())
        hours, rem = divmod(seconds, 3600)
        mins, secs = divmod(rem, 60)
        return f"{hours}:{mins:02}:{secs:02}"

    def get_current_status(self, obj):
        data = {
            "status": obj.status,
            "updated_at": self._format_datetime(obj.status_updated_at),
        }

        if obj.status == "Error" and obj.error_message:
            data["error_message"] = obj.error_message

        return data


class LeafInfluxSummarySerializer(LeafInfluxSerializerHelpers, serializers.ModelSerializer):
    submitted_at = serializers.DateTimeField(source="created_at", read_only=True)
    total_runtime = serializers.SerializerMethodField()
    current_status = serializers.SerializerMethodField()

    class Meta:
        model = LeafInfluxDB
        fields = [
            "id",
            "submitted_at",
            "current_status",
            "total_runtime",
        ]


class LeafInfluxSerializer(LeafInfluxSerializerHelpers, serializers.ModelSerializer):
    submitted_at = serializers.DateTimeField(source="created_at", read_only=True)
    total_runtime = serializers.SerializerMethodField()
    current_status = serializers.SerializerMethodField()

    class Meta:
        model = LeafInfluxDB
        fields = [
            "id",
            "submitted_at",
            "current_status",
            "total_runtime",

            "namespace",
            "pod_modeler_name",
            "svc_modeler_name",
            "pod_listener_name",
            "source",
            "modeler",
            "mqtt",
        ]
