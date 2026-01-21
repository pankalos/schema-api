from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiParameter
from rest_framework.views import APIView
from .serializers import GenericStreamingRequestSerializer

from django.conf import settings
from api_auth.auth import ApiTokenAuthentication
from api_auth.permissions import IsUser, IsActive, IsContextMember
from rest_framework.permissions import IsAuthenticated

from api_streaming_influx.handler import (
    handle_influx_create,
    handle_influx_list,
    handle_influx_detail,
    handle_influx_terminate,
)

from api_streaming_timescale.handler import (
    handle_timescale_create,
    handle_timescale_list,
    handle_timescale_detail,
    handle_timescale_terminate,
)


STREAMING_HANDLERS = {
    "influx": {
        "create": handle_influx_create,
        "list": handle_influx_list,
        "detail": handle_influx_detail,
        "terminate": handle_influx_terminate,
    },

    "timescale": {
        "create": handle_timescale_create,
        "list": handle_timescale_list,
        "detail": handle_timescale_detail,
        "terminate": handle_timescale_terminate,
    }
}


class StreamingDispatcherView(APIView):
    # auth/permissions same...
    authentication_classes = [ApiTokenAuthentication] if settings.USE_AUTH else []
    permission_classes = [IsAuthenticated, IsUser, IsActive, IsContextMember] if settings.USE_AUTH else []


    @extend_schema(
        summary="Create a new streaming task",
        request=GenericStreamingRequestSerializer,
        tags=["Streaming"],
        responses={201: OpenApiExample("Streaming task created", value={"task_id": "abc123", "status": "created"})}
    )
    def post(self, request):
        serializer = GenericStreamingRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        backend = serializer.validated_data["streaming"]
        payload = serializer.validated_data["data"]

        handler = STREAMING_HANDLERS.get(backend, {}).get("create")
        if not handler:
            return Response({"error": "Unsupported backend"}, status=400)

        return handler(payload, request.user)


    @extend_schema(
        summary="List all streaming tasks for current user",
        parameters=[
            OpenApiParameter(name="streaming", required=False, type=str, description="Backend to use (e.g., influx, timescale)"),
        ],
        tags=["Streaming"],
        responses={200: GenericStreamingRequestSerializer}
    )
    def get(self, request):
        backend = request.query_params.get("streaming")
        handler = STREAMING_HANDLERS.get(backend, {}).get("list")
        if not handler:
            return Response({"error": "Unsupported backend"}, status=400)
        return handler(request.user)


class StreamingDispatcherDetailView(APIView):
    # auth/permissions same...
    authentication_classes = [ApiTokenAuthentication] if settings.USE_AUTH else []
    permission_classes = [IsAuthenticated, IsUser, IsActive, IsContextMember] if settings.USE_AUTH else []

    @extend_schema(
        summary="Get details of a specific streaming task",
        parameters=[
            OpenApiParameter(name="streaming", required=False, type=str, description="Backend to use"),
        ],
        tags=["Streaming"],
        # responses={200: InfluxDBSerializer}  # You can make this dynamic if needed
    )
    def get(self, request, task_id):
        backend = request.query_params.get("streaming")
        handler = STREAMING_HANDLERS.get(backend, {}).get("detail")
        if not handler:
            return Response({"error": "Unsupported backend"}, status=400)
        return handler(task_id, request.user)


class StreamingDispatcherTerminateView(APIView):
    # auth/permissions same...
    authentication_classes = [ApiTokenAuthentication] if settings.USE_AUTH else []
    permission_classes = [IsAuthenticated, IsUser, IsActive, IsContextMember] if settings.USE_AUTH else []

    @extend_schema(
        summary="Terminate a streaming task (delete pods/services)",
        parameters=[
            OpenApiParameter(name="streaming", required=False, type=str, description="Backend to use"),
        ],
        tags=["Streaming"],
        responses={200: OpenApiExample("Task terminated", value={"status": "Terminated"})}
    )
    def post(self, request, task_id):
        backend = request.query_params.get("streaming")
        handler = STREAMING_HANDLERS.get(backend, {}).get("terminate")
        if not handler:
            return Response({"error": "Unsupported backend"}, status=400)
        return handler(task_id, request.user)

