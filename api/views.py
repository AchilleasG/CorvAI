from django.shortcuts import render

# Create your views here.
from ninja import NinjaAPI
from input.views import router as input_router
from chat.views import router as chat_router
from orchestration.views import router as orchestration_router
from study.views import router as study_router

api = NinjaAPI(title="CorvAPI")

api.add_router("/input",input_router)
api.add_router("/chats", chat_router)
api.add_router("/orchestration", orchestration_router)
api.add_router("/study", study_router)
