# Kubernetes Deployment Guide for Schema-API and Schema-Lab

This guide explains how to deploy **Schema-API** and **Schema-Lab** on **Kubernetes**.

## Overview

To deploy the platform, you need the following components:

1. A Kubernetes cluster
2. A storage class that supports at least RWO mode
3. A storage backend for exchanging input/output with the external world
4. [TESK](https://github.com/elixir-cloud-aai/TESK?tab=readme-ov-file)
5. PostgreSQL for Schema API backend
6. [Schema-API](https://schema.athenarc.gr/docs/schema-api/)
7. Schema-Lab

---

## Quick Deployment Guides

The following quick guides describe one working deployment flow for the required dependencies of **Schema-API** and **Schema-Lab**:

1. NFS storage provisioner
2. MinIO
3. PostgreSQL
4. TESK

> **Note:** These steps reflect the deployment approach used in this project and the attached template instructions.

---

## 1. Quick Deployment Guide: NFS

This NFS provisioner is used to provide a storage class that supports dynamic PVC/PV creation. In this setup, the storage class name is `storageclass-nfs`.

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

> Deleting the PVC will also delete the dynamically provisioned PV and its data. If the provisioner deployment is removed, existing PVs become unusable until it is restored.

---

## 2. Quick Deployment Guide: MinIO

MinIO is used here as the S3-compatible storage backend. The deployment uses the **MinIO Operator** and a **Tenant**, both installed from local Helm charts. 

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

If `requestAutoCert: false`, access the console over HTTP using the NodePort shown for the console service. If `requestAutoCert: true`, use HTTPS instead. The uploaded instructions use credentials like:

```text
username: minio
password: minio-password
```

> Keep real credentials out of the README and replace them with placeholders in your public docs. 

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

Schema-API requires PostgreSQL. In this setup, PostgreSQL is deployed with **Crunchy Postgres for Kubernetes** using a Helm-based examples repository. The guide assumes that `storageclass-nfs` is the cluster default, or that you explicitly set it in the values file. 

### 1. Clone the examples repository

```bash
git clone https://github.com/pankalos/postgres-operator-examples
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

Example values from the uploaded guide:

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

Example test file contents:

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

Example request:

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

The uploaded notes mention that after repeated `helm upgrade --install` commands, the **service IP** may change. Since the service is configured as **NodePort** with `node_port: 31567`, the more stable public access method is usually:

```text
http://<NODE_IP>:31567/v1/tasks
```

instead of relying on an internal ClusterIP. That makes the README more reliable for users deploying on their own cluster. This is an inference based on your TESK service configuration and example commands. 

---

## Recommended Dependency Order

Deploy the dependencies in this order:

1. NFS
2. MinIO
3. PostgreSQL
4. TESK

After all four are ready, continue with:

5. Schema-API
6. Schema-Lab

---

## Deployment Files

The following template files are provided and should be filled in with values matching your environment:

- `schema-api-local-template.yaml`
- `schema-lab-local.yaml`

---

## 1. Configure Schema-API

Edit `schema-api-local-template.yaml` and update the values according to your environment.

At minimum, review and update:

- PostgreSQL connection details
- S3/MinIO credentials
- `allowedHosts`
- `s3Url`
- `teskEndpoint`
- `corsOrigins`
- secret keys
- any image names or database profile settings you use

### Important settings to review

#### Database
Set the PostgreSQL database name, user, password, host, and port.

#### S3 / MinIO
Set:

- S3 endpoint URL
- access key
- secret key
- SSL settings

#### Allowed Hosts
If you expose Schema-API using **NodePort**, make sure the service IP or hostname is included in `allowedHosts`.

#### CORS
Set `corsOrigins` to the public URL of Schema-Lab.

#### TESK Endpoint
Set `teskEndpoint` to the reachable TESK API endpoint.

---

## 2. Apply the Schema-API Deployment

After filling in the template, apply it:

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

Example:

```bash
kubectl get pods -n schema-api
kubectl exec -n schema-api -it <schema-api-pod-name> -- sh
```

Inside the container:

```bash
python manage.py migrate
```

Wait until the pods become healthy:

```bash
kubectl get pods -n schema-api
```

Example output may initially look like this:

```text
pod/schema-api-xxxxx                1/1   Running
pod/schema-api-cache-xxxxx          1/1   Running
pod/schema-api-watch-xxxxx          0/1   CrashLoopBackOff
pod/schema-workers-xxxxx            1/1   Running
```

After migrations complete, `schema-api-watch` should recover.

---

## 4. Configure and Deploy Schema-Lab

Edit `schema-lab-local.yaml` and set the Schema-API URL accordingly.

Example:

```yaml
schemaApiUrl: http://<NODE_IP>:30090
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
kubectl exec -n schema-api -it <schema-api-pod-name> -- sh
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
curl --location 'http://<NODE_IP>:30090/api_auth/contexts' \
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
curl --location 'http://<NODE_IP>:30090/api_auth/users' \
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
curl --location 'http://<NODE_IP>:30090/api_auth/contexts/context0/users' \
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
curl --location 'http://<NODE_IP>:30090/api_auth/contexts/context0/users/user0/tokens' \
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
(Or just try to upload a file in the S3. If everything goes well you will not need the following)

First, enter the PostgreSQL pod:

```bash
kubectl exec -it <postgres-pod-name> -n postgres-operator -- psql
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

### File upload/download does not work
Check the following:

- MinIO/S3 credentials
- bucket creation
- bucket name matches the correct user UUID
- `s3Url` is reachable from Schema-API

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
9. Create the S3 bucket for each user UUID
