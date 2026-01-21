from rest_framework import serializers


class GenericStreamingRequestSerializer(serializers.Serializer):
    streaming = serializers.ChoiceField(choices=["influx", "timescale"])  # "influx", "timedb",... etc.
    data = serializers.DictField()
