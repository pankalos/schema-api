from django.urls import path

from api.views import UserQuotasAPIView, TasksListCreateAPIView, TaskRetrieveAPIView, TaskStdoutAPIView, \
    TaskStderrAPIView, UserContextInfoAPIView, TaskCancelAPIView
from api_auth.views import ContextsAPIView, ContextDetailsAPIView

from api_streaming.views import (
    StreamingDispatcherView,
    StreamingDispatcherDetailView,
    StreamingDispatcherTerminateView
)


urlpatterns = [
    path(r'tasks', TasksListCreateAPIView.as_view(), name='tasks'),
    path(r'tasks/<uuid:uuid>', TaskRetrieveAPIView.as_view(), name='tasks2'),
    path(r'tasks/<uuid:uuid>/stdout', TaskStdoutAPIView.as_view(), name='task_stdout'),
    path(r'tasks/<uuid:uuid>/stderr', TaskStderrAPIView.as_view(), name='task_stderr'),
    path(r'tasks/<uuid:uuid>/cancel', TaskCancelAPIView.as_view(), name='task_cancel'),
    path(r'contexts', ContextsAPIView.as_view(), name='user-contexts'),
    path(r'contexts/<name>', ContextDetailsAPIView.as_view(), name='user-context-details'),
    # Temporary url - expected to be removed in the future

    # Streaming DB's
    path('streaming', StreamingDispatcherView.as_view(), name='streaming-dispatcher'),
    path('streaming/<str:task_id>', StreamingDispatcherDetailView.as_view(), name='streaming-detail'),
    path('streaming/<str:task_id>/terminate', StreamingDispatcherTerminateView.as_view(), name='streaming-terminate'),

    path(r'context-info', UserContextInfoAPIView.as_view(), name='user-context-info'),
    path(r'quotas', UserQuotasAPIView.as_view(), name='user_quotas'),
]
