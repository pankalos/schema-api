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






def _delete_leaf_influx_k8s_resources(journey: LeafInfluxDB) -> None:
    """
    Delete Kubernetes resources created for this streaming job.

    Important:
    This function only deletes pods/services.
    It does NOT decide the final DB status.

    So it can be reused by:
    - manual terminate      -> status = Terminated
    - automatic error sync  -> status = Error
    """
    try:
        get_k8s_api().delete_namespaced_pod(
            name=journey.pod_modeler_name,
            namespace=journey.namespace,
        )
    except client.exceptions.ApiException as e:
        if e.status != 404:
            raise

    try:
        get_k8s_api().delete_namespaced_pod(
            name=journey.pod_listener_name,
            namespace=journey.namespace,
        )
    except client.exceptions.ApiException as e:
        if e.status != 404:
            raise

    try:
        get_k8s_api().delete_namespaced_service(
            name=journey.svc_modeler_name,
            namespace=journey.namespace,
        )
    except client.exceptions.ApiException as e:
        if e.status != 404:
            raise






def _read_pod(namespace: str, pod_name: str):
    """
    Return the Kubernetes pod object, or None if it does not exist.
    """
    try:
        return get_k8s_api().read_namespaced_pod(
            name=pod_name,
            namespace=namespace,
        )
    except client.exceptions.ApiException as e:
        if e.status == 404:
            return None
        raise


def _tail_pod_logs(namespace: str, pod_name: str, lines: int = 40) -> str:
    """
    Return last log lines for a pod.
    Used only when we detect an error.
    """
    try:
        logs = get_k8s_api().read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            tail_lines=lines,
        )
        return logs or ""
    except Exception as e:
        return f"Could not read pod logs: {e}"


def _container_error_message(pod, label: str) -> str:
    """
    Inspect one pod and return an error message if the pod/container is in
    a failed or suspicious state.

    Returns empty string if no pod-level error is detected.
    """
    if pod is None:
        return f"{label} pod does not exist."

    pod_name = pod.metadata.name
    namespace = pod.metadata.namespace
    phase = pod.status.phase

    if phase == "Failed":
        logs = _tail_pod_logs(namespace, pod_name)
        return (
            f"{label} pod failed. "
            f"reason={pod.status.reason}, message={pod.status.message}\n"
            f"Last logs:\n{logs}"
        )

    container_statuses = pod.status.container_statuses or []

    for cs in container_statuses:
        state = cs.state

        if state.waiting:
            reason = state.waiting.reason or ""
            message = state.waiting.message or ""

            # These are common Kubernetes container-level error states.
            if reason in [
                "CrashLoopBackOff",
                "ImagePullBackOff",
                "ErrImagePull",
                "CreateContainerConfigError",
                "CreateContainerError",
                "InvalidImageName",
                "RunContainerError",
            ]:
                
                logs = _tail_pod_logs(namespace, pod_name)

                previous = ""
                if cs.last_state and cs.last_state.terminated:
                    previous_term = cs.last_state.terminated
                    previous = (
                        f" Previous termination: "
                        f"exit_code={previous_term.exit_code}, "
                        f"reason={previous_term.reason}, "
                        f"message={previous_term.message}."
                    )

                return (
                    f"{label} container is waiting with error. "
                    f"container={cs.name}, reason={reason}, message={message}."
                    f"{previous}\n"
                    f"Last logs:\n{logs}"
                )

        if state.terminated:
            reason = state.terminated.reason or ""
            message = state.terminated.message or ""
            exit_code = state.terminated.exit_code

            if exit_code != 0:
                logs = _tail_pod_logs(namespace, pod_name)
                return (
                    f"{label} container terminated with non-zero exit code. "
                    f"container={cs.name}, exit_code={exit_code}, "
                    f"reason={reason}, message={message}\n"
                    f"Last logs:\n{logs}"
                )

    return ""


def _pod_is_running_and_ready(pod) -> bool:
    """
    True only when pod phase is Running and all containers are ready.
    """
    if pod is None:
        return False

    if pod.status.phase != "Running":
        return False

    container_statuses = pod.status.container_statuses or []

    if not container_statuses:
        return False

    return all(cs.ready for cs in container_statuses)




