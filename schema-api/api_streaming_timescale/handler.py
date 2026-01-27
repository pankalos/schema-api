import os, json
from rest_framework import status
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from django.utils.crypto import get_random_string
from django.utils import timezone

from .models import TimescaleDB
from .serializers import TimescaleCreateSerializer, TimescaleStreamSummarySerializer, TimescaleStreamSerializer

from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException



def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_listener_image() -> str:
    return require_env("SCHEMA_API_TIMESCALE_LISTENER_IMAGE")

def get_streaming_namespace() -> str:
    return require_env("SCHEMA_API_STREAMING_NAMESPACE")



# Ensure in-cluster config is loaded once. Lazy Kubernetes client init
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



def _db_profile_to_secret_name(db_profile: str) -> str:
    # Read from env (ConfigMap often adds a trailing newline)
    raw = os.environ.get("SCHEMA_API_STREAMING_DB_PROFILES", "{}").strip()

    # Parse JSON safely
    try:
        mapping = json.loads(raw)
    except Exception as e:
        raise ValidationError({
            "db_profile": f"SCHEMA_API_STREAMING_DB_PROFILES is not valid JSON: {e}"
        })

    # Ensure it's a dict (profile -> secret name)
    if not isinstance(mapping, dict):
        raise ValidationError({
            "db_profile": "SCHEMA_API_STREAMING_DB_PROFILES must be a JSON object like "
                          '{"timescaleDB":"db-profile-timescale-db"}'
        })

    # Normalize incoming key
    key = (db_profile or "").strip()

    secret_profile_name = mapping.get(key)
    if not secret_profile_name:
        raise ValidationError({
            "db_profile": (
                f"Unknown db_profile {db_profile!r} (normalized={key!r}). "
                f"Available profiles: {sorted(mapping.keys())}"
            )
        })

    return secret_profile_name




# ---------- CREATE ----------

