from rest_framework import serializers
from .models import InfluxDB

# Shared base
class InfluxGenSerializer(serializers.Serializer):
    url = serializers.CharField()
    token = serializers.CharField()
    bucket = serializers.CharField()
    org = serializers.CharField()
    measurement = serializers.CharField()
    tags = serializers.ListField(child=serializers.CharField())
    cols = serializers.ListField(child=serializers.CharField())


class InfluxInSerializer(InfluxGenSerializer):
    everyTs = serializers.IntegerField()


class InfluxOutSerializer(InfluxGenSerializer):
    col_time = serializers.CharField()


class ModelerSerializer(serializers.Serializer):
    endpoint = serializers.CharField()
    image = serializers.CharField()
    port = serializers.IntegerField()
    args = serializers.ListField(child=serializers.CharField())


class InfluxDBCreateSerializer(serializers.Serializer):
    namespace = serializers.CharField()
    influx_in = InfluxInSerializer()
    influx_out = InfluxOutSerializer()
    modeler = ModelerSerializer()


class InfluxDBSerializer(serializers.ModelSerializer):
    total_runtime = serializers.SerializerMethodField()

    class Meta:
        model = InfluxDB
        fields = '__all__'

    def get_total_runtime(self, obj):
        delta = obj.computed_runtime
        seconds = round(delta.total_seconds())
        hours, rem = divmod(seconds, 3600)
        mins, secs = divmod(rem, 60)
        return f"{hours}:{mins:02}:{secs:02}"


class InfluxDBSummarySerializer(serializers.ModelSerializer):
    total_runtime = serializers.SerializerMethodField()

    class Meta:
        model = InfluxDB
        fields = ['id', 'created_at', 'status', 'total_runtime']

    def get_total_runtime(self, obj):
        delta = obj.computed_runtime
        seconds = round(delta.total_seconds())
        hours, rem = divmod(seconds, 3600)
        mins, secs = divmod(rem, 60)
        return f"{hours}:{mins:02}:{secs:02}"
