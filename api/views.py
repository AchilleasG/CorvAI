from django.shortcuts import render

# Create your views here.
from ninja import NinjaAPI
from input.views import router as input_router


api = NinjaAPI(title="CorvAPI")

api.add_router("/input",input_router)