def sync_leaf_influx_status(journey: LeafInfluxDB) -> LeafInfluxDB:
    """
    Refresh DB status based on current Kubernetes pod state.

    Called from list/detail.

    If an error is detected:
    - status becomes Error
    - error_message is saved
    - total_runtime is frozen
    - Kubernetes pods/services are cleaned up
    - DB row remains as Error

    If user manually terminates:
    - status is Completed
    - sync does not touch it again
    """
    if journey.status in ["Completed", "Error"]:
        return journey

    listener_pod = _read_pod(journey.namespace, journey.pod_listener_name)
    modeler_pod = _read_pod(journey.namespace, journey.pod_modeler_name)

    listener_error = _container_error_message(listener_pod, "listener")
    modeler_error = _container_error_message(modeler_pod, "modeler")

    if listener_error or modeler_error:
        error_message = "\n\n".join(
            msg for msg in [listener_error, modeler_error] if msg
        )

        journey.status = "Error"
        journey.status_updated_at = timezone.now()
        journey.error_message = error_message

        if journey.total_runtime is None:
            journey.total_runtime = timezone.now() - journey.created_at

        journey.save(
            update_fields=[
                "status",
                "status_updated_at",
                "error_message",
                "total_runtime",
            ]
        )

        # Auto-cleanup after error detection.
        # Keep DB status as Error.
        try:
            _delete_leaf_influx_k8s_resources(journey)
        except Exception as cleanup_error:
            journey.error_message = (
                f"{journey.error_message}\n\n"
                f"Cleanup error after detecting task failure: {cleanup_error}"
            )
            journey.status_updated_at = timezone.now()
            journey.save(update_fields=["error_message", "status_updated_at"])

        return journey

    if _pod_is_running_and_ready(listener_pod) and _pod_is_running_and_ready(modeler_pod):
        if journey.status != "Running" or journey.error_message:
            journey.status = "Running"
            journey.status_updated_at = timezone.now()
            journey.error_message = None
            journey.save(
                update_fields=[
                    "status",
                    "status_updated_at",
                    "error_message",
                ]
            )

        return journey

    # Not failed, but not fully running yet.
    if journey.status != "Queued" or journey.error_message:
        journey.status = "Queued"
        journey.status_updated_at = timezone.now()
        journey.error_message = None
        journey.save(
            update_fields=[
                "status",
                "status_updated_at",
                "error_message",
            ]
        )

    return journey






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
    mqtt_conf = validated_data["mqtt"]

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
    # We inject sensitive values through env vars where possible.
    listener_args = [
        "--target_service", svc_modeler_name,
        "--target_endpoint", modeler["endpoint"],
        "--port", str(modeler["port"]),

        "--organisation", source["organisation"],
        "--department", source["department"],
        "--entity", source["entity"],

        "--metrics", *source["metrics"],
        "--everyTs", str(source["everyTs"]),
    ]

    listener_env = [
        client.V1EnvVar(name="LEAF_API_URL", value=source["api_url"]),
        client.V1EnvVar(name="LEAF_API_TOKEN", value=source["token"]),
    ]

    
    # MQTT write-back is required now.
    # Values come from the POST payload.
    # Username/password are injected into the dynamically-created listener pod.
    listener_args += [
        "--mqtt_host", mqtt_conf["host"],
        "--mqtt_port", str(mqtt_conf.get("port", 443)),
        "--mqtt_topic", mqtt_conf["topic"],
        "--mqtt_basepath", mqtt_conf.get("basepath", "mqtt"),
        "--mqtt_measurement", mqtt_conf["measurement"],
    ]

    output_tags = mqtt_conf.get("output_tags") or []
    if output_tags:
        listener_args += ["--output_tags", *output_tags]

    listener_env += [
        client.V1EnvVar(name="MQTT_USERNAME", value=mqtt_conf["username"]),
        client.V1EnvVar(name="MQTT_PASSWORD", value=mqtt_conf["password"]),
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

    
    mqtt_safe = dict(mqtt_conf)
    mqtt_safe.pop("password", None)


    leaf_task = LeafInfluxDB.objects.create(
        id=rand_s,
        user=user,
        namespace=namespace,
        pod_modeler_name=pod_modeler_name,
        svc_modeler_name=svc_modeler_name,
        pod_listener_name=pod_listener_name,
        source=source_safe,
        modeler=modeler,
        mqtt=mqtt_safe,
        status="Queued",
        status_updated_at=timezone.now(),
        error_message=None,
    )

    serializer = LeafInfluxSummarySerializer(leaf_task)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


# ----------------------------
# LIST / DETAIL
# ----------------------------

def handle_leaf_influx_list(user):
    journeys = list(LeafInfluxDB.objects.filter(user=user))

    for journey in journeys:
        sync_leaf_influx_status(journey)

    serializer = LeafInfluxSummarySerializer(journeys, many=True)
    return Response(serializer.data, status=200)



def handle_leaf_influx_detail(task_id, user):
    try:
        journey = LeafInfluxDB.objects.get(id=task_id, user=user)
        journey = sync_leaf_influx_status(journey)
        serializer = LeafInfluxSerializer(journey)
        return Response(serializer.data, status=200)
    except LeafInfluxDB.DoesNotExist:
        return Response({"error": "Not found"}, status=404)



# ----------------------------
# TERMINATE
# ----------------------------

def handle_leaf_influx_terminate(task_id, user):
    try:
        task = LeafInfluxDB.objects.get(id=task_id, user=user)

        _delete_leaf_influx_k8s_resources(task)

        if task.total_runtime is None:
            task.total_runtime = timezone.now() - task.created_at

        task.status = "Completed"
        task.status_updated_at = timezone.now()
        task.error_message = None

        task.save(
            update_fields=[
                "status",
                "status_updated_at",
                "error_message",
                "total_runtime",
            ]
        )

        serializer = LeafInfluxSummarySerializer(task)
        return Response(serializer.data, status=200)

    except LeafInfluxDB.DoesNotExist:
        return Response({"error": "Not found"}, status=404)
    except Exception as e:
        return Response({"error": str(e)}, status=500)

