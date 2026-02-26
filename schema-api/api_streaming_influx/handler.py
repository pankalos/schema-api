import os
import json

from rest_framework import status
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from django.utils.crypto import get_random_string
from django.utils import timezone

from .models import InfluxDB
from .serializers import (
    InfluxDBCreateSerializer,
    InfluxDBSummarySerializer,
    InfluxDBSerializer
)

from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException


# ----------------------------
# Environment helpers
# ----------------------------

from typing import Optional


def _env(name: str, default: Optional[str] = None) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        if default is not None:
            return default
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_streaming_namespace() -> str:
    # Keep a safe default for local/dev, but in-cluster this should be set via ConfigMap
    return _env("SCHEMA_API_STREAMING_NAMESPACE", default="schema-api")


def get_listener_image() -> str:
    # Allow override via env; fallback keeps backwards compatibility
    return _env("SCHEMA_API_INFLUX_LISTENER_IMAGE", default="pankalos/user-journey-data-listener-gen:latest")


def get_listener_script() -> str:
    # New listener code you generated is typically named influxdb-listener.py
    # Allow override in case the image uses a different filename.
    return _env("SCHEMA_API_INFLUX_LISTENER_SCRIPT", default="influxdb-listener.py")


# ----------------------------
# K8s client (lazy init)
# ----------------------------

_K8S_API = None


def get_k8s_api():
    global _K8S_API
    if _K8S_API is not None:
        return _K8S_API

    try:
        config.load_incluster_config()
    except ConfigException:
        # local/dev (kubeconfig)
        config.load_kube_config()

    _K8S_API = client.CoreV1Api()
    return _K8S_API


# ----------------------------
# DB profile -> K8s Secret name
# ----------------------------

def _db_profile_to_secret_name(db_profile: str) -> str:
    """Resolve db_profile (string) -> Kubernetes Secret name.

    The mapping is provided by SCHEMA_API_STREAMING_DB_PROFILES as JSON:
      {"timescaleDB":"db-profile-timescale-db", "influxDB":"db-profile-influx-db"}
    """
    raw = os.environ.get("SCHEMA_API_STREAMING_DB_PROFILES", "{}").strip()
    try:
        mapping = json.loads(raw)
    except Exception as e:
        raise ValidationError({"db_profile": f"SCHEMA_API_STREAMING_DB_PROFILES is not valid JSON: {e}"})

    if not isinstance(mapping, dict):
        raise ValidationError({"db_profile": "SCHEMA_API_STREAMING_DB_PROFILES must be a JSON object"})

    key = (db_profile or "").strip()
    secret_name = mapping.get(key)
    if not secret_name:
        raise ValidationError({
            "db_profile": (
                f"Unknown db_profile {db_profile!r} (normalized={key!r}). "
                f"Available profiles: {sorted(mapping.keys())}"
            )
        })
    return secret_name


# ----------------------------
# CREATE
# ----------------------------

def handle_influx_create(data, user):
    serializer = InfluxDBCreateSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    return _create_influx_task(serializer.validated_data, user)


