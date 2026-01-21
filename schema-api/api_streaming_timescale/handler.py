from rest_framework import status
from rest_framework.response import Response
from django.utils.crypto import get_random_string
from django.utils import timezone

from .models import TimescaleStreamDB
from .serializers import TimescaleCreateSerializer, TimescaleStreamSummarySerializer, TimescaleStreamSerializer

from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException


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



LISTENER_IMAGE = "pankalos/timescaledb-listener:latest-b"


# ---------- CREATE ----------

def handle_timescale_create(data, user):
    serializer = TimescaleCreateSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    validated_data = serializer.validated_data

    rand_s = get_random_string(10).lower()
    namespace = "schema-api"                    # Hardcoded Predefined namespace!
    psql_in   = validated_data["psql_in"]
    psql_out  = validated_data["psql_out"]
    modeler   = validated_data["modeler"]

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

    # 3) listener pod args. Modification need...
    args = [
        "python", "-u", "timescaledb-listener.py",
        "--modeler_service", svc_modeler_name,
        "--modeler_endpoint", modeler["endpoint"],
        # "--modeler_namespace", namespace,         # Currently Both Modeler & Listener are in the same Namespace predifined above!
        "--modeler_port", str(modeler["port"]),

        "--psql_host", psql_in["host"],
        "--psql_port", str(psql_in["port"]),
        "--psql_dbname", psql_in["dbname"],
        "--psql_dbtable_in", psql_in["table_in"],
        "--psql_user", psql_in["user"],
        "--psql_password", psql_in["password"],

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


    # 4) listener pod (inject PG password via Secret -> env -> script reads PGPASSWORD)
    # env = [client.V1EnvVar(
    #     name="PGPASSWORD",
    #     value_from=client.V1EnvVarSource(
    #         secret_key_ref=client.V1SecretKeySelector(name=psql_in["password_secret"], key="password")
    #     )
    # )]

    # print(f'args: ${args}')

    pod_listener = client.V1Pod(
        metadata=client.V1ObjectMeta(name=pod_listener_name, namespace=namespace, labels={"role":"timescale-listener", "stream_id": rand_s}),
        spec=client.V1PodSpec(containers=[
            client.V1Container(
                name=pod_listener_name,
                image=LISTENER_IMAGE,
                args=args,
                # env=env
            )
        ])
    )

    get_k8s_api().create_namespaced_pod(namespace=namespace, body=pod_listener)

    # --- Save to DB ---
    job = TimescaleStreamDB.objects.create(
        id=rand_s, user=user, namespace=namespace,
        pod_modeler_name=pod_modeler_name,
        svc_modeler_name=svc_modeler_name,
        pod_listener_name=pod_listener_name,
        psql_in=psql_in, psql_out=psql_out, modeler=modeler,
        status="Running"
    )

    return Response({"id": job.id}, status=status.HTTP_201_CREATED)


# ---------- LIST ----------

def handle_timescale_list(user):
    ts_journeys = TimescaleStreamDB.objects.filter(user=user)
    serializer = TimescaleStreamSummarySerializer(ts_journeys, many=True)
    return Response(serializer.data, status=200)


# ---------- DETAIL ----------

def handle_timescale_detail(task_id, user):
    try:
        ts_journey = TimescaleStreamDB.objects.get(id=task_id, user=user)
        serializer = TimescaleStreamSerializer(ts_journey)
        return Response(serializer.data, status=200)
    except TimescaleStreamDB.DoesNotExist:
        return Response({"error": "Not found"}, status=404)


# ---------- TERMINATE ----------

def handle_timescale_terminate(task_id, user):
    try:
        job = TimescaleStreamDB.objects.get(pk=task_id, user=user)
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
    except TimescaleStreamDB.DoesNotExist:
        return Response({"error":"Not found"}, status=404)

