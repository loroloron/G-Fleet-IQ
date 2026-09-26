from django.contrib import admin
from django.urls import path, include
from django.views.i18n import set_language
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.contrib.auth import views as auth_views
from dashboard import views as dashboard_views

urlpatterns = [

    path("admin/", admin.site.urls),
    path("i18n/setlang/", set_language, name="set_language"),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("sign-up/", dashboard_views.sign_up, name="sign_up"),
    path("account/setup/", dashboard_views.account_setup, name="account_setup"),
    path("account/team/", dashboard_views.account_team, name="account_team"),
    path("clients/<int:company_id>/team/", dashboard_views.client_team, name="client_team"),

    path("", include("dashboard.urls")),

]

urlpatterns += staticfiles_urlpatterns()
