import os

from typing import Optional

from rest_framework import status
from rest_framework.response import Response
from django.utils.crypto import get_random_string
from django.utils import timezone

from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException

from .models import LeafInfluxDB
from .serializers import (
    LeafInfluxCreateSerializer,
    LeafInfluxSummarySerializer,
    LeafInfluxSerializer,
)


# ----------------------------
# Environment helpers
# ----------------------------

def _env(name: str, default: Optional[str] = None) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        if default is not None:
            return default
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_streaming_namespace() -> str:
    return _env("SCHEMA_API_STREAMING_NAMESPACE", default="schema-api")


def get_listener_image() -> str:
    return _env(
        "SCHEMA_API_LEAF_INFLUX_LISTENER_IMAGE",
        default="pankalos/leaf-influx-listener:latest"
    )


def get_listener_script() -> str:
    return _env(
        "SCHEMA_API_LEAF_INFLUX_LISTENER_SCRIPT",
        default="leaf-listener.py"
    )


# ----------------------------
# K8s client
# ----------------------------

_k8s_api = None


def get_k8s_api():
    global _k8s_api
    if _k8s_api is None:
        try:
            config.load_incluster_config()
        except ConfigException:
            config.load_kube_config()
        _k8s_api = client.CoreV1Api()
    return _k8s_api


# ----------------------------
# CREATE
# ----------------------------

def handle_leaf_influx_create(data, user):
    serializer = LeafInfluxCreateSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    return _create_leaf_influx_task(serializer.validated_data, user)


def _create_leaf_influx_task(validated_data, user):
    rand_s = get_random_string(10).lower()
    namespace = get_streaming_namespace()

    source = validated_data["source"]
    modeler = validated_data["modeler"]

    LISTENER_IMAGE = get_listener_image()
    LISTENER_SCRIPT = get_listener_script()

    pod_modeler_name = f"leaf-influx-modeler-{rand_s}"
    pod_listener_name = f"leaf-influx-listener-{rand_s}"
    svc_modeler_name = f"leaf-influx-modeler-svc-{rand_s}"

    # --- Create modeler pod ---
    pod_modeler = client.V1Pod(
        metadata=client.V1ObjectMeta(
            name=pod_modeler_name,
            namespace=namespace,
            labels={"role": "modeler", "stream_id": rand_s},
        ),
        spec=client.V1PodSpec(
            containers=[
                client.V1Container(
                    name=pod_modeler_name,
                    image=modeler["image"],
                    args=modeler.get("args", []),
                    ports=[client.V1ContainerPort(container_port=modeler["port"])],
                )
            ]
        ),
    )
    get_k8s_api().create_namespaced_pod(namespace=namespace, body=pod_modeler)

    # --- Create modeler service ---
    service = client.V1Service(
        metadata=client.V1ObjectMeta(name=svc_modeler_name, namespace=namespace),
        spec=client.V1ServiceSpec(
            selector={"role": "modeler", "stream_id": rand_s},
            ports=[client.V1ServicePort(port=modeler["port"], target_port=modeler["port"])],
        ),
    )
    get_k8s_api().create_namespaced_service(namespace=namespace, body=service)

    # Listener flags only.
    # We inject LEAF_API_URL and LEAF_API_TOKEN through env vars.
    listener_args = [
        "--target_service", svc_modeler_name,
        "--target_endpoint", modeler["endpoint"],
        "--port", str(modeler["port"]),
        "--organisation", source["organisation"],
        "--department", source["department"],
        "--metrics", *source["metrics"],
        "--everyTs", str(source["everyTs"]),
    ]

    if source.get("entity"):
        listener_args += ["--entity", source["entity"]]

    if modeler.get("include_time_to_mod", False):
        listener_args.append("--include_time_to_mod")

    listener_env = [
        client.V1EnvVar(name="LEAF_API_URL", value=source["api_url"]),
        client.V1EnvVar(name="LEAF_API_TOKEN", value=source["token"]),
    ]

    # --- Create listener pod ---
    pod_listener = client.V1Pod(
        metadata=client.V1ObjectMeta(
            name=pod_listener_name,
            namespace=namespace,
            labels={"role": "listener", "stream_id": rand_s},
        ),
        spec=client.V1PodSpec(
            containers=[
                client.V1Container(
                    name=pod_listener_name,
                    image=LISTENER_IMAGE,
                    command=["python", "-u", LISTENER_SCRIPT],
                    args=listener_args,
                    env=listener_env,
                )
            ]
        ),
    )
    get_k8s_api().create_namespaced_pod(namespace=namespace, body=pod_listener)

    # Save non-secret source config only
    source_safe = dict(source)
    source_safe.pop("token", None)

    journey = LeafInfluxDB.objects.create(
        id=rand_s,
        user=user,
        namespace=namespace,
        pod_modeler_name=pod_modeler_name,
        svc_modeler_name=svc_modeler_name,
        pod_listener_name=pod_listener_name,
        source=source_safe,
        modeler=modeler,
        status="created",
    )

    return Response({"task_id": journey.id, "status": "created"}, status=status.HTTP_201_CREATED)


# ----------------------------
# LIST / DETAIL
# ----------------------------

def handle_leaf_influx_list(user):
    journeys = LeafInfluxDB.objects.filter(user=user)
    serializer = LeafInfluxSummarySerializer(journeys, many=True)
    return Response(serializer.data, status=200)


def handle_leaf_influx_detail(task_id, user):
    try:
        journey = LeafInfluxDB.objects.get(id=task_id, user=user)
        serializer = LeafInfluxSerializer(journey)
        return Response(serializer.data, status=200)
    except LeafInfluxDB.DoesNotExist:
        return Response({"error": "Not found"}, status=404)


# ----------------------------
# TERMINATE
# ----------------------------

def handle_leaf_influx_terminate(task_id, user):
    try:
        journey = LeafInfluxDB.objects.get(id=task_id, user=user)

        try:
            get_k8s_api().delete_namespaced_pod(name=journey.pod_modeler_name, namespace=journey.namespace)
        except client.exceptions.ApiException as e:
            if e.status != 404:
                raise

        try:
            get_k8s_api().delete_namespaced_pod(name=journey.pod_listener_name, namespace=journey.namespace)
        except client.exceptions.ApiException as e:
            if e.status != 404:
                raise

        try:
            get_k8s_api().delete_namespaced_service(name=journey.svc_modeler_name, namespace=journey.namespace)
        except client.exceptions.ApiException as e:
            if e.status != 404:
                raise

        if journey.total_runtime is None:
            journey.total_runtime = timezone.now() - journey.created_at
        journey.status = "Terminated"
        journey.save()

        return Response({"status": "Terminated"}, status=200)

    except LeafInfluxDB.DoesNotExist:
        return Response({"error": "Not found"}, status=404)
    except Exception as e:
        return Response({"error": str(e)}, status=500)

