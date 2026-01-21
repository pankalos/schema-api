from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
User = get_user_model()


class TimescaleStreamDB(models.Model):
    id = models.CharField(primary_key=True, max_length=32)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    namespace = models.CharField(max_length=64, default="schema-api")

    pod_modeler_name  = models.CharField(max_length=128)
    svc_modeler_name  = models.CharField(max_length=128)
    pod_listener_name = models.CharField(max_length=128)

    # capture full configs for audit/debug
    psql_in  = models.JSONField()   # host, port, db, user, table_in, cols_in, time_col_in, everyTs
    psql_out = models.JSONField()   # table_out, time_col_out, cols_types_out, hypertable opts
    modeler  = models.JSONField()   # image, port, endpoint, args (optional)

    created_at = models.DateTimeField(auto_now_add=True)
    total_runtime = models.DurationField(null=True, blank=True)
    status = models.CharField(max_length=32, default="created")

    @property
    def computed_runtime(self):
        if self.total_runtime is not None:
            return self.total_runtime
        return timezone.now() - self.created_at
