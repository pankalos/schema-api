from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class LeafInfluxDB(models.Model):
    id = models.CharField(primary_key=True, max_length=32)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    namespace = models.CharField(max_length=64, default="schema-api")

    pod_modeler_name = models.CharField(max_length=128)
    svc_modeler_name = models.CharField(max_length=128)
    pod_listener_name = models.CharField(max_length=128)

    # Non-secret source config only. Do NOT persist token/password.
    source = models.JSONField()
    modeler = models.JSONField()

    # MQTT is always required now.
    # We still persist only the safe mqtt config, without password.
    mqtt = models.JSONField()

    created_at = models.DateTimeField(auto_now_add=True)
    total_runtime = models.DurationField(null=True, blank=True)

    status = models.CharField(max_length=32, default="Queued")
    status_updated_at = models.DateTimeField(default=timezone.now)

    error_message = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.id}"

    @property
    def computed_runtime(self):
        if self.total_runtime is not None:
            return self.total_runtime
        return timezone.now() - self.created_at