def _create_influx_task(validated_data, user):
    rand_s = get_random_string(10).lower()

    # Namespace is effectively fixed by RBAC; keep request namespace only for backwards compatibility
    namespace = get_streaming_namespace()

    db_profile = validated_data["db_profile"]
    influx_in = validated_data["influx_in"]
    influx_out = validated_data["influx_out"]
    modeler = validated_data["modeler"]

    # Guardrail: avoid writing predictions into exactly the same series as input
    if influx_in["bucket"] == influx_out["bucket"] and influx_in["measurement"] == influx_out["measurement"]:
        return Response(
            {"error": "influx_in and influx_out cannot use the same bucket+measurement"},
            status=400
        )

    # Resolve secret name and inject env vars into listener pod
    # Secret is expected to contain INFLUX_URL, INFLUX_ORG, INFLUX_TOKEN
    secret_profile_name = _db_profile_to_secret_name(db_profile)
    env_from = [client.V1EnvFromSource(secret_ref=client.V1SecretEnvSource(name=secret_profile_name))]

    LISTENER_IMAGE = get_listener_image()
    LISTENER_SCRIPT = get_listener_script()

    pod_modeler_name = f"influxdb-modeler-{rand_s}"
    pod_listener_name = f"influxdb-listener-{rand_s}"
    svc_modeler_name = f"influxdb-modeler-svc-{rand_s}"

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

    # --- Build listener args (NEW listener contract) ---
    #
    # Credentials (INFLUX_URL / INFLUX_ORG / INFLUX_TOKEN) are NOT passed as args anymore.
    # They come from env vars injected from the db_profile secret.
    args = [
        "python", "-u", LISTENER_SCRIPT,
        "--target_service", svc_modeler_name,
        "--target_endpoint", modeler["endpoint"],
        # "--namespace", namespace,  # kept for compatibility (listener ignores it)
        "--port", str(modeler["port"]),

        "--everyTs", str(influx_in["everyTs"]),
        "--bucket_in", influx_in["bucket"],
        "--measurement_in", influx_in["measurement"],

        "--bucket_out", influx_out["bucket"],
        "--measurement_out", influx_out["measurement"],
    ]

    # Optional: pass write precision only when user provided it (listener defaults to 's')
    if influx_out.get("write_precision"):
        args += ["--write_precision", influx_out["write_precision"]]

    # Optional: modeler-returned time key (strict if set)
    if influx_out.get("time_col_out"):
        args += ["--time_col_out", influx_out["time_col_out"]]

    # Optional: include input time to modeler (listener uses fixed key 'ts')
    if modeler.get("include_time_to_mod", False):
        args.append("--include_time_to_mod")

    # Optional tags/cols
    if influx_in.get("tags"):
        args.append("--tags_in")
        args.extend(influx_in["tags"])
    if influx_in.get("cols"):
        args.append("--cols_in")
        args.extend(influx_in["cols"])

    if influx_out.get("tags"):
        args.append("--tags_out")
        args.extend(influx_out["tags"])
    if influx_out.get("cols"):
        args.append("--cols_out")
        args.extend(influx_out["cols"])

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
                    args=args,
                    env_from=env_from,  # <--- inject INFLUX_* from secret
                )
            ]
        ),
    )
    get_k8s_api().create_namespaced_pod(namespace=namespace, body=pod_listener)

    # --- Save metadata to schema-api DB (NO secrets) ---
    journey = InfluxDB.objects.create(
        id=rand_s,
        user=user,
        namespace=namespace,
        pod_modeler_name=pod_modeler_name,
        svc_modeler_name=svc_modeler_name,
        pod_listener_name=pod_listener_name,
        db_profile=db_profile,
        influx_in=influx_in,
        influx_out=influx_out,
        modeler=modeler,
        status="created",
    )

    return Response({"task_id": journey.id, "status": "created"}, status=status.HTTP_201_CREATED)


# ----------------------------
# LIST / DETAIL
# ----------------------------

def handle_influx_list(user):
    journeys = InfluxDB.objects.filter(user=user)
    serializer = InfluxDBSummarySerializer(journeys, many=True)
    return Response(serializer.data, status=200)


def handle_influx_detail(task_id, user):
    try:
        journey = InfluxDB.objects.get(id=task_id, user=user)
        serializer = InfluxDBSerializer(journey)
        return Response(serializer.data, status=200)
    except InfluxDB.DoesNotExist:
        return Response({"error": "Not found"}, status=404)


# ----------------------------
# TERMINATE
# ----------------------------

def handle_influx_terminate(task_id, user):
    try:
        journey = InfluxDB.objects.get(id=task_id, user=user)

        # Delete pods + service (ignore 404)
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

    except InfluxDB.DoesNotExist:
        return Response({"error": "Not found"}, status=404)
    except Exception as e:
        return Response({"error": str(e)}, status=500)
