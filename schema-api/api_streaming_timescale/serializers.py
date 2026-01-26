from rest_framework import serializers
from .models import TimescaleDB


class PsqlInSerializer(serializers.Serializer):
    # host = serializers.CharField()
    # port = serializers.IntegerField()
    # dbname = serializers.CharField()
    # password = serializers.CharField()    # name of K8s Secret that has 'password'
    # user = serializers.CharField()
    
    # No host/user/password here anymore
    table_in = serializers.CharField()
    everyTs = serializers.IntegerField(min_value=1)
    cols_in = serializers.ListField(child=serializers.CharField())
    time_col_in = serializers.CharField()

class PsqlOutSerializer(serializers.Serializer):
    table_out = serializers.CharField()
    time_col_out = serializers.CharField()
    cols_types_out = serializers.ListField(child=serializers.CharField())  # ["xhat:float8","yhat:float8"]

    make_hypertable = serializers.BooleanField(required=False, default=True)
    chunk_interval = serializers.CharField(required=False, default="1 hour")
    migrate_existing = serializers.BooleanField(required=False, default=False)

class ModelerSerializer(serializers.Serializer):
    image = serializers.CharField()
    port = serializers.IntegerField()
    endpoint = serializers.CharField()
    include_time_to_mod = serializers.BooleanField(required=False, default=False)
    rename_inp_time_col_to_mod_as = serializers.CharField(required=False)
    args = serializers.ListField(child=serializers.CharField(), required=False, default=list)

class TimescaleCreateSerializer(serializers.Serializer):
    # namespace = serializers.CharField()

    # REQUIRED: user selects a DB profile, not credentials
    db_profile = serializers.CharField()

    psql_in   = PsqlInSerializer()
    psql_out  = PsqlOutSerializer()
    modeler   = ModelerSerializer()


class TimescaleStreamSerializer(serializers.ModelSerializer):
    total_runtime = serializers.SerializerMethodField()

    class Meta:
        model = TimescaleDB
        fields = '__all__'

    def get_total_runtime(self, obj):
        delta = obj.computed_runtime
        seconds = round(delta.total_seconds())
        hours, rem = divmod(seconds, 3600)
        mins, secs = divmod(rem, 60)
        return f"{hours}:{mins:02}:{secs:02}"


class TimescaleStreamSummarySerializer(serializers.ModelSerializer):
    total_runtime = serializers.SerializerMethodField()

    class Meta:
        model = TimescaleDB
        fields = ['id', 'created_at', 'db_profile', 'status', 'total_runtime']

    def get_total_runtime(self, obj):
        delta = obj.computed_runtime
        seconds = round(delta.total_seconds())
        hours, rem = divmod(seconds, 3600)
        mins, secs = divmod(rem, 60)
        return f"{hours}:{mins:02}:{secs:02}"

