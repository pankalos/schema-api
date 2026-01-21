from rest_framework import status
from rest_framework.response import Response
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


# Ensure in-cluster config is loaded once
_K8S_API = None
def get_k8s_api():
    """Return a Kubernetes CoreV1Api client.

    - In cluster: uses ServiceAccount via load_incluster_config()
    - Local/dev: falls back to kubeconfig via load_kube_config()
    """
    global _K8S_API
    if _K8S_API is None:
        try:
            config.load_incluster_config()
        except ConfigException:
            config.load_kube_config()
        _K8S_API = client.CoreV1Api()
    return _K8S_API


# ---------- CREATE ----------

def handle_influx_create(data, user):
    serializer = InfluxDBCreateSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    return _create_influx_task(serializer.validated_data, user)


def _create_influx_task(validated_data, user):
    rand_s = get_random_string(10).lower()
    namespace = validated_data["namespace"]
    influx_in = validated_data["influx_in"]
    influx_out = validated_data["influx_out"]
    modeler = validated_data["modeler"]

    if influx_in["url"] == influx_out["url"] and influx_in["bucket"] == influx_out["bucket"]:
        return Response({"error": "influx_in and influx_out cannot use the same bucket/url"}, status=400)

    pod_modeler_name = f"influxdb-modeler-{rand_s}"
    pod_listener_name = f"influxdb-listener-{rand_s}"
    svc_modeler_name = f"influxdb-modeler-svc-{rand_s}"

    # --- Create modeler pod ---
    pod_modeler = client.V1Pod(
        metadata=client.V1ObjectMeta(name=pod_modeler_name, namespace=namespace, labels={"role": "modeler", "stream_id": rand_s}),
        spec=client.V1PodSpec(containers=[
            client.V1Container(
                name=pod_modeler_name,
                image=modeler["image"],
                args=modeler["args"],
                ports=[client.V1ContainerPort(container_port=modeler["port"])]
            )
        ])
    )
    get_k8s_api().create_namespaced_pod(namespace=namespace, body=pod_modeler)

    # --- Create modeler service ---
    service = client.V1Service(
        metadata=client.V1ObjectMeta(name=svc_modeler_name, namespace=namespace),
        spec=client.V1ServiceSpec(
            selector={"role": "modeler", "stream_id": rand_s},
            ports=[client.V1ServicePort(port=modeler["port"], target_port=modeler["port"])]
        )
    )
    get_k8s_api().create_namespaced_service(namespace=namespace, body=service)

    # --- Build listener args ---
    args = [
        "python", "-u", "user-journey-data-listener-gen.py",
        "--target_service", svc_modeler_name,
        "--namespace", namespace,
        "--port", str(modeler["port"]),
        "--target_endpoint", modeler["endpoint"],
        "--bucket_in", influx_in["bucket"],
        "--org_in", influx_in["org"],
        "--token_in", influx_in["token"],
        "--influx_url_in", influx_in["url"],
        "--everyTs", str(influx_in["everyTs"]),
        "--measurement_in", influx_in["measurement"],
        "--bucket_out", influx_out["bucket"],
        "--org_out", influx_out["org"],
        "--token_out", influx_out["token"],
        "--influx_url_out", influx_out["url"],
        "--measurement_out", influx_out["measurement"],
        "--col_t_name_out", influx_out["col_time"]
    ]

    # Add optional tags and columns
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
        metadata=client.V1ObjectMeta(name=pod_listener_name, namespace=namespace, labels={"role": "listener", "stream_id": rand_s}),
        spec=client.V1PodSpec(containers=[
            client.V1Container(
                name=pod_listener_name,
                image="pankalos/user-journey-data-listener-gen:latest",
                args=args,
                ports=[client.V1ContainerPort(container_port=5000)]
            )
        ])
    )
    get_k8s_api().create_namespaced_pod(namespace=namespace, body=pod_listener)

    # --- Save to DB ---
    journey = InfluxDB.objects.create(
        id=rand_s,
        user=user,
        namespace=namespace,
        pod_modeler_name=pod_modeler_name,
        svc_modeler_name=svc_modeler_name,
        pod_listener_name=pod_listener_name,
        influx_in=influx_in,
        influx_out=influx_out,
        modeler=modeler,
        status="created"
    )

    return Response({"task_id": journey.id, "status": "created"}, status=status.HTTP_201_CREATED)


# ---------- LIST ----------

def handle_influx_list(user):
    journeys = InfluxDB.objects.filter(user=user)
    serializer = InfluxDBSummarySerializer(journeys, many=True)
    return Response(serializer.data, status=200)


# ---------- DETAIL ----------

def handle_influx_detail(task_id, user):
    try:
        journey = InfluxDB.objects.get(id=task_id, user=user)
        serializer = InfluxDBSerializer(journey)
        return Response(serializer.data, status=200)
    except InfluxDB.DoesNotExist:
        return Response({"error": "Not found"}, status=404)


# ---------- TERMINATE ----------

def handle_influx_terminate(task_id, user):
    try:
        journey = InfluxDB.objects.get(id=task_id, user=user)

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

