# Kubernetes Deployment Guide for Schema-API and Schema-Lab

This guide explains how to deploy **Schema-API** and **Schema-Lab** on **Kubernetes**.

## Overview

To deploy the platform, you need the following components:

1. A Kubernetes cluster
2. A storage class that supports at least RWO mode
3. A storage backend for exchanging input/output with the external world
4. [TESK](https://github.com/elixir-cloud-aai/TESK?tab=readme-ov-file)
5. PostgreSQL for the Schema-API backend
6. [Schema-API](https://schema.athenarc.gr/docs/schema-api/)
7. Schema-Lab

---

## Quick Deployment Guides

The following quick guides describe one working deployment flow for the required dependencies of **Schema-API** and **Schema-Lab**:

1. [NFS](https://github.com/kubernetes-sigs/nfs-ganesha-server-and-external-provisioner.git) storage provisioner
2. [MinIO](https://docs.min.io/enterprise/aistor-object-store/installation/kubernetes/)
3. [PostgreSQL](https://access.crunchydata.com/documentation/postgres-operator/latest/tutorials/basic-setup/create-cluster)
4. [TESK](https://github.com/elixir-cloud-aai/TESK.git)

> **Note:** These steps reflect one working deployment approach for this project.

---

## 1. Quick Deployment Guide: NFS

This [NFS](https://github.com/kubernetes-sigs/nfs-ganesha-server-and-external-provisioner.git) provisioner is used to provide a storage class that supports dynamic PVC/PV creation. In this setup, the storage class name is `storageclass-nfs`.

### 1. Clone the repository

```bash
git clone https://github.com/kubernetes-sigs/nfs-ganesha-server-and-external-provisioner.git
cd nfs-ganesha-server-and-external-provisioner
```

### 2. Configure the export volume

Edit `deploy/kubernetes/deployment.yaml` and mount a local directory or another supported volume at `/export`.

Example:

```yaml
volumeMounts:
  - name: export-volume
    mountPath: /export

volumes:
  - name: export-volume
    hostPath:
      path: /path/to/your/nfs-state-data
```

> The backing volume must use a supported local Linux filesystem. NFS itself is not supported as the backend for this export path.

### 3. Set the provisioner name

In `deploy/kubernetes/deployment.yaml`, set the provisioner argument:

```yaml
args:
  - "-provisioner=k8s-provisioner/nfs"
```

### 4. Deploy the provisioner

```bash
kubectl create -f deploy/kubernetes/deployment.yaml
```

### 5. Apply RBAC resources

```bash
kubectl create -f deploy/kubernetes/rbac.yaml
```

### 6. Create the StorageClass

Edit `deploy/kubernetes/class.yaml` so that it uses the same provisioner name:

```yaml
kind: StorageClass
apiVersion: storage.k8s.io/v1
metadata:
  name: storageclass-nfs
provisioner: k8s-provisioner/nfs
mountOptions:
  - vers=3
```

Apply it:

```bash
kubectl create -f deploy/kubernetes/class.yaml
```

### 7. Test with a PVC

Create a PVC using `storageclass-nfs`:

```yaml
kind: PersistentVolumeClaim
apiVersion: v1
metadata:
  name: nfs
spec:
  storageClassName: storageclass-nfs
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Mi
```

Apply it:

```bash
kubectl apply -f deploy/kubernetes/claim.yaml
```

Check that the PVC and PV are created:

```bash
kubectl get pv,pvc -A
```

> Deleting the PVC also deletes the dynamically provisioned PV and its data.

---

## 2. Quick Deployment Guide: MinIO

[MinIO](https://docs.min.io/enterprise/aistor-object-store/installation/kubernetes/) is used here as the S3-compatible storage backend. The deployment uses the **MinIO Operator** and a **Tenant**, both installed from local Helm charts.

### 1. Install the MinIO Operator

Download and extract the Operator chart:

```bash
curl -O https://raw.githubusercontent.com/minio/operator/master/helm-releases/operator-7.1.1.tgz
tar -xvzf operator-7.1.1.tgz
```

Optional: edit `operator/values.yaml` and reduce replicas if needed:

```yaml
replicaCount: 1
```

Install the operator:

```bash
helm install --namespace minio --create-namespace minio-operator ./operator
```

### 2. Install the MinIO Tenant

Download and extract the Tenant chart:

```bash
curl -O https://raw.githubusercontent.com/minio/operator/master/helm-releases/tenant-7.1.1.tgz
tar -xvzf tenant-7.1.1.tgz
```

Edit `tenant/values.yaml` and set values like these:

```yaml
configSecret:
  name: myminio-env-configuration
  accessKey: minio
  secretKey: minio-password

pools:
  volumesPerServer: 1
  size: 500Mi
  storageClassName: storageclass-nfs

certificate:
  requestAutoCert: false

exposeServices:
  minio: true
  console: true
```

Install the tenant:

```bash
helm install --namespace minio minio-tenant ./tenant
helm upgrade --install minio-tenant ./tenant -f ./tenant/values.yaml -n minio
```

### 3. Access the MinIO console

Check the service:

```bash
kubectl get svc -n minio
```

If `requestAutoCert: false`, access the console over HTTP using the NodePort shown for the console service. If `requestAutoCert: true`, use HTTPS instead.

Example credentials used in local testing:

```text
username: minio
password: minio-password
```

> Do not commit real credentials to GitHub. Replace them with placeholders in public documentation.

### 4. Verify MinIO with `mc`

Run a temporary MinIO client pod:

```bash
kubectl -n minio run mcsh --rm -it --restart=Never --image=minio/mc --command -- /bin/sh
```

Inside the pod:

```bash
mc alias set myminio http://myminio-tenant-hl:9000 'minio' 'minio-password'
mc admin info myminio
mc mb -p myminio/testbucket
echo hello | mc pipe myminio/testbucket/hello.txt
mc ls myminio/testbucket
exit
```

### 5. Create dedicated access keys for applications

A common pattern is to create a separate MinIO user and attach the `readwrite` policy:

```bash
mc admin user add myminio <ACCESS_KEY> '<SECRET_KEY>'
mc admin policy attach myminio readwrite --user <ACCESS_KEY>
```

Then test with the new credentials:

```bash
mc alias set myminio2 http://myminio-tenant-hl:9000 '<ACCESS_KEY>' '<SECRET_KEY>'
mc ls myminio2
```

### 6. Base64-encode credentials for Kubernetes secrets

You may need base64-encoded values for K8s manifests:

```bash
echo -n '<ACCESS_KEY>' | base64
echo -n '<SECRET_KEY>' | base64
```

These values can then be used in your Schema-API secrets.

---

## 3. Quick Deployment Guide: PostgreSQL

Schema-API requires PostgreSQL. In this setup, PostgreSQL is deployed with [**Crunchy Postgres for Kubernetes**](https://access.crunchydata.com/documentation/postgres-operator/latest/tutorials/basic-setup/create-cluster) using a Helm-based examples repository.

### 1. Clone the examples repository

```bash
git clone https://github.com/CrunchyData/postgres-operator-examples.git
cd postgres-operator-examples
```

### 2. Configure PostgreSQL values

Edit `helm/postgres/values.yaml`.

Example configuration:

```yaml
instanceSize: 500Mi
instanceStorageClassName: "storageclass-nfs"

users:
  - name: <POSTGRES_USER>
    databases:
      - schema
    options: 'SUPERUSER'

backupsSize: 500Mi
backupsStorageClassName: "storageclass-nfs"
```

### 3. Install the Crunchy Postgres Operator

```bash
helm install cpk helm/install --namespace postgres-operator --create-namespace
```

### 4. Install the PostgreSQL cluster

```bash
helm install schema helm/postgres --namespace postgres-operator
```

### 5. Read the generated credentials

Example:

```bash
kubectl get secret schema-pguser-<POSTGRES_USER> -n postgres-operator -o jsonpath='{.data.user}' | base64 --decode
```

The generated secret includes values such as:

- database name
- host
- user
- password
- port
- URI / JDBC URI

These values are used later in `schema-api-local-template.yaml`.

### 6. Upgrade or uninstall

Upgrade after changing values:

```bash
helm upgrade schema helm/postgres -n postgres-operator
```

Uninstall the cluster:

```bash
helm uninstall schema -n postgres-operator
```

Uninstall the operator:

```bash
helm uninstall cpk -n postgres-operator
```

### 7. Connect to PostgreSQL

```bash
kubectl exec schema-instance1-c9gt-0 -n postgres-operator -it -- psql
```

Useful commands inside `psql`:

```sql
\l
\dt
\c schema
\dnS
```

To recreate the public schema from scratch:

```sql
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
```

---

## 4. Quick Deployment Guide: TESK

[TESK](https://github.com/elixir-cloud-aai/TESK/tree/master) is the task execution backend used by Schema-API. In this setup it is configured to use **S3 storage**, **MinIO credentials**, and the `storageclass-nfs` storage class.

### 1. Clone TESK

```bash
git clone https://github.com/elixir-cloud-aai/TESK.git
cd TESK
```

### 2. Configure `charts/tesk/values.yaml`

Edit `charts/tesk/values.yaml` and update the deployment settings.

Example values:

```yaml
host_name: ""
storage: s3
storageClass: storageclass-nfs

tesk:
  tes_api_base_path: v1
  image: docker.io/elixircloud/tesk-api:1.1.0
  port: 8080
  taskmaster_image_name: docker.io/elixircloud/tesk-core-taskmaster
  taskmaster_image_version: v0.10.4
  taskmaster_filer_image_name: pankalos/tesk-core-filer-v0.10.4
  taskmaster_filer_image_version: patched

service:
  type: NodePort
  node_port: 31567
```

### 3. Configure S3 access for TESK

Go to:

```text
TESK/charts/tesk/s3-config/
```

Create the `config` file from the template:

```ini
[default]
endpoint_url=http://myminio-tenant-hl.minio.svc.cluster.local:9000
```

Create the `credentials` file from the template:

```ini
[default]
aws_access_key_id=<MINIO_ACCESS_KEY>
aws_secret_access_key=<MINIO_SECRET_KEY>
```

### 4. Create a test object in MinIO

Example file contents:

```text
Hello from Kubernetes storage
This is another line.
this too
Hello again here!
Hi!
```

Upload it to a bucket, for example `s3://test/testfile.txt`, before testing TESK.

### 5. Create the namespace and install TESK

```bash
kubectl create namespace tesk
cd charts/tesk
helm upgrade --install tesk-release . -f values.yaml -n tesk
```

### 6. Verify TESK

Check that the API is reachable:

```bash
curl --location 'http://<NODE_IP>:31567/v1/tasks'
```

Expected response:

```json
{
  "tasks": []
}
```

### 7. Submit a test task using S3 input/output

The following example looks for `testfile.txt` in S3 and:

1. Filters lines that contain `Hello` word
2. Rewrites them to uppercase
3. Creates a new file testfile-out.txt to s3 and writes the output

```bash
curl --location 'http://<NODE_IP>:31567/v1/tasks' \
  --header 'Content-Type: application/json' \
  --data '{
    "description": "string",
    "executors": [
      {
        "image": "alpine",
        "command": ["grep", "Hello"],
        "stdin": "/data/file1.txt",
        "stdout": "/data/file2.txt"
      },
      {
        "image": "alpine",
        "command": ["tr", "'\''a-z'\''", "'\''A-Z'\''"],
        "stdin": "/data/file2.txt",
        "stdout": "/data/file3.txt"
      }
    ],
    "inputs": [
      {
        "url": "s3://test/testfile.txt",
        "type": "FILE",
        "path": "/data/file1.txt"
      }
    ],
    "outputs": [
      {
        "url": "s3://test/testfile-out.txt",
        "path": "/data/file3.txt",
        "type": "FILE"
      }
    ],
    "resources": {
      "cpu_cores": 0.5,
      "disk_gb": 0.01,
      "preemptible": false
    },
    "tags": {
      "WORKFLOW_ID": "cwl-01",
      "PROJECT_GROUP": "my-lab"
    },
    "volumes": [
      "/data"
    ]
  }'
```

Example response:

```json
{
  "id": "task-xxxxxxxx"
}
```

### 8. Important note about TESK access

If TESK is exposed as a NodePort, the most stable public access method is usually:

```text
http://<NODE_IP>:31567/v1/tasks
```

---

## Recommended Dependency Order

Deploy the dependencies in this order:

1. NFS
2. MinIO
3. TESK
4. PostgreSQL

After all four are ready, continue with:

5. Schema-API
6. Schema-Lab

---

## Deployment Files

The following template files are provided in this repository and should be filled in with values matching your environment:

- `/deployment/k8s/schema-api-local-template.yaml`
- `/deployment/k8s/schema-lab-local.yaml`

> **Note:** `schema-api-local-template.yaml` is already provided in this repository. Edit the existing file before applying it.

---

## 1. Prepare `schema-api-local-template.yaml`

Open the provided `schema-api-local-template.yaml` file and update the values according to your environment.

### 1.1 DB profile credentials

Create the DB profiles accordingly. These are the profiles that streaming tasks connect to.

Update these values according to your environment:

#### InfluxDB example

```yaml
INFLUX_URL: "http://<INFLUX_HOST>:8086"
INFLUX_ORG: "<INFLUX_ORG>"
INFLUX_TOKEN: "<INFLUX_TOKEN>"
```

#### Timescale / PostgreSQL example

```yaml
PSQL_HOST: "http://<TIMESCALE_HOST>"
PSQL_PORT: "5432"
PSQL_DBNAME: "<TIMESCALE_DBNAME>"
PSQL_USER: "<TIMESCALE_USER>"
PSQL_PASSWORD: "<TIMESCALE_PASSWORD>"
```

If you have more profiles, add them to the `schema-api-db-profile-names-config` ConfigMap in:

```yaml
SCHEMA_API_STREAMING_DB_PROFILES
```

### 1.2 Schema-API PostgreSQL secret

Schema-API uses PostgreSQL to store states and data. This PostgreSQL instance is used by Schema-API for tasks and workflows.

Update the secret values:

```yaml
apiVersion: v1
kind: Secret
metadata:
  namespace: schema-api
  name: schema-api-db-secret
type: Opaque
stringData:
  POSTGRES_DB: "<SCHEMA_DB_NAME>"
  POSTGRES_USER: "<SCHEMA_DB_USER>"
  POSTGRES_PASSWORD: "<SCHEMA_DB_PASSWORD>"
```

### 1.3 Schema-API secret key

Set a random secret key for Schema-API in base64 format:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: schema-api-secret-key
  namespace: schema-api
data:
  secretKey: "<BASE64_SCHEMA_API_SECRET_KEY>"
```

### 1.4 S3 credentials

Update the S3 / MinIO credentials using base64-encoded values:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: s3-credentials
  namespace: schema-api
data:
  access_key_id: "<BASE64_S3_ACCESS_KEY_ID>"
  secret_access_key: "<BASE64_S3_SECRET_ACCESS_KEY>"
```

### 1.5 Schema-API ConfigMap

Update the `schema-api-config` ConfigMap according to your environment.

At minimum, review and update:

- `allowedHosts`
- `s3Url`
- `s3UseSSL`
- `teskEndpoint`
- `corsOrigins`

Example:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: schema-api-config
  namespace: schema-api
data:
  allowedHosts: "127.0.0.1,localhost,<SCHEMA_API_HOST>"
  s3Url: "http://<MINIO_API_HOST>:<MINIO_API_PORT>"
  slugPattern: "[-_a-zA-Z0-9]+"
  s3UseSSL: "no"
  s3MaxPartSize: "104857600"
  filesEnabled: "yes"
  authEnabled: "yes"
  taskApiClass: "api.taskapis.TesTaskApi"
  teskEndpoint: "http://<TESK_HOST>:<TESK_NODEPORT>/"
  corsOrigins: "http://<SCHEMA_LAB_HOST>:<SCHEMA_LAB_NODEPORT>"
  userThrottleRate: "200/minute"
  updateStateOnTasksListing: "no"
  cacheEnabled: "yes"
  cacheTimeout: "15"
  redisHost: "redis-cache"
```

> **Important:** If you expose Schema-API using `NodePort`, first deploy it, get the public host/IP, add that host to `allowedHosts`, and then re-apply the file.

### 1.6 Schema-API deployment database host

In the `schema-api` deployment, set:

```yaml
- name: SCHEMA_API_DB_HOST
  value: <POSTGRES_SERVICE_URL>
```

### 1.7 Schema-API watch deployment database host

In the `schema-api-watch` deployment, set:

```yaml
- name: SCHEMA_API_DB_HOST
  value: <POSTGRES_SERVICE_URL>
```

### 1.8 Schema workers TESK URL

In the `schema-workers` deployment, update the TESK API URL.

Example in-cluster URL:

```yaml
- 'http://tesk-api.tesk.svc.cluster.local:8080'
```

If you use a public NodePort instead, change it accordingly.

---

## 2. Apply the Schema-API Deployment

After filling in `schema-api-local-template.yaml`, apply it:

```bash
kubectl apply -f schema-api-local-template.yaml
```

You can check the resources with:

```bash
kubectl get pods -n schema-api
kubectl get svc -n schema-api
```

If you are using **NodePort**, get the Schema-API service IP/port and add it to `allowedHosts`.

Then re-apply the updated file and restart the deployments:

```bash
kubectl apply -f schema-api-local-template.yaml
kubectl rollout restart deployment/schema-api -n schema-api
kubectl rollout restart deployment/schema-api-watch -n schema-api
```

---

## 3. Run Database Migrations

It is possible that the `schema-api-watch` pod enters `CrashLoopBackOff` before migrations are applied. In that case, run the migrations manually from the `schema-api` pod.

### Check the pods

```bash
kubectl get pods -n schema-api
```

Example output:

```text
pod/schema-api-xxxxx                1/1   Running
pod/schema-api-cache-xxxxx          1/1   Running
pod/schema-api-watch-xxxxx          0/1   CrashLoopBackOff
pod/schema-workers-xxxxx            1/1   Running
```

### Enter the Schema-API pod

```bash
kubectl exec -n schema-api -it <SCHEMA_API_POD> -- sh
```

### Run migrations

```bash
python manage.py migrate
```

Wait until the pods become healthy:

```bash
kubectl get pods -n schema-api
```

After migrations complete, `schema-api-watch` should recover.

If needed, restart the watcher:

```bash
kubectl rollout restart deployment/schema-api-watch -n schema-api
```

---

## 4. Configure and Deploy Schema-Lab

Edit `schema-lab-local.yaml` and set the Schema-API URL accordingly.

Example:

```yaml
schemaApiUrl: http://<SCHEMA_API_HOST>:<SCHEMA_API_NODEPORT>
```

Then apply the file:

```bash
kubectl apply -f schema-lab-local.yaml
```

You can verify the deployment with:

```bash
kubectl get pods -n schema-api
kubectl get svc -n schema-api
```

---

## 5. Register an Application Service and Issue a Token

Enter the Schema-API pod:

```bash
kubectl exec -n schema-api -it <SCHEMA_API_POD> -- sh
```

Register an application service:

```bash
python manage.py application_service register test
```

Issue an API key valid for 10 years:

```bash
python manage.py application_service for test apikeys issue -d 10y
```

Save the generated token securely. Do **not** commit it to Git.

---

## 6. Create a Context

Use the application service token to create a new context.

```bash
curl --location 'http://<SCHEMA_API_HOST>:<SCHEMA_API_NODEPORT>/api_auth/contexts' \
  --header 'Content-Type: application/json' \
  --header 'Authorization: Bearer <APPLICATION_SERVICE_TOKEN>' \
  --data '{
    "name": "context0"
  }'
```

Example response:

```json
{
  "name": "context0",
  "quotas": {
    "max_active_disk_gb": null,
    "max_active_ram_gb": null,
    "max_active_cpu_cores": null,
    "max_ram_gb_request": null,
    "max_disk_gb_request": null,
    "max_cpu_cores_request": null,
    "max_active_tasks": null,
    "total_tasks": null,
    "max_executors_request": null
  }
}
```

---

## 7. Create a User

```bash
curl --location 'http://<SCHEMA_API_HOST>:<SCHEMA_API_NODEPORT>/api_auth/users' \
  --header 'Content-Type: application/json' \
  --header 'Authorization: Bearer <APPLICATION_SERVICE_TOKEN>' \
  --data '{
    "username": "user0"
  }'
```

Example response:

```json
{
  "username": "user0",
  "is_active": true,
  "fs_user_dir": "user0"
}
```

---

## 8. Register the User in the Context

```bash
curl --location 'http://<SCHEMA_API_HOST>:<SCHEMA_API_NODEPORT>/api_auth/contexts/context0/users' \
  --header 'Content-Type: application/json' \
  --header 'Authorization: Bearer <APPLICATION_SERVICE_TOKEN>' \
  --data '{
    "username": "user0"
  }'
```

Example response:

```json
{
  "name": "context0",
  "quotas": {
    "max_active_disk_gb": null,
    "max_active_ram_gb": null,
    "max_active_cpu_cores": null,
    "max_ram_gb_request": null,
    "max_disk_gb_request": null,
    "max_cpu_cores_request": null,
    "max_active_tasks": null,
    "total_tasks": null,
    "max_executors_request": null
  },
  "users": [
    {
      "username": "user0",
      "is_active": true
    }
  ]
}
```

---

## 9. Issue a Token for the User

```bash
curl --location 'http://<SCHEMA_API_HOST>:<SCHEMA_API_NODEPORT>/api_auth/contexts/context0/users/user0/tokens' \
  --header 'Content-Type: application/json' \
  --header 'Authorization: Bearer <APPLICATION_SERVICE_TOKEN>' \
  --data '{
    "expiry": "2028-01-20T00:00:00"
  }'
```

Example response:

```json
{
  "uuid": "<TOKEN_UUID>",
  "title": "",
  "hint": "<TOKEN_HINT>",
  "expiry": "2028-01-27T00:00:00Z",
  "is_active": true,
  "created": "2026-01-27T13:57:17.189219Z",
  "token": "<USER_TOKEN>"
}
```

Store the user token securely.

---

## 10. Create the User Bucket in MinIO / S3

To enable upload/download functionality, create a bucket in MinIO/S3 using the UUID associated with the created user.

You can also first try to upload a file through the normal flow. If that works, you may not need to inspect PostgreSQL manually.

First, enter the PostgreSQL pod:

```bash
kubectl exec -it <POSTGRES_POD> -n postgres-operator -- psql
```

Then connect to the Schema database:

```sql
\c schema
select * from api_auth_authentity;
```

Locate the relevant UUID, then create a bucket in MinIO/S3 with that exact UUID as the bucket name.

Once the bucket exists, the user can upload and download files.

---

## Troubleshooting

### `schema-api-watch` is in `CrashLoopBackOff`
This may happen before database migrations are applied.

**Fix:**
1. Enter the `schema-api` pod
2. Run:

```bash
python manage.py migrate
```

3. Restart the deployment if needed:

```bash
kubectl rollout restart deployment/schema-api-watch -n schema-api
```

### Schema-Lab cannot reach Schema-API

Check the following:

- `schemaApiUrl` in `schema-lab-local.yaml`
- `corsOrigins` in `schema-api-local-template.yaml`
- service exposure (`NodePort`, ingress, or load balancer)

### Requests fail with host validation errors

Make sure the Schema-API public host/IP is included in:

```yaml
allowedHosts
```
- Try Minio with `requestAutoCert: false`

### File upload/download does not work

Check the following:

- MinIO/S3 credentials
- bucket creation
- bucket name matches the correct user UUID
- `s3Url` is reachable from Schema-API
- Try Minio with `requestAutoCert: false`

---

## Notes

- Do not commit real secrets, tokens, or passwords to Git.
- Prefer placeholders such as `<NODE_IP>`, `<TOKEN>`, and `<S3_ENDPOINT>` in documentation examples.
- If you use NodePort, verify that the selected ports are reachable from outside the cluster.
- Re-apply manifests after changing ConfigMaps or Secrets, and restart deployments when necessary.

---

## Example Deployment Order

A recommended deployment order is:

1. Deploy the Kubernetes storage class
2. Deploy MinIO / S3-compatible storage
3. Deploy TESK
4. Deploy PostgreSQL
5. Fill in and apply `schema-api-local-template.yaml`
6. Run database migrations
7. Fill in and apply `schema-lab-local.yaml`
8. Register application service, context, and users
9. Create the S3 bucket for each user UUID or try to upload a file first from UI.
