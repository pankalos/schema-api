from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class InfluxDB(models.Model):
    id = models.CharField(primary_key=True, max_length=32)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    namespace = models.CharField(max_length=64, default="schema-api")

    pod_modeler_name = models.CharField(max_length=128)
    svc_modeler_name = models.CharField(max_length=128)
    pod_listener_name = models.CharField(max_length=128)

    # NEW: store only the profile name chosen by the user (no credentials stored)
    db_profile = models.CharField(max_length=64)

    # non-secret configs only
    influx_in = models.JSONField()    # bucket, measurement, tags, cols, everyTs
    influx_out = models.JSONField()   # bucket, measurement, tags, cols, optional time_col_out/write_precision
    modeler = models.JSONField()      # image, port, endpoint, args, include_time_to_mod

    created_at = models.DateTimeField(auto_now_add=True)
    total_runtime = models.DurationField(null=True, blank=True)
    status = models.CharField(max_length=32, default="created")

    def __str__(self):
        return f"{self.user.username} - {self.id}"

    @property
    def computed_runtime(self):
        if self.total_runtime is not None:
            return self.total_runtime
        return timezone.now() - self.created_at
