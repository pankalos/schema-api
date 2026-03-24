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

## Prerequisites

Before deploying Schema-API and Schema-Lab, make sure the following are available:

### 1. Kubernetes
A working Kubernetes cluster is required.

### 2. Storage Class
To handle tasks with I/O [TESK](https://github.com/elixir-cloud-aai/TESK/blob/master/documentation/deployment.md) creates temporary PVCs.
You need a storage class that supports creation of temporary PVCs.

- Support for **ReadWriteOnce (RWO)** is sufficient.
- This demo was tested with [**NFS**](https://github.com/kubernetes-sigs/nfs-ganesha-server-and-external-provisioner.git).

### 3. Storage Backend for External I/O
[TESK](https://github.com/elixir-cloud-aai/TESK/blob/master/documentation/deployment.md) requires a backend for exchanging files with the external world.

Currently supported backends include:

- **FTP**: read/write access to a single FTP account
- **Shared filesystem**: usually provided through a **ReadWriteMany (RWX)** PVC
- **S3-compatible storage** *(work in progress)*: read/write access to a single bucket

In this deployment, [**MinIO**](https://docs.min.io/enterprise/aistor-object-store/installation/kubernetes/) was used as the S3-compatible backend.

### 4. TESK
[TESK](https://github.com/elixir-cloud-aai/TESK/tree/master) is an implementation of a task execution engine based on the TES standard and running on Kubernetes.

TESK can be deployed once the storage class and storage backend are available.

Useful links:
- [TESK repository](https://github.com/elixir-cloud-aai/TESK?tab=readme-ov-file)
- [TESK deployment documentation](https://github.com/elixir-cloud-aai/TESK/blob/master/documentation/deployment.md)

### 5. PostgreSQL
Schema-API requires **PostgreSQL** as its backend database.
You can choose any PostgreSQL installation at your desposal.
[**Crunchy PostgreSQL**](https://access.crunchydata.com/documentation/postgres-operator/latest/tutorials/basic-setup/create-cluster) used for this demo deployment.

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
