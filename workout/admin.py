from django.contrib import admin
from workout.models import Exercise, WorkoutExerciseLog, WorkoutGoal, WorkoutPlan, WorkoutPlanExercise, WorkoutSession

for model in [Exercise, WorkoutPlan, WorkoutPlanExercise, WorkoutSession, WorkoutExerciseLog, WorkoutGoal]:
    admin.site.register(model)
