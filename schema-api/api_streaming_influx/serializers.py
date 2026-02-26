from rest_framework import serializers
from .models import InfluxDB


class InfluxInSerializer(serializers.Serializer):
    """
    Non-secret input configuration.
    Credentials are NOT accepted here; they must come from db_profile -> k8s Secret.
    """
    bucket = serializers.CharField()
    measurement = serializers.CharField()
    everyTs = serializers.IntegerField(min_value=1)

    tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list
    )
    cols = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list
    )


class InfluxOutSerializer(serializers.Serializer):
    """
    Non-secret output configuration.
    """
    bucket = serializers.CharField()
    measurement = serializers.CharField()

    tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list
    )
    cols = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list
    )

    # Optional: name of the modeler-returned time vector key (epoch ints)
    # If set, it is strict: it must also be included in cols (your requested contract).
    time_col_out = serializers.CharField(required=False)

    # Optional: listener write_precision (defaults to 's' if omitted)
    write_precision = serializers.ChoiceField(
        choices=["s", "ms", "us", "ns"],
        required=False
    )

    def validate(self, attrs):
        tco = attrs.get("time_col_out")
        cols = attrs.get("cols") or []

        # Contract: if time_col_out is set, it MUST also appear in cols
        if tco:
            if not cols:
                raise serializers.ValidationError({
                    "cols": f"When time_col_out is set to '{tco}', cols must be provided and include '{tco}'."
                })
            if tco not in cols:
                raise serializers.ValidationError({
                    "cols": f"When time_col_out is set to '{tco}', it must also be included in cols."
                })

        return attrs


class ModelerSerializer(serializers.Serializer):
    """
    Modeler configuration for the modeler pod.
    """
    endpoint = serializers.CharField()
    image = serializers.CharField()
    port = serializers.IntegerField()
    args = serializers.ListField(child=serializers.CharField(), required=False, default=list)

    # Maps to listener flag --include_time_to_mod
    include_time_to_mod = serializers.BooleanField(required=False, default=False)


class InfluxDBCreateSerializer(serializers.Serializer):
    """
    The user selects db_profile; schema-api resolves it to a k8s Secret and injects INFLUX_* env vars.
    """
    namespace = serializers.CharField(required=False)
    db_profile = serializers.CharField()

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
        fields = ['id', 'created_at', 'db_profile', 'status', 'total_runtime']

    def get_total_runtime(self, obj):
        delta = obj.computed_runtime
        seconds = round(delta.total_seconds())
        hours, rem = divmod(seconds, 3600)
        mins, secs = divmod(rem, 60)
        return f"{hours}:{mins:02}:{secs:02}"
