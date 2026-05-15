from rest_framework import serializers
from .models import LeafInfluxDB


class LeafInfluxSourceSerializer(serializers.Serializer):
    api_url = serializers.URLField()
    token = serializers.CharField()

    organisation = serializers.CharField()
    department = serializers.CharField()
    entity = serializers.CharField(required=False, allow_blank=False)

    metrics = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
    )

    everyTs = serializers.IntegerField(min_value=1)


class LeafInfluxModelerSerializer(serializers.Serializer):
    endpoint = serializers.CharField()
    image = serializers.CharField()
    port = serializers.IntegerField()
    args = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    include_time_to_mod = serializers.BooleanField(required=False, default=False)


class LeafInfluxCreateSerializer(serializers.Serializer):
    namespace = serializers.CharField(required=False)
    source = LeafInfluxSourceSerializer()
    modeler = LeafInfluxModelerSerializer()


class LeafInfluxSerializer(serializers.ModelSerializer):
    total_runtime = serializers.SerializerMethodField()

    class Meta:
        model = LeafInfluxDB
        fields = '__all__'

    def get_total_runtime(self, obj):
        delta = obj.computed_runtime
        seconds = round(delta.total_seconds())
        hours, rem = divmod(seconds, 3600)
        mins, secs = divmod(rem, 60)
        return f"{hours}:{mins:02}:{secs:02}"


class LeafInfluxSummarySerializer(serializers.ModelSerializer):
    total_runtime = serializers.SerializerMethodField()

    class Meta:
        model = LeafInfluxDB
        fields = ['id', 'created_at', 'status', 'total_runtime']

    def get_total_runtime(self, obj):
        delta = obj.computed_runtime
        seconds = round(delta.total_seconds())
        hours, rem = divmod(seconds, 3600)
        mins, secs = divmod(rem, 60)
        return f"{hours}:{mins:02}:{secs:02}"
