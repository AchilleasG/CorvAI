from django.shortcuts import render

# Create your views here.
from ninja import NinjaAPI
from input.views import router as input_router
from chat.views import router as chat_router
from orchestration.views import router as orchestration_router
from study.views import router as study_router
from workout.views import router as workout_router
from ssh_connections.views import router as ssh_router
from coding.views import router as coding_router
from coding.files import router as files_router

api = NinjaAPI(title="CorvAPI")

api.add_router("/input",input_router)
api.add_router("/chats", chat_router)
api.add_router("/orchestration", orchestration_router)
api.add_router("/study", study_router)
api.add_router("/workout", workout_router)
api.add_router("/ssh", ssh_router)
api.add_router("/coding", coding_router)
api.add_router("/files", files_router)