def handle_timescale_create(data, user):
    serializer = TimescaleCreateSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    validated_data = serializer.validated_data

    # LISTENER_IMAGE = "pankalos/timescaledb-listener:latest-b"
    LISTENER_IMAGE = get_listener_image()
    STREAMING_NAMESPACE = get_streaming_namespace()


    rand_s = get_random_string(10).lower()
    # namespace = "schema-api"                    # Hardcoded Predefined namespace!
    namespace = STREAMING_NAMESPACE
    psql_in   = validated_data["psql_in"]
    psql_out  = validated_data["psql_out"]
    modeler   = validated_data["modeler"]
    db_profile = validated_data["db_profile"]


    # Resolve the Kubernetes Secret *name* from the profile (allowlist mapping)
    # Example: db_profile="timescaleDB" -> secret_profile_name="db-profile-timescaleDB"
    secret_profile_name = _db_profile_to_secret_name(db_profile)

    # Tell Kubernetes: "load ALL key/value pairs from this Secret as environment variables
    # inside the *listener container*".
    # If the Secret contains keys like PSQL_HOST, PSQL_PORT, ... then inside the container:
    #   PSQL_HOST=<value>, PSQL_PORT=<value>, ...
    env_from = [
        client.V1EnvFromSource(
            secret_ref=client.V1SecretEnvSource(name=secret_profile_name)
        )
    ]

    pod_modeler_name = f"modeler-{rand_s}"
    svc_modeler_name = f"modeler-svc-{rand_s}"
    pod_listener_name = f"listener-{rand_s}"

    # 1) modeler pod
    pod_modeler = client.V1Pod(
        metadata=client.V1ObjectMeta(name=pod_modeler_name, namespace=namespace, labels={"role":"modeler", "stream_id": rand_s}),
        spec=client.V1PodSpec(containers=[
            client.V1Container(
                name=pod_modeler_name,
                image=modeler["image"],
                args=modeler.get("args", []),
                ports=[client.V1ContainerPort(container_port=modeler["port"])]
            )
        ])
    )
    get_k8s_api().create_namespaced_pod(namespace=namespace, body=pod_modeler)

    # 2) modeler service
    service = client.V1Service(
        metadata=client.V1ObjectMeta(name=svc_modeler_name, namespace=namespace),
        spec=client.V1ServiceSpec(
            selector={"role":"modeler", "stream_id": rand_s},
            ports=[client.V1ServicePort(port=modeler["port"], target_port=modeler["port"])]
        )
    )
    get_k8s_api().create_namespaced_service(namespace=namespace, body=service)


    # We pass DB connection parameters to the listener via args, BUT using $(...) placeholders.
    # Kubernetes expands $(PSQL_HOST) etc. at container start time using the env vars above.
    # So the listener ultimately receives real values like:
    #   --psql_host timescaledb.schema-api.svc.cluster.local
    args = [
        "python", "-u", "timescaledb-listener.py",
        "--modeler_service", svc_modeler_name,
        "--modeler_endpoint", modeler["endpoint"],
        # "--modeler_namespace", namespace,         # Currently Both Modeler & Listener are in the same Namespace predifined above!
        "--modeler_port", str(modeler["port"]),

        "--psql_host", "$(PSQL_HOST)",
        "--psql_port", "$(PSQL_PORT)",
        "--psql_dbname", "$(PSQL_DBNAME)",
        "--psql_dbtable_in", psql_in["table_in"],
        "--psql_user", "$(PSQL_USER)",
        "--psql_password", "$(PSQL_PASSWORD)",

        "--everyTs", str(psql_in["everyTs"]),
        "--cols_in", *psql_in["cols_in"],
        "--time_col_in", psql_in["time_col_in"],

        "--psql_dbtable_out", psql_out["table_out"],
        "--time_col_out", psql_out["time_col_out"],
        "--cols_types_out", *psql_out["cols_types_out"],
    ]

    include_time = modeler.get("include_time_to_mod", False)
    if include_time:
        args.append("--include_time_to_mod")

    rename_inp_time_col = str(modeler.get("rename_inp_time_col_to_mod_as", ""))
    if rename_inp_time_col != "":
        args += ["--rename_inp_time_col_to_mod_as", rename_inp_time_col]


    make_hypertable = psql_out.get("make_hypertable", False)
    if make_hypertable:
        args.append("--make_hypertable")

    args += ["--chunk_interval", psql_out.get("chunk_interval", "1 hour")]


    migrate_existing = psql_out.get("migrate_existing", False)
    if migrate_existing:
        args.append("--migrate_existing")


    # Listener pod: env_from must be included so $(PSQL_*) placeholders can expand
    pod_listener = client.V1Pod(
        metadata=client.V1ObjectMeta(name=pod_listener_name, namespace=namespace, labels={"role":"timescale-listener", "stream_id": rand_s}),
        spec=client.V1PodSpec(containers=[
            client.V1Container(
                name=pod_listener_name,
                image=LISTENER_IMAGE,
                args=args,
                env_from=env_from
            )
        ])
    )

    get_k8s_api().create_namespaced_pod(namespace=namespace, body=pod_listener)

    # --- Save to DB (store ONLY the profile name + non-secret configs) ---
    job = TimescaleDB.objects.create(
        id=rand_s, 
        user=user, 
        namespace=namespace,
        pod_modeler_name=pod_modeler_name,
        svc_modeler_name=svc_modeler_name,
        pod_listener_name=pod_listener_name,
        db_profile=db_profile,
        psql_in=psql_in, 
        psql_out=psql_out, 
        modeler=modeler,
        status="Running"
    )

    return Response({"id": job.id}, status=status.HTTP_201_CREATED)


# ---------- LIST ----------

def handle_timescale_list(user):
    ts_journeys = TimescaleDB.objects.filter(user=user)
    serializer = TimescaleStreamSummarySerializer(ts_journeys, many=True)
    return Response(serializer.data, status=200)


# ---------- DETAIL ----------

def handle_timescale_detail(task_id, user):
    try:
        ts_journey = TimescaleDB.objects.get(id=task_id, user=user)
        serializer = TimescaleStreamSerializer(ts_journey)
        return Response(serializer.data, status=200)
    except TimescaleDB.DoesNotExist:
        return Response({"error": "Not found"}, status=404)


# ---------- TERMINATE ----------

def handle_timescale_terminate(task_id, user):
    try:
        job = TimescaleDB.objects.get(pk=task_id, user=user)
        # delete pods and service (ignore 404s)
        try: get_k8s_api().delete_namespaced_pod(name=job.pod_listener_name, namespace=job.namespace)
        except Exception: pass
        try: get_k8s_api().delete_namespaced_pod(name=job.pod_modeler_name, namespace=job.namespace)
        except Exception: pass
        try: get_k8s_api().delete_namespaced_service(name=job.svc_modeler_name, namespace=job.namespace)
        except Exception: pass

        if job.total_runtime is None:
            job.total_runtime = timezone.now() - job.created_at
        job.status = "Terminated"
        job.save()
        return Response({"status": "Terminated"}, status=200)
    except TimescaleDB.DoesNotExist:
        return Response({"error":"Not found"}, status=404)

