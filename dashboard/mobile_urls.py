from django.urls import path

from .mobile_api import (
    MobileDashboardView,
    MobileCreateRecordView,
    MobileLoadActionView,
    MobileLoadsView,
    MobileLoginView,
    MobileLogoutView,
    MobileWorkspaceView,
)

urlpatterns = [
    path("login/", MobileLoginView.as_view(), name="mobile_login"),
    path("logout/", MobileLogoutView.as_view(), name="mobile_logout"),
    path("dashboard/", MobileDashboardView.as_view(), name="mobile_dashboard"),
    path("loads/", MobileLoadsView.as_view(), name="mobile_loads"),
    path("workspace/", MobileWorkspaceView.as_view(), name="mobile_workspace"),
    path("records/", MobileCreateRecordView.as_view(), name="mobile_create_record"),
    path("loads/<int:load_id>/<str:action>/", MobileLoadActionView.as_view(), name="mobile_load_action"),
]
