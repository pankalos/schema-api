from rest_framework import serializers


class GenericStreamingRequestSerializer(serializers.Serializer):
    streaming = serializers.ChoiceField(choices=["influx", "timescale", "leaf-influx"])  # "influx", "timescale",... etc.
    data = serializers.DictField()
