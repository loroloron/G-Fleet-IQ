from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("drivers/", views. drivers, name="drivers"),
    path("drivers/<int:driver_id>/edit/", views.edit_driver, name="edit_driver"),
    path("customers/", views.customers, name="customers"),
    path("trucks/", views.trucks, name="trucks"),
    path("loads/", views.loads, name="loads"),
    path("trailers/", views.trailers, name="trailers"),
    path("ai-dispatch/", views.ai_dispatch, name="ai_dispatch"),
    path("dispatch-board/", views.dispatch_board, name="dispatch_board"),
    path(
    "assign-load/<int:load_id>/",
    views.assign_load,
    name="assign_load",
),
    path("trucks/<int:truck_id>/edit/", views.edit_truck, name="edit_truck"),
    path("trucks/add/", views.add_truck, name="add_truck"),
   path("drivers/add/", views.add_driver, name="add_driver"), 
   path("trucks/add/", views.add_truck, name="add_truck"),
   path("trailers/add/", views.add_trailer, name="add_trailer"),
   path("trailers/<int:trailer_id>/edit/", views.edit_trailer, name="edit_trailer"),
   path(
    "drivers/<int:driver_id>/delete/",
    views.delete_driver,
    name="delete_driver",
),
    path(
    "trucks/<int:truck_id>/delete/",
    views.delete_truck,
    name="delete_truck",
),
path(
    "trailers/<int:trailer_id>/delete/",
    views.delete_trailer,
    name="delete_trailer",
),
path(
    "trailers/<int:trailer_id>/delete/",
    views.delete_trailer,
    name="delete_trailer",
),
path(
    "customers/<int:customer_id>/delete/",
    views.delete_customer,
    name="delete_customer",
),
path("loads/", views.loads, name="loads"),
path("loads/<int:load_id>/", views.load_detail, name="load_detail"),
path("loads/<int:load_id>/edit/", views.edit_load, name="edit_load"),
path("loads/<int:load_id>/delete/", views.delete_load, name="delete_load"),
path("companies/", views.companies, name="companies"),
path("fleet-map/", views.fleet_map, name="fleet_map"),
path("trucks/<int:truck_id>/", views.truck_detail, name="truck_detail"),
path(
    "assign-load/<int:load_id>/",
    views.assign_load,
    name="assign_load",
),
path(
    "plan-all-loads/",
    views.plan_all_loads,
    name="plan_all_loads",
),
]